from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from urllib.parse import urlparse

from site_auditor.models import (
    AuditIssue,
    FetchResult,
    IssueCategory,
    IssueSeverity,
    PageData,
)

AuditRule = Callable[[PageData, FetchResult], list[AuditIssue]]


SEVERITY_ORDER = {
    IssueSeverity.HIGH: 0,
    IssueSeverity.MEDIUM: 1,
    IssueSeverity.LOW: 2,
    IssueSeverity.INFO: 3,
}


class PageAuditor:
    """Run website quality rules against one parsed page."""

    RULES: tuple[AuditRule, ...] = ()

    @classmethod
    def audit(
        cls,
        page: PageData,
        fetch_result: FetchResult,
    ) -> list[AuditIssue]:
        """Run every registered rule and return sorted issues."""

        rules: tuple[AuditRule, ...] = (
            cls._check_http_status,
            cls._check_https,
            cls._check_title,
            cls._check_meta_description,
            cls._check_canonical_url,
            cls._check_language,
            cls._check_viewport,
            cls._check_robots_directives,
            cls._check_h1_elements,
            cls._check_heading_structure,
            cls._check_empty_headings,
            cls._check_duplicate_headings,
            cls._check_image_alt_attributes,
            cls._check_thin_content,
        )

        issues: list[AuditIssue] = []

        for rule in rules:
            issues.extend(rule(page, fetch_result))

        return sorted(
            issues,
            key=lambda issue: (
                SEVERITY_ORDER[issue.severity],
                issue.category.value,
                issue.rule_id,
                issue.location,
            ),
        )

    @classmethod
    def _create_issue(
        cls,
        *,
        page: PageData,
        rule_id: str,
        category: IssueCategory,
        severity: IssueSeverity,
        title: str,
        message: str,
        location: str,
        evidence: str | None = None,
        recommendation: str | None = None,
    ) -> AuditIssue:
        return AuditIssue(
            rule_id=rule_id,
            category=category,
            severity=severity,
            title=title,
            message=message,
            url=page.url,
            location=location,
            evidence=evidence,
            recommendation=recommendation,
        )

    @classmethod
    def _check_http_status(
        cls,
        page: PageData,
        fetch_result: FetchResult,
    ) -> list[AuditIssue]:
        status_code = fetch_result.status_code

        if status_code is None or status_code < 400:
            return []

        if status_code >= 500:
            message = (
                f"The server returned HTTP {status_code}. The page could not be served correctly."
            )
        else:
            message = (
                f"The page returned HTTP {status_code}, indicating "
                "a client-side or missing-resource error."
            )

        return [
            cls._create_issue(
                page=page,
                rule_id="technical.http_error_status",
                category=IssueCategory.TECHNICAL,
                severity=IssueSeverity.HIGH,
                title="HTTP error status",
                message=message,
                location="HTTP response",
                evidence=str(status_code),
                recommendation=(
                    "Ensure the URL returns a successful 2xx response "
                    "or redirects to a valid replacement page."
                ),
            )
        ]

    @classmethod
    def _check_https(
        cls,
        page: PageData,
        fetch_result: FetchResult,
    ) -> list[AuditIssue]:
        del fetch_result

        if urlparse(page.url).scheme.lower() == "https":
            return []

        return [
            cls._create_issue(
                page=page,
                rule_id="technical.insecure_http",
                category=IssueCategory.TECHNICAL,
                severity=IssueSeverity.MEDIUM,
                title="Page does not use HTTPS",
                message="The page is served over an unencrypted HTTP connection.",
                location="Document URL",
                evidence=page.url,
                recommendation=(
                    "Serve the page over HTTPS and redirect HTTP requests to the HTTPS version."
                ),
            )
        ]

    @classmethod
    def _check_title(
        cls,
        page: PageData,
        fetch_result: FetchResult,
    ) -> list[AuditIssue]:
        del fetch_result

        if not page.title or not page.title.strip():
            return [
                cls._create_issue(
                    page=page,
                    rule_id="seo.title_missing",
                    category=IssueCategory.SEO,
                    severity=IssueSeverity.HIGH,
                    title="Missing page title",
                    message="The document does not contain a usable title.",
                    location="<head> > <title>",
                    recommendation=(
                        "Add a unique and descriptive <title> element to the document head."
                    ),
                )
            ]

        title_length = len(page.title)

        if title_length < 15:
            return [
                cls._create_issue(
                    page=page,
                    rule_id="seo.title_too_short",
                    category=IssueCategory.SEO,
                    severity=IssueSeverity.LOW,
                    title="Page title is very short",
                    message=("The title may not provide enough context about the page."),
                    location="<head> > <title>",
                    evidence=f"{title_length} characters: {page.title}",
                    recommendation=(
                        "Use a more descriptive title that accurately summarizes the page."
                    ),
                )
            ]

        if title_length > 60:
            return [
                cls._create_issue(
                    page=page,
                    rule_id="seo.title_too_long",
                    category=IssueCategory.SEO,
                    severity=IssueSeverity.MEDIUM,
                    title="Page title may be too long",
                    message=("Long titles may be truncated in search-result interfaces."),
                    location="<head> > <title>",
                    evidence=f"{title_length} characters: {page.title}",
                    recommendation=(
                        "Shorten the title while retaining its most important descriptive terms."
                    ),
                )
            ]

        return []

    @classmethod
    def _check_meta_description(
        cls,
        page: PageData,
        fetch_result: FetchResult,
    ) -> list[AuditIssue]:
        del fetch_result

        description = page.meta_description

        if not description or not description.strip():
            return [
                cls._create_issue(
                    page=page,
                    rule_id="seo.meta_description_missing",
                    category=IssueCategory.SEO,
                    severity=IssueSeverity.MEDIUM,
                    title="Missing meta description",
                    message=("The page does not provide a meta description."),
                    location='<meta name="description">',
                    recommendation=(
                        "Add a concise description that summarizes the page's purpose and content."
                    ),
                )
            ]

        description_length = len(description)

        if description_length < 50:
            return [
                cls._create_issue(
                    page=page,
                    rule_id="seo.meta_description_short",
                    category=IssueCategory.SEO,
                    severity=IssueSeverity.LOW,
                    title="Meta description is short",
                    message=(
                        "The description may not give users enough information about the page."
                    ),
                    location='<meta name="description">',
                    evidence=f"{description_length} characters",
                    recommendation=(
                        "Expand the description with a concise and accurate summary of the page."
                    ),
                )
            ]

        if description_length > 160:
            return [
                cls._create_issue(
                    page=page,
                    rule_id="seo.meta_description_long",
                    category=IssueCategory.SEO,
                    severity=IssueSeverity.LOW,
                    title="Meta description may be too long",
                    message=(
                        "Long descriptions may be shortened when displayed by search interfaces."
                    ),
                    location='<meta name="description">',
                    evidence=f"{description_length} characters",
                    recommendation=(
                        "Reduce the description while retaining its most important information."
                    ),
                )
            ]

        return []

    @classmethod
    def _check_canonical_url(
        cls,
        page: PageData,
        fetch_result: FetchResult,
    ) -> list[AuditIssue]:
        del fetch_result

        if page.canonical_url:
            return []

        return [
            cls._create_issue(
                page=page,
                rule_id="seo.canonical_missing",
                category=IssueCategory.SEO,
                severity=IssueSeverity.LOW,
                title="Missing canonical URL",
                message=("The page does not declare its preferred canonical URL."),
                location='<link rel="canonical">',
                recommendation=(
                    "Add a canonical link when duplicate or alternative "
                    "versions of this page may be accessible."
                ),
            )
        ]

    @classmethod
    def _check_language(
        cls,
        page: PageData,
        fetch_result: FetchResult,
    ) -> list[AuditIssue]:
        del fetch_result

        if page.language:
            return []

        return [
            cls._create_issue(
                page=page,
                rule_id="accessibility.document_language_missing",
                category=IssueCategory.ACCESSIBILITY,
                severity=IssueSeverity.MEDIUM,
                title="Document language is missing",
                message=("The root HTML element does not declare the document language."),
                location="<html>",
                recommendation=('Add an appropriate lang attribute, such as <html lang="en">.'),
            )
        ]

    @classmethod
    def _check_viewport(
        cls,
        page: PageData,
        fetch_result: FetchResult,
    ) -> list[AuditIssue]:
        del fetch_result

        if page.has_viewport_meta:
            return []

        return [
            cls._create_issue(
                page=page,
                rule_id="technical.viewport_missing",
                category=IssueCategory.TECHNICAL,
                severity=IssueSeverity.MEDIUM,
                title="Viewport meta tag is missing",
                message=("The page does not provide mobile viewport instructions."),
                location='<meta name="viewport">',
                recommendation=(
                    'Add <meta name="viewport" content="width=device-width, initial-scale=1">.'
                ),
            )
        ]

    @classmethod
    def _check_robots_directives(
        cls,
        page: PageData,
        fetch_result: FetchResult,
    ) -> list[AuditIssue]:
        del fetch_result

        if "noindex" not in page.robots_directives:
            return []

        return [
            cls._create_issue(
                page=page,
                rule_id="seo.robots_noindex",
                category=IssueCategory.SEO,
                severity=IssueSeverity.INFO,
                title="Page contains a noindex directive",
                message=("Search engines are being instructed not to index this page."),
                location='<meta name="robots">',
                evidence=", ".join(page.robots_directives),
                recommendation=(
                    "Confirm that excluding this page from search indexes is intentional."
                ),
            )
        ]

    @classmethod
    def _check_h1_elements(
        cls,
        page: PageData,
        fetch_result: FetchResult,
    ) -> list[AuditIssue]:
        del fetch_result

        h1_headings = [heading for heading in page.headings if heading.level == 1]

        if not h1_headings:
            return [
                cls._create_issue(
                    page=page,
                    rule_id="content.h1_missing",
                    category=IssueCategory.CONTENT,
                    severity=IssueSeverity.HIGH,
                    title="H1 heading is missing",
                    message=("The page does not contain a primary H1 heading."),
                    location="<body>",
                    recommendation=(
                        "Add a clear H1 heading describing the page's primary subject."
                    ),
                )
            ]

        if len(h1_headings) > 1:
            evidence = " | ".join(heading.text or "[empty]" for heading in h1_headings[:5])

            return [
                cls._create_issue(
                    page=page,
                    rule_id="content.multiple_h1",
                    category=IssueCategory.CONTENT,
                    severity=IssueSeverity.MEDIUM,
                    title="Multiple H1 headings found",
                    message=(f"The page contains {len(h1_headings)} H1 headings."),
                    location="<body> headings",
                    evidence=evidence,
                    recommendation=(
                        "Review whether one clear primary H1 would provide "
                        "a better document structure."
                    ),
                )
            ]

        return []

    @classmethod
    def _check_heading_structure(
        cls,
        page: PageData,
        fetch_result: FetchResult,
    ) -> list[AuditIssue]:
        del fetch_result

        issues: list[AuditIssue] = []
        previous_heading = None

        for heading in page.headings:
            if previous_heading is not None:
                level_difference = heading.level - previous_heading.level

                if level_difference > 1:
                    issues.append(
                        cls._create_issue(
                            page=page,
                            rule_id="accessibility.heading_level_skipped",
                            category=IssueCategory.ACCESSIBILITY,
                            severity=IssueSeverity.MEDIUM,
                            title="Heading level was skipped",
                            message=(
                                f"The heading structure changes from "
                                f"H{previous_heading.level} to "
                                f"H{heading.level}."
                            ),
                            location=f"heading[{heading.index}]",
                            evidence=heading.text or "[empty heading]",
                            recommendation=(
                                "Use sequential heading levels to represent the document hierarchy."
                            ),
                        )
                    )

            previous_heading = heading

        return issues

    @classmethod
    def _check_empty_headings(
        cls,
        page: PageData,
        fetch_result: FetchResult,
    ) -> list[AuditIssue]:
        del fetch_result

        return [
            cls._create_issue(
                page=page,
                rule_id="accessibility.empty_heading",
                category=IssueCategory.ACCESSIBILITY,
                severity=IssueSeverity.MEDIUM,
                title="Empty heading found",
                message=(f"An H{heading.level} element does not contain text."),
                location=f"heading[{heading.index}]",
                recommendation=("Remove the empty heading or provide meaningful heading text."),
            )
            for heading in page.headings
            if not heading.text.strip()
        ]

    @classmethod
    def _check_duplicate_headings(
        cls,
        page: PageData,
        fetch_result: FetchResult,
    ) -> list[AuditIssue]:
        del fetch_result

        normalized_headings = [
            heading.text.casefold().strip() for heading in page.headings if heading.text.strip()
        ]

        heading_counts = Counter(normalized_headings)

        duplicate_texts = sorted(text for text, count in heading_counts.items() if count > 1)

        if not duplicate_texts:
            return []

        evidence = " | ".join(duplicate_texts[:10])

        return [
            cls._create_issue(
                page=page,
                rule_id="content.duplicate_heading_text",
                category=IssueCategory.CONTENT,
                severity=IssueSeverity.LOW,
                title="Duplicate heading text found",
                message=("One or more heading texts are repeated on the page."),
                location="<body> headings",
                evidence=evidence,
                recommendation=("Use headings that clearly distinguish each section's purpose."),
            )
        ]

    @classmethod
    def _check_image_alt_attributes(
        cls,
        page: PageData,
        fetch_result: FetchResult,
    ) -> list[AuditIssue]:
        del fetch_result

        issues: list[AuditIssue] = []

        for image in page.images:
            if image.has_alt_attribute:
                continue

            evidence = image.resolved_url or image.src or "[source missing]"

            issues.append(
                cls._create_issue(
                    page=page,
                    rule_id="accessibility.image_alt_missing",
                    category=IssueCategory.ACCESSIBILITY,
                    severity=IssueSeverity.MEDIUM,
                    title="Image alt attribute is missing",
                    message=("An image does not have an alt attribute."),
                    location=f"img[{image.index}]",
                    evidence=evidence,
                    recommendation=(
                        "Add meaningful alt text for informative images. "
                        'Use alt="" for images that are purely decorative.'
                    ),
                )
            )

        return issues

    @classmethod
    def _check_thin_content(
        cls,
        page: PageData,
        fetch_result: FetchResult,
    ) -> list[AuditIssue]:
        del fetch_result

        if page.word_count >= 50:
            return []

        return [
            cls._create_issue(
                page=page,
                rule_id="content.low_word_count",
                category=IssueCategory.CONTENT,
                severity=IssueSeverity.INFO,
                title="Low visible word count",
                message=("The page contains relatively little visible text."),
                location="<body>",
                evidence=f"{page.word_count} visible words",
                recommendation=(
                    "Confirm that the amount of content is appropriate for the page's purpose."
                ),
            )
        ]
