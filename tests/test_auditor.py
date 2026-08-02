from site_auditor.auditor import PageAuditor
from site_auditor.models import FetchResult
from site_auditor.parser import PageParser


def audit_html(
    html: str,
    *,
    url: str = "https://example.com/page",
    status_code: int = 200,
):
    fetch_result = FetchResult(
        requested_url=url,
        final_url=url,
        fetch_succeeded=True,
        status_code=status_code,
        reason_phrase="OK",
        content_type="text/html",
        encoding="utf-8",
        is_html=True,
        html=html,
    )

    page = PageParser.parse(fetch_result)
    issues = PageAuditor.audit(page, fetch_result)

    return issues


def issue_ids(issues) -> set[str]:
    return {issue.rule_id for issue in issues}


def test_reports_missing_title() -> None:
    issues = audit_html(
        """
        <html lang="en">
        <head>
            <meta name="viewport" content="width=device-width">
            <meta name="description"
                  content="This is a sufficiently descriptive page summary
                           for the test document.">
            <link rel="canonical" href="/page">
        </head>
        <body>
            <h1>Test page</h1>
        </body>
        </html>
        """
    )

    assert "seo.title_missing" in issue_ids(issues)


def test_reports_missing_meta_description() -> None:
    issues = audit_html(
        """
        <html lang="en">
        <head>
            <title>A sufficiently descriptive page title</title>
            <meta name="viewport" content="width=device-width">
            <link rel="canonical" href="/page">
        </head>
        <body>
            <h1>Test page</h1>
        </body>
        </html>
        """
    )

    assert "seo.meta_description_missing" in issue_ids(issues)


def test_reports_missing_h1() -> None:
    issues = audit_html(
        """
        <html lang="en">
        <head>
            <title>A sufficiently descriptive page title</title>
            <meta name="viewport" content="width=device-width">
        </head>
        <body>
            <h2>Secondary heading</h2>
        </body>
        </html>
        """
    )

    assert "content.h1_missing" in issue_ids(issues)


def test_reports_multiple_h1_elements() -> None:
    issues = audit_html(
        """
        <html lang="en">
        <head>
            <title>A sufficiently descriptive page title</title>
            <meta name="viewport" content="width=device-width">
        </head>
        <body>
            <h1>First primary heading</h1>
            <h1>Second primary heading</h1>
        </body>
        </html>
        """
    )

    assert "content.multiple_h1" in issue_ids(issues)


def test_reports_skipped_heading_level() -> None:
    issues = audit_html(
        """
        <html lang="en">
        <head>
            <title>A sufficiently descriptive page title</title>
            <meta name="viewport" content="width=device-width">
        </head>
        <body>
            <h1>Primary heading</h1>
            <h3>Skipped secondary heading</h3>
        </body>
        </html>
        """
    )

    matching_issues = [
        issue for issue in issues if issue.rule_id == "accessibility.heading_level_skipped"
    ]

    assert len(matching_issues) == 1
    assert matching_issues[0].location == "heading[2]"


def test_reports_missing_image_alt_attribute() -> None:
    issues = audit_html(
        """
        <html lang="en">
        <head>
            <title>A sufficiently descriptive page title</title>
            <meta name="viewport" content="width=device-width">
        </head>
        <body>
            <h1>Primary heading</h1>
            <img src="/product.png">
        </body>
        </html>
        """
    )

    matching_issues = [
        issue for issue in issues if issue.rule_id == "accessibility.image_alt_missing"
    ]

    assert len(matching_issues) == 1
    assert matching_issues[0].location == "img[1]"
    assert matching_issues[0].evidence == ("https://example.com/product.png")


def test_does_not_report_empty_decorative_alt() -> None:
    issues = audit_html(
        """
        <html lang="en">
        <head>
            <title>A sufficiently descriptive page title</title>
            <meta name="viewport" content="width=device-width">
        </head>
        <body>
            <h1>Primary heading</h1>
            <img src="/decoration.png" alt="">
        </body>
        </html>
        """
    )

    assert "accessibility.image_alt_missing" not in issue_ids(issues)


def test_reports_noindex_as_information() -> None:
    issues = audit_html(
        """
        <html lang="en">
        <head>
            <title>A sufficiently descriptive page title</title>
            <meta name="robots" content="noindex, follow">
            <meta name="viewport" content="width=device-width">
        </head>
        <body>
            <h1>Primary heading</h1>
        </body>
        </html>
        """
    )

    assert "seo.robots_noindex" in issue_ids(issues)


def test_reports_http_error_status() -> None:
    issues = audit_html(
        """
        <html lang="en">
        <head>
            <title>Page not found on the example website</title>
            <meta name="viewport" content="width=device-width">
        </head>
        <body>
            <h1>Page not found</h1>
        </body>
        </html>
        """,
        status_code=404,
    )

    assert "technical.http_error_status" in issue_ids(issues)


def test_reports_insecure_http() -> None:
    issues = audit_html(
        """
        <html lang="en">
        <head>
            <title>A sufficiently descriptive page title</title>
            <meta name="viewport" content="width=device-width">
        </head>
        <body>
            <h1>Primary heading</h1>
        </body>
        </html>
        """,
        url="http://example.com/page",
    )

    assert "technical.insecure_http" in issue_ids(issues)
