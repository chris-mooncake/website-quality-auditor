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
from site_auditor.scoring import (
    calculate_batch_score,
    calculate_page_score,
)


def create_issue(
    *,
    rule_id: str,
    category: IssueCategory,
    severity: IssueSeverity,
) -> AuditIssue:
    return AuditIssue(
        rule_id=rule_id,
        category=category,
        severity=severity,
        title="Test issue",
        message="Test message",
        url="https://example.com/",
        location="test",
    )


def create_page(
    issues: list[AuditIssue] | None = None,
    *,
    parsed: bool = True,
) -> PageScanResult:
    return PageScanResult(
        fetch_result=FetchResult(
            requested_url="https://example.com/",
            final_url="https://example.com/",
            fetch_succeeded=True,
            status_code=200,
            content_type="text/html",
            is_html=True,
        ),
        page_data=(PageData(url="https://example.com/") if parsed else None),
        issues=issues or [],
    )


def category_score(summary, category: IssueCategory):
    return next(item for item in summary.category_scores if item.category == category)


def test_clean_page_scores_100() -> None:
    summary = calculate_page_score(create_page())

    assert summary.overall_score == 100.0
    assert all(item.score == 100.0 for item in summary.category_scores)


def test_high_issue_subtracts_20_points() -> None:
    page = create_page(
        [
            create_issue(
                rule_id="seo.title_missing",
                category=IssueCategory.SEO,
                severity=IssueSeverity.HIGH,
            )
        ]
    )

    summary = calculate_page_score(page)

    assert (
        category_score(
            summary,
            IssueCategory.SEO,
        ).score
        == 80.0
    )


def test_repeated_rule_penalty_is_capped() -> None:
    issues = [
        create_issue(
            rule_id="accessibility.image_alt_missing",
            category=IssueCategory.ACCESSIBILITY,
            severity=IssueSeverity.MEDIUM,
        )
        for _ in range(20)
    ]

    summary = calculate_page_score(create_page(issues))

    # Medium penalty 8 * capped repeat multiplier 2 = 16.
    assert (
        category_score(
            summary,
            IssueCategory.ACCESSIBILITY,
        ).score
        == 84.0
    )


def test_non_parsed_page_does_not_claim_seo_score() -> None:
    page = create_page(
        [
            create_issue(
                rule_id="technical.fetch_failed",
                category=IssueCategory.TECHNICAL,
                severity=IssueSeverity.HIGH,
            )
        ],
        parsed=False,
    )

    summary = calculate_page_score(page)

    assert (
        category_score(
            summary,
            IssueCategory.TECHNICAL,
        ).score
        == 80.0
    )

    assert (
        category_score(
            summary,
            IssueCategory.SEO,
        ).score
        is None
    )


def test_batch_category_score_is_page_average() -> None:
    clean_page = create_page()
    issue_page = create_page(
        [
            create_issue(
                rule_id="content.h1_missing",
                category=IssueCategory.CONTENT,
                severity=IssueSeverity.HIGH,
            )
        ]
    )

    batch = BatchScanResult(
        mode=ScanMode.MULTIPLE_PAGES,
        pages=[clean_page, issue_page],
        total_duration_ms=100,
    )

    summary = calculate_batch_score(batch)

    assert (
        category_score(
            summary,
            IssueCategory.CONTENT,
        ).score
        == 90.0
    )
