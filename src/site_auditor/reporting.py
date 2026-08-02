from __future__ import annotations

import json
from io import StringIO

import pandas as pd

from site_auditor.models import BatchScanResult
from site_auditor.scoring import (
    ScoreSummary,
    calculate_page_score,
)


def create_issues_csv(
    batch_result: BatchScanResult,
) -> str:
    """Create a CSV containing every issue from the scan."""

    rows = [
        {
            "requested_url": page.fetch_result.requested_url,
            "final_url": page.fetch_result.final_url or "",
            "severity": issue.severity.value,
            "category": issue.category.value,
            "rule_id": issue.rule_id,
            "title": issue.title,
            "location": issue.location,
            "evidence": issue.evidence or "",
            "message": issue.message,
            "recommendation": issue.recommendation or "",
        }
        for page in batch_result.pages
        for issue in page.issues
    ]

    columns = [
        "requested_url",
        "final_url",
        "severity",
        "category",
        "rule_id",
        "title",
        "location",
        "evidence",
        "message",
        "recommendation",
    ]

    return _rows_to_csv(rows, columns)


def create_pages_csv(
    batch_result: BatchScanResult,
) -> str:
    """Create a CSV containing one summary row per scanned page."""

    rows: list[dict[str, object]] = []

    for page in batch_result.pages:
        fetch = page.fetch_result
        parsed = page.page_data
        page_score = calculate_page_score(page)

        category_scores = {
            category_score.category.value: category_score.score
            for category_score in page_score.category_scores
        }

        rows.append(
            {
                "requested_url": fetch.requested_url,
                "final_url": fetch.final_url or "",
                "fetch_succeeded": fetch.fetch_succeeded,
                "status_code": fetch.status_code,
                "response_time_ms": fetch.response_time_ms,
                "content_type": fetch.content_type or "",
                "title": parsed.title if parsed and parsed.title else "",
                "word_count": parsed.word_count if parsed else None,
                "issue_count": len(page.issues),
                "overall_score": page_score.overall_score,
                "technical_score": category_scores.get("Technical"),
                "seo_score": category_scores.get("SEO"),
                "accessibility_score": category_scores.get("Accessibility"),
                "content_score": category_scores.get("Content"),
                "processing_error_type": page.processing_error_type or "",
                "processing_error_message": page.processing_error_message or "",
            }
        )

    columns = [
        "requested_url",
        "final_url",
        "fetch_succeeded",
        "status_code",
        "response_time_ms",
        "content_type",
        "title",
        "word_count",
        "issue_count",
        "overall_score",
        "technical_score",
        "seo_score",
        "accessibility_score",
        "content_score",
        "processing_error_type",
        "processing_error_message",
    ]

    return _rows_to_csv(rows, columns)


def create_scan_json(
    batch_result: BatchScanResult,
    score_summary: ScoreSummary,
) -> str:
    """Create a complete JSON report containing scan data and scores."""

    payload = {
        "report_version": "1.0",
        "scoring": score_summary.model_dump(mode="json"),
        "scan": batch_result.model_dump(mode="json"),
    }

    return json.dumps(
        payload,
        indent=2,
        ensure_ascii=False,
    )


def _rows_to_csv(
    rows: list[dict[str, object]],
    columns: list[str],
) -> str:
    dataframe = pd.DataFrame(rows, columns=columns)
    output = StringIO()
    dataframe.to_csv(output, index=False)
    return output.getvalue()
