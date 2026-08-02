import json

from site_auditor.models import (
    AuditIssue,
    BatchScanResult,
    FetchResult,
    IssueCategory,
    IssueSeverity,
    PageData,
    PageScanResult,
    ScanMode,
)
from site_auditor.reporting import (
    create_issues_csv,
    create_pages_csv,
    create_scan_json,
)
from site_auditor.scoring import calculate_batch_score


def create_batch() -> BatchScanResult:
    issue = AuditIssue(
        rule_id="seo.title_missing",
        category=IssueCategory.SEO,
        severity=IssueSeverity.HIGH,
        title="Missing title",
        message="The title is missing.",
        url="https://example.com/",
        location="<title>",
        recommendation="Add a title.",
    )

    page = PageScanResult(
        fetch_result=FetchResult(
            requested_url="https://example.com/",
            final_url="https://example.com/",
            fetch_succeeded=True,
            status_code=200,
            content_type="text/html",
            is_html=True,
        ),
        page_data=PageData(
            url="https://example.com/",
            word_count=20,
        ),
        issues=[issue],
    )

    return BatchScanResult(
        mode=ScanMode.SINGLE_PAGE,
        pages=[page],
        total_duration_ms=100,
    )


def test_issues_csv_contains_rule() -> None:
    report = create_issues_csv(create_batch())

    assert "seo.title_missing" in report
    assert "Missing title" in report


def test_pages_csv_contains_score() -> None:
    report = create_pages_csv(create_batch())

    assert "overall_score" in report
    assert "technical_score" in report


def test_json_contains_scan_and_scoring() -> None:
    batch = create_batch()
    score = calculate_batch_score(batch)

    payload = json.loads(create_scan_json(batch, score))

    assert "scan" in payload
    assert "scoring" in payload
    assert payload["report_version"] == "1.0"
