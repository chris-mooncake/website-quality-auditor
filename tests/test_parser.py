import pytest

from site_auditor.models import FetchResult
from site_auditor.parser import PageParser

SAMPLE_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta
        name="description"
        content="A test page used by the website quality auditor."
    >
    <meta name="robots" content="index, follow">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="canonical" href="/canonical-page">
    <title>Example Test Page</title>
</head>
<body>
    <header>
        <h1>Main heading</h1>
    </header>

    <main>
        <h2>First section</h2>

        <p>This page contains visible test content.</p>

        <a href="/about">About us</a>
        <a href="https://external.example.org/page">External page</a>
        <a href="mailto:test@example.com">Email us</a>
        <a href="/private" rel="nofollow">Private page</a>

        <img src="/images/logo.png" alt="Company logo">
        <img src="/images/decorative.png" alt="">
        <img src="/images/product.png">
    </main>

    <script>
        This script content must not count as visible words.
    </script>
</body>
</html>
"""


def create_fetch_result(
    html: str = SAMPLE_HTML,
) -> FetchResult:
    return FetchResult(
        requested_url="https://example.com/start",
        final_url="https://example.com/start",
        fetch_succeeded=True,
        status_code=200,
        content_type="text/html",
        encoding="utf-8",
        is_html=True,
        html=html,
    )


def test_extracts_page_metadata() -> None:
    page = PageParser.parse(create_fetch_result())

    assert page.url == "https://example.com/start"
    assert page.title == "Example Test Page"
    assert page.meta_description == "A test page used by the website quality auditor."
    assert page.canonical_url == "https://example.com/canonical-page"
    assert page.language == "en"
    assert page.robots_directives == ["index", "follow"]
    assert page.has_viewport_meta is True
    assert page.charset == "utf-8"


def test_extracts_headings() -> None:
    page = PageParser.parse(create_fetch_result())

    assert len(page.headings) == 2

    assert page.headings[0].index == 1
    assert page.headings[0].level == 1
    assert page.headings[0].text == "Main heading"

    assert page.headings[1].level == 2
    assert page.headings[1].text == "First section"


def test_resolves_and_classifies_links() -> None:
    page = PageParser.parse(create_fetch_result())

    assert len(page.links) == 4

    internal_link = page.links[0]

    assert internal_link.href == "/about"
    assert internal_link.resolved_url == "https://example.com/about"
    assert internal_link.is_internal is True

    external_link = page.links[1]

    assert external_link.is_internal is False
    assert external_link.resolved_url == "https://external.example.org/page"

    email_link = page.links[2]

    assert email_link.href == "mailto:test@example.com"
    assert email_link.resolved_url is None
    assert email_link.is_internal is False

    nofollow_link = page.links[3]

    assert nofollow_link.is_nofollow is True


def test_distinguishes_missing_and_empty_alt_attributes() -> None:
    page = PageParser.parse(create_fetch_result())

    assert len(page.images) == 3

    normal_image = page.images[0]
    assert normal_image.has_alt_attribute is True
    assert normal_image.alt == "Company logo"

    decorative_image = page.images[1]
    assert decorative_image.has_alt_attribute is True
    assert decorative_image.alt == ""

    missing_alt_image = page.images[2]
    assert missing_alt_image.has_alt_attribute is False
    assert missing_alt_image.alt is None


def test_counts_visible_words() -> None:
    page = PageParser.parse(create_fetch_result())

    assert page.word_count > 0


def test_rejects_unsuccessful_fetch() -> None:
    result = FetchResult(
        requested_url="https://example.com",
        fetch_succeeded=False,
        error_type="timeout",
        error_message="Request timed out.",
    )

    with pytest.raises(
        ValueError,
        match="unsuccessful fetch result",
    ):
        PageParser.parse(result)


def test_rejects_non_html_response() -> None:
    result = FetchResult(
        requested_url="https://example.com/document.pdf",
        final_url="https://example.com/document.pdf",
        fetch_succeeded=True,
        status_code=200,
        content_type="application/pdf",
        is_html=False,
    )

    with pytest.raises(
        ValueError,
        match="non-HTML response",
    ):
        PageParser.parse(result)
