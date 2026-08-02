from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable

from pydantic import BaseModel, Field

from site_auditor.models import (
    AuditIssue,
    BatchScanResult,
    IssueCategory,
    IssueSeverity,
    PageScanResult,
)

SEVERITY_PENALTIES: dict[IssueSeverity, float] = {
    IssueSeverity.HIGH: 20.0,
    IssueSeverity.MEDIUM: 8.0,
    IssueSeverity.LOW: 3.0,
    IssueSeverity.INFO: 0.0,
}

CATEGORY_WEIGHTS: dict[IssueCategory, float] = {
    IssueCategory.TECHNICAL: 0.30,
    IssueCategory.SEO: 0.25,
    IssueCategory.ACCESSIBILITY: 0.25,
    IssueCategory.CONTENT: 0.20,
}

# Repeated instances of the same rule on one page matter, but they should not
# let a single repeated issue dominate the entire website score.
REPEAT_PENALTY_INCREMENT = 0.25
MAX_REPEAT_MULTIPLIER = 2.0


class CategoryScore(BaseModel):
    """Quality score and supporting metrics for one audit category."""

    category: IssueCategory
    score: float | None = Field(default=None, ge=0.0, le=100.0)
    label: str
    weight: float = Field(ge=0.0, le=1.0)
    assessed_pages: int = Field(ge=0)
    issue_count: int = Field(ge=0)
    high_count: int = Field(ge=0)
    medium_count: int = Field(ge=0)
    low_count: int = Field(ge=0)
    info_count: int = Field(ge=0)
    average_penalty: float = Field(ge=0.0)


class ScoreSummary(BaseModel):
    """Overall quality score and category-level score breakdown."""

    overall_score: float | None = Field(default=None, ge=0.0, le=100.0)
    overall_label: str
    scanned_pages: int = Field(ge=0)
    parsed_html_pages: int = Field(ge=0)
    category_scores: list[CategoryScore]
    methodology_version: str = "1.0"


def score_label(score: float | None) -> str:
    """Return a human-readable label for a numeric score."""

    if score is None:
        return "Not assessed"

    if score >= 90:
        return "Excellent"

    if score >= 75:
        return "Good"

    if score >= 60:
        return "Needs work"

    return "Poor"


def calculate_page_score(page_result: PageScanResult) -> ScoreSummary:
    """Calculate scores for one page scan result."""

    return calculate_scores([page_result])


def calculate_batch_score(batch_result: BatchScanResult) -> ScoreSummary:
    """Calculate scores for all pages in a batch or crawl result."""

    return calculate_scores(batch_result.pages)


def calculate_scores(
    page_results: Iterable[PageScanResult],
) -> ScoreSummary:
    """
    Calculate category and overall scores.

    Each eligible page starts at 100 in each category. Issues subtract points
    according to severity. Repeated instances of the same rule on the same page
    receive a capped multiplier. Category scores are averages across pages on
    which that category could actually be assessed.
    """

    pages = list(page_results)
    parsed_html_pages = sum(page.page_data is not None for page in pages)

    category_scores: list[CategoryScore] = []

    for category in IssueCategory:
        eligible_pages = [page for page in pages if _category_is_assessable(page, category)]

        category_issues = [
            issue for page in eligible_pages for issue in page.issues if issue.category == category
        ]

        severity_counts = Counter(issue.severity for issue in category_issues)

        page_scores = [_score_page_category(page.issues, category) for page in eligible_pages]

        if page_scores:
            category_score = round(
                sum(page_scores) / len(page_scores),
                1,
            )
            average_penalty = round(
                100.0 - category_score,
                1,
            )
        else:
            category_score = None
            average_penalty = 0.0

        category_scores.append(
            CategoryScore(
                category=category,
                score=category_score,
                label=score_label(category_score),
                weight=CATEGORY_WEIGHTS[category],
                assessed_pages=len(eligible_pages),
                issue_count=len(category_issues),
                high_count=severity_counts[IssueSeverity.HIGH],
                medium_count=severity_counts[IssueSeverity.MEDIUM],
                low_count=severity_counts[IssueSeverity.LOW],
                info_count=severity_counts[IssueSeverity.INFO],
                average_penalty=average_penalty,
            )
        )

    weighted_categories = [
        category_score for category_score in category_scores if category_score.score is not None
    ]

    total_available_weight = sum(category_score.weight for category_score in weighted_categories)

    if total_available_weight > 0:
        overall_score = round(
            sum(
                category_score.score * category_score.weight
                for category_score in weighted_categories
                if category_score.score is not None
            )
            / total_available_weight,
            1,
        )
    else:
        overall_score = None

    return ScoreSummary(
        overall_score=overall_score,
        overall_label=score_label(overall_score),
        scanned_pages=len(pages),
        parsed_html_pages=parsed_html_pages,
        category_scores=category_scores,
    )


def _category_is_assessable(
    page_result: PageScanResult,
    category: IssueCategory,
) -> bool:
    """Return whether a category was meaningfully assessed for a page."""

    if category == IssueCategory.TECHNICAL:
        return True

    return page_result.page_data is not None


def _score_page_category(
    issues: list[AuditIssue],
    category: IssueCategory,
) -> float:
    """Calculate one page's score for one category."""

    matching_issues = [issue for issue in issues if issue.category == category]

    grouped_issues: dict[str, list[AuditIssue]] = defaultdict(list)

    for issue in matching_issues:
        grouped_issues[issue.rule_id].append(issue)

    total_penalty = 0.0

    for rule_issues in grouped_issues.values():
        base_penalty = max(SEVERITY_PENALTIES[issue.severity] for issue in rule_issues)

        occurrence_count = len(rule_issues)
        repeat_multiplier = min(
            1.0 + (occurrence_count - 1) * REPEAT_PENALTY_INCREMENT,
            MAX_REPEAT_MULTIPLIER,
        )

        total_penalty += base_penalty * repeat_multiplier

    return round(
        max(0.0, 100.0 - total_penalty),
        1,
    )
