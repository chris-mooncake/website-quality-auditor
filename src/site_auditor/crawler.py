from __future__ import annotations

from collections import deque
from collections.abc import Callable
from pathlib import PurePosixPath
from time import sleep
from typing import Protocol
from urllib.parse import (
    parse_qsl,
    urlencode,
    urlsplit,
    urlunsplit,
)
from urllib.robotparser import RobotFileParser

import httpx

from site_auditor.fetcher import DEFAULT_USER_AGENT
from site_auditor.models import (
    CrawlMetadata,
    CrawlResult,
    PageScanResult,
)
from site_auditor.net_safety import SafeTransport

ROBOTS_USER_AGENT = "WebsiteQualityAuditor"


TRACKING_QUERY_PARAMETERS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}


NON_HTML_EXTENSIONS = {
    ".7z",
    ".avi",
    ".bmp",
    ".css",
    ".csv",
    ".doc",
    ".docx",
    ".eot",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".map",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".ogg",
    ".otf",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".rar",
    ".rss",
    ".svg",
    ".tar",
    ".tif",
    ".tiff",
    ".ttf",
    ".txt",
    ".wav",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
    ".xls",
    ".xlsx",
    ".xml",
    ".zip",
}


CrawlProgressCallback = Callable[
    [int, int, PageScanResult, int],
    None,
]


class ScannerProtocol(Protocol):
    """Interface required by the website crawler."""

    def scan_page(self, url: str) -> PageScanResult:
        """Fetch, parse, and audit one page."""


class RobotsLoaderProtocol(Protocol):
    """Interface for loading robots.txt policies."""

    def load(self, start_url: str) -> RobotsPolicy:
        """Load the robots.txt policy for a website."""


class RobotsPolicy:
    """Parsed robots.txt rules and request metadata."""

    def __init__(
        self,
        *,
        parser: RobotFileParser,
        robots_txt_url: str | None,
        status_code: int | None,
        error: str | None,
    ) -> None:
        self.parser = parser
        self.robots_txt_url = robots_txt_url
        self.status_code = status_code
        self.error = error

    @classmethod
    def allow_all(cls) -> RobotsPolicy:
        """Create a policy that permits all URLs."""

        parser = RobotFileParser()
        parser.parse([])

        return cls(
            parser=parser,
            robots_txt_url=None,
            status_code=None,
            error=None,
        )

    @classmethod
    def from_text(
        cls,
        robots_text: str,
        *,
        robots_txt_url: str,
        status_code: int = 200,
    ) -> RobotsPolicy:
        """Create a robots policy from text."""

        parser = RobotFileParser()
        parser.set_url(robots_txt_url)
        parser.parse(robots_text.splitlines())

        return cls(
            parser=parser,
            robots_txt_url=robots_txt_url,
            status_code=status_code,
            error=None,
        )

    def can_fetch(self, url: str) -> bool:
        """Return whether the crawler may fetch a URL."""

        return self.parser.can_fetch(
            ROBOTS_USER_AGENT,
            url,
        )

    def crawl_delay(self) -> float | None:
        """Return the robots crawl delay when declared."""

        delay = self.parser.crawl_delay(ROBOTS_USER_AGENT)

        if delay is None:
            return None

        return float(delay)


class HttpRobotsLoader:
    """Download and parse robots.txt using HTTPX."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.timeout_seconds = timeout_seconds

    def load(self, start_url: str) -> RobotsPolicy:
        """Load robots.txt for the starting website."""

        start_parts = urlsplit(start_url)

        robots_txt_url = urlunsplit(
            (
                start_parts.scheme,
                start_parts.netloc,
                "/robots.txt",
                "",
                "",
            )
        )

        parser = RobotFileParser()
        parser.set_url(robots_txt_url)

        try:
            with httpx.Client(
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Accept": "text/plain,*/*;q=0.5",
                },
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=True,
                transport=SafeTransport(httpx.HTTPTransport()),
            ) as client:
                response = client.get(robots_txt_url)

            if 200 <= response.status_code < 300:
                parser.parse(response.text.splitlines())
            else:
                # Missing or unavailable robots.txt:
                # continue with an allow-all policy while recording
                # the returned status.
                parser.parse([])

            return RobotsPolicy(
                parser=parser,
                robots_txt_url=robots_txt_url,
                status_code=response.status_code,
                error=None,
            )

        except httpx.HTTPError as error:
            parser.parse([])

            message = str(error).strip() or error.__class__.__name__

            return RobotsPolicy(
                parser=parser,
                robots_txt_url=robots_txt_url,
                status_code=None,
                error=message,
            )


class WebsiteCrawler:
    """Discover and scan internal HTML pages."""

    def __init__(
        self,
        scanner: ScannerProtocol,
        *,
        robots_loader: RobotsLoaderProtocol | None = None,
    ) -> None:
        self.scanner = scanner
        self.robots_loader = robots_loader or HttpRobotsLoader()

    def crawl(
        self,
        start_url: str,
        *,
        max_pages: int,
        request_delay_seconds: float,
        respect_robots_txt: bool,
        progress_callback: CrawlProgressCallback | None = None,
    ) -> CrawlResult:
        """Crawl one website using a breadth-first queue."""

        if max_pages < 1:
            raise ValueError("max_pages must be at least 1.")

        if request_delay_seconds < 0:
            raise ValueError("request_delay_seconds cannot be negative.")

        normalized_start_url = normalize_crawl_url(start_url)

        if normalized_start_url is None:
            raise ValueError("The starting URL is not a valid HTTP or HTTPS URL.")

        if respect_robots_txt:
            robots_policy = self.robots_loader.load(normalized_start_url)
        else:
            robots_policy = RobotsPolicy.allow_all()

        robots_delay = robots_policy.crawl_delay() if respect_robots_txt else None

        effective_delay_seconds = max(
            request_delay_seconds,
            robots_delay or 0.0,
        )

        queue: deque[str] = deque([normalized_start_url])

        queued_urls = {normalized_start_url}
        visited_urls: set[str] = set()
        discovered_urls = {normalized_start_url}

        robots_blocked_urls: list[str] = []
        skipped_url_count = 0

        page_results: list[PageScanResult] = []

        while queue and len(page_results) < max_pages:
            current_url = queue.popleft()
            queued_urls.discard(current_url)

            if current_url in visited_urls:
                continue

            visited_urls.add(current_url)

            if respect_robots_txt and not robots_policy.can_fetch(current_url):
                robots_blocked_urls.append(current_url)
                continue

            page_result = self.scanner.scan_page(current_url)

            page_results.append(page_result)

            final_url = page_result.fetch_result.final_url

            if final_url:
                normalized_final_url = normalize_crawl_url(final_url)

                if normalized_final_url is not None:
                    visited_urls.add(normalized_final_url)

            if page_result.page_data is not None:
                for link in page_result.page_data.links:
                    if link.resolved_url is None:
                        continue

                    candidate_url = normalize_crawl_url(link.resolved_url)

                    if candidate_url is None:
                        skipped_url_count += 1
                        continue

                    if not is_same_site(
                        candidate_url,
                        normalized_start_url,
                    ):
                        skipped_url_count += 1
                        continue

                    if should_skip_crawl_url(candidate_url):
                        skipped_url_count += 1
                        continue

                    discovered_urls.add(candidate_url)

                    if candidate_url in visited_urls or candidate_url in queued_urls:
                        continue

                    queue.append(candidate_url)
                    queued_urls.add(candidate_url)

            if progress_callback is not None:
                progress_callback(
                    len(page_results),
                    max_pages,
                    page_result,
                    len(queue),
                )

            should_wait = (
                bool(queue) and len(page_results) < max_pages and effective_delay_seconds > 0
            )

            if should_wait:
                sleep(effective_delay_seconds)

        reached_page_limit = len(page_results) >= max_pages and bool(queue)

        metadata = CrawlMetadata(
            start_url=normalized_start_url,
            discovered_url_count=len(discovered_urls),
            skipped_url_count=skipped_url_count,
            robots_blocked_urls=robots_blocked_urls,
            reached_page_limit=reached_page_limit,
            robots_txt_url=(robots_policy.robots_txt_url if respect_robots_txt else None),
            robots_txt_status_code=(robots_policy.status_code if respect_robots_txt else None),
            robots_txt_error=(robots_policy.error if respect_robots_txt else None),
            effective_delay_seconds=(effective_delay_seconds),
        )

        return CrawlResult(
            pages=page_results,
            metadata=metadata,
        )


def normalize_crawl_url(
    raw_url: str,
) -> str | None:
    """
    Normalize a URL for crawl deduplication.

    Fragments and common marketing-tracking parameters are removed.
    """

    value = raw_url.strip()

    if not value:
        return None

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None

    scheme = parsed.scheme.lower()
    hostname = parsed.hostname

    if scheme not in {"http", "https"}:
        return None

    if hostname is None:
        return None

    if parsed.username or parsed.password:
        return None

    normalized_hostname = hostname.lower()

    if ":" in normalized_hostname:
        normalized_hostname = f"[{normalized_hostname}]"

    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)

    if port is not None and not default_port:
        netloc = f"{normalized_hostname}:{port}"
    else:
        netloc = normalized_hostname

    path = parsed.path or "/"

    query_pairs = [
        (name, value)
        for name, value in parse_qsl(
            parsed.query,
            keep_blank_values=True,
        )
        if (name.casefold() not in TRACKING_QUERY_PARAMETERS)
    ]

    query_pairs.sort()

    normalized_query = urlencode(
        query_pairs,
        doseq=True,
    )

    return urlunsplit(
        (
            scheme,
            netloc,
            path,
            normalized_query,
            "",
        )
    )


def is_same_site(
    candidate_url: str,
    start_url: str,
) -> bool:
    """Check whether two URLs belong to the same host scope."""

    candidate_hostname = urlsplit(candidate_url).hostname

    start_hostname = urlsplit(start_url).hostname

    if candidate_hostname is None or start_hostname is None:
        return False

    return _scope_hostname(candidate_hostname) == _scope_hostname(start_hostname)


def should_skip_crawl_url(url: str) -> bool:
    """Return whether a URL appears to target a non-HTML asset."""

    path = urlsplit(url).path
    extension = PurePosixPath(path).suffix.lower()

    return extension in NON_HTML_EXTENSIONS


def _scope_hostname(hostname: str) -> str:
    """
    Normalize the hostname for crawl scope.

    This treats example.com and www.example.com as the same scope,
    but does not automatically include arbitrary subdomains.
    """

    normalized = hostname.casefold()

    if normalized.startswith("www."):
        return normalized[4:]

    return normalized
