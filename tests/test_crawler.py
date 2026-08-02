from site_auditor.crawler import (
    RobotsPolicy,
    WebsiteCrawler,
    normalize_crawl_url,
)
from site_auditor.models import (
    FetchResult,
    LinkData,
    PageData,
    PageScanResult,
)


class StubScanner:
    """Return predefined page results by URL."""

    def __init__(
        self,
        results: dict[str, PageScanResult],
    ) -> None:
        self.results = results
        self.requested_urls: list[str] = []

    def scan_page(
        self,
        url: str,
    ) -> PageScanResult:
        self.requested_urls.append(url)
        return self.results[url]


class StaticRobotsLoader:
    """Return one predefined robots policy."""

    def __init__(
        self,
        policy: RobotsPolicy,
    ) -> None:
        self.policy = policy

    def load(
        self,
        start_url: str,
    ) -> RobotsPolicy:
        del start_url
        return self.policy


def create_page_result(
    url: str,
    links: list[str] | None = None,
) -> PageScanResult:
    page_links = [
        LinkData(
            index=index,
            text=f"Link {index}",
            href=link,
            resolved_url=link,
            is_internal=True,
        )
        for index, link in enumerate(
            links or [],
            start=1,
        )
    ]

    return PageScanResult(
        fetch_result=FetchResult(
            requested_url=url,
            final_url=url,
            fetch_succeeded=True,
            status_code=200,
            content_type="text/html",
            encoding="utf-8",
            is_html=True,
        ),
        page_data=PageData(
            url=url,
            title="Example page",
            word_count=100,
            links=page_links,
        ),
    )


def test_crawls_internal_pages_without_duplicates() -> None:
    start_url = "https://example.com/"
    about_url = "https://example.com/about"
    contact_url = "https://example.com/contact"

    scanner = StubScanner(
        {
            start_url: create_page_result(
                start_url,
                links=[
                    about_url,
                    about_url,
                    contact_url,
                    "https://external.example.org/page",
                    "https://example.com/image.png",
                ],
            ),
            about_url: create_page_result(
                about_url,
                links=[contact_url],
            ),
            contact_url: create_page_result(
                contact_url,
            ),
        }
    )

    crawler = WebsiteCrawler(scanner)

    result = crawler.crawl(
        start_url,
        max_pages=10,
        request_delay_seconds=0,
        respect_robots_txt=False,
    )

    assert scanner.requested_urls == [
        start_url,
        about_url,
        contact_url,
    ]

    assert len(result.pages) == 3
    assert result.metadata.reached_page_limit is False


def test_stops_at_page_limit() -> None:
    start_url = "https://example.com/"
    first_url = "https://example.com/first"
    second_url = "https://example.com/second"

    scanner = StubScanner(
        {
            start_url: create_page_result(
                start_url,
                links=[first_url, second_url],
            ),
            first_url: create_page_result(first_url),
            second_url: create_page_result(second_url),
        }
    )

    crawler = WebsiteCrawler(scanner)

    result = crawler.crawl(
        start_url,
        max_pages=2,
        request_delay_seconds=0,
        respect_robots_txt=False,
    )

    assert len(result.pages) == 2
    assert result.metadata.reached_page_limit is True


def test_respects_robots_txt() -> None:
    start_url = "https://example.com/"
    public_url = "https://example.com/public"
    private_url = "https://example.com/private"

    scanner = StubScanner(
        {
            start_url: create_page_result(
                start_url,
                links=[public_url, private_url],
            ),
            public_url: create_page_result(public_url),
        }
    )

    policy = RobotsPolicy.from_text(
        """
        User-agent: WebsiteQualityAuditor
        Disallow: /private
        """,
        robots_txt_url=("https://example.com/robots.txt"),
    )

    crawler = WebsiteCrawler(
        scanner,
        robots_loader=StaticRobotsLoader(policy),
    )

    result = crawler.crawl(
        start_url,
        max_pages=10,
        request_delay_seconds=0,
        respect_robots_txt=True,
    )

    assert scanner.requested_urls == [
        start_url,
        public_url,
    ]

    assert result.metadata.robots_blocked_urls == [private_url]


def test_normalizes_fragments_and_tracking_parameters() -> None:
    result = normalize_crawl_url("HTTPS://EXAMPLE.COM:443/products?utm_source=test&b=2&a=1#details")

    assert result == ("https://example.com/products?a=1&b=2")
