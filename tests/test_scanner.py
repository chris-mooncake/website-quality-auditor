from site_auditor.models import FetchResult
from site_auditor.scanner import BatchScanner

VALID_HTML = """
<!doctype html>
<html lang="en">
<head>
    <title>A useful example page title</title>
    <meta
        name="description"
        content="This is a sufficiently detailed description of the test page."
    >
    <meta name="viewport" content="width=device-width">
    <link rel="canonical" href="/page">
</head>
<body>
    <h1>Example page</h1>
    <p>
        This page contains enough visible text to demonstrate that the
        scanner can fetch, parse, audit, and retain structured results.
    </p>
</body>
</html>
"""


class StubFetcher:
    """Return predefined fetch results without making network requests."""

    def __init__(
        self,
        results: list[FetchResult],
    ) -> None:
        self.results = iter(results)

    def fetch(self, url: str) -> FetchResult:
        result = next(self.results)

        assert result.requested_url == url

        return result


def create_html_result(
    url: str,
    *,
    headers: dict[str, str] | None = None,
) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        fetch_succeeded=True,
        status_code=200,
        reason_phrase="OK",
        content_type="text/html",
        encoding="utf-8",
        body_size_bytes=len(VALID_HTML.encode()),
        is_html=True,
        html=VALID_HTML,
        headers=headers or {},
    )


def test_scans_multiple_urls_in_order() -> None:
    first_url = "https://example.com/first"
    second_url = "https://example.com/second"

    fetcher = StubFetcher(
        [
            create_html_result(first_url),
            create_html_result(second_url),
        ]
    )

    scanner = BatchScanner(fetcher)

    results = list(
        scanner.scan_urls(
            [first_url, second_url],
            request_delay_seconds=0,
        )
    )

    assert len(results) == 2

    assert results[0].fetch_result.requested_url == first_url
    assert results[1].fetch_result.requested_url == second_url

    assert results[0].page_data is not None
    assert results[1].page_data is not None


def test_continues_after_fetch_failure() -> None:
    failed_url = "https://example.com/failure"
    successful_url = "https://example.com/success"

    failed_result = FetchResult(
        requested_url=failed_url,
        fetch_succeeded=False,
        error_type="timeout",
        error_message="The request timed out.",
    )

    fetcher = StubFetcher(
        [
            failed_result,
            create_html_result(successful_url),
        ]
    )

    scanner = BatchScanner(fetcher)

    results = list(
        scanner.scan_urls(
            [failed_url, successful_url],
            request_delay_seconds=0,
        )
    )

    assert len(results) == 2

    assert results[0].page_data is None
    assert results[0].issues[0].rule_id == "technical.fetch_failed"

    assert results[1].page_data is not None


def test_records_non_html_resource() -> None:
    url = "https://example.com/document.pdf"

    fetch_result = FetchResult(
        requested_url=url,
        final_url=url,
        fetch_succeeded=True,
        status_code=200,
        content_type="application/pdf",
        body_size_bytes=0,
        is_html=False,
    )

    scanner = BatchScanner(StubFetcher([fetch_result]))

    result = scanner.scan_page(url)

    assert result.page_data is None
    assert len(result.issues) == 1
    assert result.issues[0].rule_id == "technical.non_html_resource"


def test_removes_html_and_redacts_sensitive_headers() -> None:
    url = "https://example.com/page"

    fetch_result = create_html_result(
        url,
        headers={
            "content-type": "text/html",
            "set-cookie": "session=secret-value",
            "server": "example-server",
        },
    )

    scanner = BatchScanner(StubFetcher([fetch_result]))

    result = scanner.scan_page(url)

    assert result.page_data is not None
    assert result.fetch_result.html is None

    assert result.fetch_result.headers["set-cookie"] == "[REDACTED]"
    assert result.fetch_result.headers["server"] == "example-server"
