from __future__ import annotations

from collections.abc import Iterable, Iterator
from time import sleep
from typing import Protocol

from site_auditor.auditor import PageAuditor
from site_auditor.models import (
    AuditIssue,
    FetchResult,
    IssueCategory,
    IssueSeverity,
    PageScanResult,
)
from site_auditor.parser import PageParser

SENSITIVE_RESPONSE_HEADERS = {
    "set-cookie",
    "authorization",
    "proxy-authorization",
}


class FetcherProtocol(Protocol):
    """Minimum interface required by the batch scanner."""

    def fetch(self, url: str) -> FetchResult:
        """Fetch one URL."""


class BatchScanner:
    """Fetch, parse, and audit one or more supplied URLs."""

    def __init__(self, fetcher: FetcherProtocol) -> None:
        self.fetcher = fetcher

    def scan_urls(
        self,
        urls: Iterable[str],
        *,
        request_delay_seconds: float = 0.0,
    ) -> Iterator[PageScanResult]:
        """
        Scan URLs sequentially.

        Results are yielded one at a time so the interface can update its
        progress bar after every page.
        """

        if request_delay_seconds < 0:
            raise ValueError("request_delay_seconds cannot be negative.")

        url_list = list(urls)

        for index, url in enumerate(url_list):
            yield self.scan_page(url)

            is_last_url = index == len(url_list) - 1

            if not is_last_url and request_delay_seconds > 0:
                sleep(request_delay_seconds)

    def scan_page(self, url: str) -> PageScanResult:
        """Fetch, parse, and audit one page without propagating page errors."""

        raw_fetch_result = self.fetcher.fetch(url)

        stored_fetch_result = self._prepare_fetch_result_for_storage(raw_fetch_result)

        if not raw_fetch_result.fetch_succeeded:
            return PageScanResult(
                fetch_result=stored_fetch_result,
                issues=[self._create_fetch_failure_issue(raw_fetch_result)],
            )

        if not raw_fetch_result.is_html:
            return PageScanResult(
                fetch_result=stored_fetch_result,
                issues=[self._create_non_html_issue(raw_fetch_result)],
            )

        if raw_fetch_result.html is None:
            message = (
                "The response was identified as HTML, but no HTML body "
                "was available for processing."
            )

            return PageScanResult(
                fetch_result=stored_fetch_result,
                issues=[
                    self._create_processing_failure_issue(
                        raw_fetch_result,
                        message=message,
                    )
                ],
                processing_error_type="missing_html_body",
                processing_error_message=message,
            )

        try:
            page_data = PageParser.parse(raw_fetch_result)

            issues = PageAuditor.audit(
                page_data,
                raw_fetch_result,
            )

            return PageScanResult(
                fetch_result=stored_fetch_result,
                page_data=page_data,
                issues=issues,
            )

        except Exception as error:
            # One malformed or unusual page must not stop the entire batch.
            message = str(error).strip() or error.__class__.__name__

            return PageScanResult(
                fetch_result=stored_fetch_result,
                issues=[
                    self._create_processing_failure_issue(
                        raw_fetch_result,
                        message=message,
                    )
                ],
                processing_error_type=error.__class__.__name__,
                processing_error_message=message,
            )

    @staticmethod
    def _prepare_fetch_result_for_storage(
        fetch_result: FetchResult,
    ) -> FetchResult:
        """
        Remove raw HTML and redact sensitive headers before session storage.

        Parsed page data is retained separately, so keeping the complete HTML
        response for every scanned page would waste memory.
        """

        safe_headers = {
            key: ("[REDACTED]" if key.lower() in SENSITIVE_RESPONSE_HEADERS else value)
            for key, value in fetch_result.headers.items()
        }

        return fetch_result.model_copy(
            update={
                "html": None,
                "headers": safe_headers,
            }
        )

    @staticmethod
    def _create_fetch_failure_issue(
        fetch_result: FetchResult,
    ) -> AuditIssue:
        page_url = fetch_result.final_url or fetch_result.requested_url

        evidence_parts = []

        if fetch_result.error_type:
            evidence_parts.append(fetch_result.error_type)

        if fetch_result.error_message:
            evidence_parts.append(fetch_result.error_message)

        return AuditIssue(
            rule_id="technical.fetch_failed",
            category=IssueCategory.TECHNICAL,
            severity=IssueSeverity.HIGH,
            title="Page could not be fetched",
            message=(
                "The scanner could not retrieve this URL, so page quality "
                "checks could not be completed."
            ),
            url=page_url,
            location="HTTP request",
            evidence=": ".join(evidence_parts) or None,
            recommendation=(
                "Verify that the URL is reachable and that the server is "
                "not blocking or timing out the scanner."
            ),
        )

    @staticmethod
    def _create_non_html_issue(
        fetch_result: FetchResult,
    ) -> AuditIssue:
        page_url = fetch_result.final_url or fetch_result.requested_url

        return AuditIssue(
            rule_id="technical.non_html_resource",
            category=IssueCategory.TECHNICAL,
            severity=IssueSeverity.INFO,
            title="URL is not an HTML page",
            message=(
                "The URL returned a non-HTML resource and was not processed "
                "by the HTML audit rules."
            ),
            url=page_url,
            location="HTTP response",
            evidence=fetch_result.content_type or "Unknown content type",
            recommendation=("Confirm that this resource was intentionally included in the scan."),
        )

    @staticmethod
    def _create_processing_failure_issue(
        fetch_result: FetchResult,
        *,
        message: str,
    ) -> AuditIssue:
        page_url = fetch_result.final_url or fetch_result.requested_url

        return AuditIssue(
            rule_id="technical.page_processing_failed",
            category=IssueCategory.TECHNICAL,
            severity=IssueSeverity.HIGH,
            title="Page processing failed",
            message=("The page was fetched, but its HTML could not be fully parsed or audited."),
            url=page_url,
            location="HTML processing",
            evidence=message,
            recommendation=(
                "Inspect the HTML response and scanner logs to determine why processing failed."
            ),
        )
