from __future__ import annotations

from time import perf_counter
from typing import Self

import httpx

from site_auditor.models import FetchResult, RedirectHop
from site_auditor.net_safety import BlockedUrlError, SafeTransport

HTML_CONTENT_TYPES = {
    "text/html",
    "application/xhtml+xml",
}

DEFAULT_USER_AGENT = "WebsiteQualityAuditor/0.1 (local website quality auditing application)"


class PageFetcher:
    """
    Fetch web pages using a reusable HTTP client.

    The client follows redirects, measures request duration, limits the
    downloaded response size, and converts network failures into FetchResult
    objects instead of raising them to the interface.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        max_body_size_bytes: int = 5 * 1024 * 1024,
        max_redirects: int = 10,
        user_agent: str = DEFAULT_USER_AGENT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")

        if max_body_size_bytes <= 0:
            raise ValueError("max_body_size_bytes must be greater than zero.")

        if max_redirects < 0:
            raise ValueError("max_redirects cannot be negative.")

        self.max_body_size_bytes = max_body_size_bytes

        self._client = httpx.Client(
            headers={
                "User-Agent": user_agent,
                "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
                "Accept-Language": "en-US,en;q=0.8",
            },
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
            max_redirects=max_redirects,
            transport=transport
            or SafeTransport(
                httpx.HTTPTransport(
                    limits=httpx.Limits(
                        max_connections=20,
                        max_keepalive_connections=10,
                    ),
                )
            ),
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP client."""

        self._client.close()

    def fetch(self, url: str) -> FetchResult:
        """Fetch one URL and return a structured result."""

        started_at = perf_counter()

        try:
            with self._client.stream("GET", url) as response:
                headers = {key.lower(): value for key, value in response.headers.items()}

                content_type = self._extract_content_type(headers.get("content-type"))
                is_html = content_type in HTML_CONTENT_TYPES

                declared_content_length = self._parse_content_length(headers.get("content-length"))

                redirect_chain = self._build_redirect_chain(response)

                body = bytearray()
                body_truncated = False

                if is_html:
                    for chunk in response.iter_bytes():
                        remaining_capacity = self.max_body_size_bytes - len(body)

                        if remaining_capacity <= 0:
                            body_truncated = True
                            break

                        if len(chunk) > remaining_capacity:
                            body.extend(chunk[:remaining_capacity])
                            body_truncated = True
                            break

                        body.extend(chunk)

                response_time_ms = self._elapsed_milliseconds(started_at)

                encoding = response.encoding if is_html else None
                html = None
                error_type = None
                error_message = None
                fetch_succeeded = True

                if body_truncated:
                    fetch_succeeded = False
                    error_type = "body_too_large"
                    error_message = (
                        "The HTML response exceeded the configured maximum "
                        f"size of {self.max_body_size_bytes:,} bytes."
                    )

                elif is_html:
                    html, encoding = self._decode_html(
                        body=bytes(body),
                        encoding=encoding,
                    )

                return FetchResult(
                    requested_url=url,
                    final_url=str(response.url),
                    fetch_succeeded=fetch_succeeded,
                    status_code=response.status_code,
                    reason_phrase=response.reason_phrase,
                    response_time_ms=response_time_ms,
                    content_type=content_type,
                    encoding=encoding,
                    body_size_bytes=len(body),
                    declared_content_length_bytes=declared_content_length,
                    body_truncated=body_truncated,
                    is_html=is_html,
                    html=html,
                    headers=headers,
                    redirect_chain=redirect_chain,
                    error_type=error_type,
                    error_message=error_message,
                )

        except httpx.TooManyRedirects as error:
            return self._error_result(
                requested_url=url,
                started_at=started_at,
                error_type="too_many_redirects",
                error=error,
            )

        except BlockedUrlError as error:
            return self._error_result(
                requested_url=url,
                started_at=started_at,
                error_type="unsafe_url",
                error=error,
            )

        except httpx.TimeoutException as error:
            return self._error_result(
                requested_url=url,
                started_at=started_at,
                error_type="timeout",
                error=error,
            )

        except httpx.InvalidURL as error:
            return self._error_result(
                requested_url=url,
                started_at=started_at,
                error_type="invalid_url",
                error=error,
            )

        except httpx.RequestError as error:
            return self._error_result(
                requested_url=url,
                started_at=started_at,
                error_type="request_error",
                error=error,
            )

    @staticmethod
    def _extract_content_type(raw_content_type: str | None) -> str | None:
        """Return the media type without charset parameters."""

        if raw_content_type is None:
            return None

        return raw_content_type.split(";", maxsplit=1)[0].strip().lower()

    @staticmethod
    def _parse_content_length(raw_value: str | None) -> int | None:
        """Safely parse the Content-Length header."""

        if raw_value is None:
            return None

        try:
            value = int(raw_value)
        except ValueError:
            return None

        return value if value >= 0 else None

    @staticmethod
    def _decode_html(
        *,
        body: bytes,
        encoding: str | None,
    ) -> tuple[str, str]:
        """Decode HTML using the detected encoding with a UTF-8 fallback."""

        selected_encoding = encoding or "utf-8"

        try:
            html = body.decode(selected_encoding, errors="replace")
        except LookupError:
            selected_encoding = "utf-8"
            html = body.decode(selected_encoding, errors="replace")

        return html, selected_encoding

    @staticmethod
    def _build_redirect_chain(
        response: httpx.Response,
    ) -> list[RedirectHop]:
        """Convert HTTPX redirect history into application models."""

        return [
            RedirectHop(
                status_code=redirect_response.status_code,
                url=str(redirect_response.url),
                location=redirect_response.headers.get("location"),
            )
            for redirect_response in response.history
        ]

    @staticmethod
    def _elapsed_milliseconds(started_at: float) -> float:
        elapsed_seconds = perf_counter() - started_at
        return round(elapsed_seconds * 1_000, 2)

    def _error_result(
        self,
        *,
        requested_url: str,
        started_at: float,
        error_type: str,
        error: Exception,
    ) -> FetchResult:
        """Convert an exception into a failed FetchResult."""

        message = str(error).strip() or error.__class__.__name__

        return FetchResult(
            requested_url=requested_url,
            fetch_succeeded=False,
            response_time_ms=self._elapsed_milliseconds(started_at),
            error_type=error_type,
            error_message=message,
        )
