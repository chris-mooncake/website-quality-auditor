import httpx
from site_auditor.fetcher import PageFetcher


def test_fetches_html_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            headers={
                "Content-Type": "text/html; charset=utf-8",
            },
            content=b"<html><body>Hello</body></html>",
            request=request,
        )

    transport = httpx.MockTransport(handler)

    with PageFetcher(transport=transport) as fetcher:
        result = fetcher.fetch("https://example.com")

    assert result.fetch_succeeded is True
    assert result.status_code == 200
    assert result.final_url == "https://example.com"
    assert result.content_type == "text/html"
    assert result.encoding == "utf-8"
    assert result.is_html is True
    assert result.html == "<html><body>Hello</body></html>"
    assert result.error_type is None


def test_records_redirect_chain() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(
                status_code=301,
                headers={"Location": "/final"},
                request=request,
            )

        return httpx.Response(
            status_code=200,
            headers={"Content-Type": "text/html"},
            content=b"<html><body>Final page</body></html>",
            request=request,
        )

    transport = httpx.MockTransport(handler)

    with PageFetcher(transport=transport) as fetcher:
        result = fetcher.fetch("https://example.com/start")

    assert result.fetch_succeeded is True
    assert result.status_code == 200
    assert result.final_url == "https://example.com/final"

    assert len(result.redirect_chain) == 1
    assert result.redirect_chain[0].status_code == 301
    assert result.redirect_chain[0].url == "https://example.com/start"
    assert result.redirect_chain[0].location == "/final"


def test_identifies_non_html_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            headers={
                "Content-Type": "application/pdf",
                "Content-Length": "1000",
            },
            content=b"not-a-real-pdf",
            request=request,
        )

    transport = httpx.MockTransport(handler)

    with PageFetcher(transport=transport) as fetcher:
        result = fetcher.fetch("https://example.com/document.pdf")

    assert result.fetch_succeeded is True
    assert result.status_code == 200
    assert result.content_type == "application/pdf"
    assert result.is_html is False
    assert result.html is None
    assert result.declared_content_length_bytes == 1000


def test_stops_when_html_body_is_too_large() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            headers={"Content-Type": "text/html"},
            content=b"x" * 101,
            request=request,
        )

    transport = httpx.MockTransport(handler)

    with PageFetcher(
        transport=transport,
        max_body_size_bytes=100,
    ) as fetcher:
        result = fetcher.fetch("https://example.com")

    assert result.fetch_succeeded is False
    assert result.body_truncated is True
    assert result.body_size_bytes == 100
    assert result.html is None
    assert result.error_type == "body_too_large"


def test_converts_timeout_to_fetch_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(
            "The server took too long to respond.",
            request=request,
        )

    transport = httpx.MockTransport(handler)

    with PageFetcher(transport=transport) as fetcher:
        result = fetcher.fetch("https://example.com")

    assert result.fetch_succeeded is False
    assert result.status_code is None
    assert result.error_type == "timeout"
    assert "too long" in result.error_message.lower()
