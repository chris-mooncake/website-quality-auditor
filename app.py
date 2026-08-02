from collections import Counter
from time import perf_counter

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from site_auditor.crawler import WebsiteCrawler
from site_auditor.fetcher import PageFetcher
from site_auditor.models import (
    AuditIssue,
    BatchScanResult,
    FetchResult,
    IssueSeverity,
    PageData,
    ScanMode,
    ScanRequest,
)
from site_auditor.reporting import (
    create_issues_csv,
    create_pages_csv,
    create_scan_json,
)
from site_auditor.scanner import SENSITIVE_RESPONSE_HEADERS, BatchScanner
from site_auditor.scoring import (
    ScoreSummary,
    calculate_batch_score,
    calculate_page_score,
)
from site_auditor.url_utils import normalize_url, parse_url_list

st.set_page_config(
    page_title="Website Quality Auditor",
    page_icon="🔎",
    layout="wide",
)


def redact_header_value(header_name: str, header_value: str) -> str:
    """Redact headers that may contain credentials or session tokens."""

    if header_name.lower() in SENSITIVE_RESPONSE_HEADERS:
        return "[REDACTED]"

    return header_value


def format_bytes(size_bytes: int | None) -> str:
    """Convert a byte count into a readable value."""

    if size_bytes is None:
        return "Unknown"

    if size_bytes < 1024:
        return f"{size_bytes:,} B"

    size = size_bytes / 1024

    if size < 1024:
        return f"{size:,.2f} KB"

    size /= 1024

    if size < 1024:
        return f"{size:,.2f} MB"

    size /= 1024

    return f"{size:,.2f} GB"


def format_score(score: float | None) -> str:
    """Format a quality score for display."""

    if score is None:
        return "Not assessed"

    return f"{score:.1f}/100"


def display_score_dashboard(
    score_summary: ScoreSummary,
    *,
    title: str,
) -> None:
    """Display overall and category-level quality scores."""

    st.divider()
    st.subheader(title)

    metric_columns = st.columns(5)

    with metric_columns[0]:
        st.metric(
            "Overall score",
            format_score(score_summary.overall_score),
            help=(
                "Weighted average of the available category scores. "
                "This is a project-specific heuristic, not a compliance certification."
            ),
        )
        st.caption(score_summary.overall_label)

    for column, category_score in zip(
        metric_columns[1:],
        score_summary.category_scores,
        strict=True,
    ):
        with column:
            st.metric(
                category_score.category.value,
                format_score(category_score.score),
                help=(
                    f"Assessed on {category_score.assessed_pages:,} page(s); "
                    f"{category_score.issue_count:,} issue(s)."
                ),
            )
            st.caption(category_score.label)

    score_rows = [
        {
            "Category": category_score.category.value,
            "Score": (
                f"{category_score.score:.1f}"
                if category_score.score is not None
                else "Not assessed"
            ),
            "Weight": f"{category_score.weight * 100:.0f}%",
            "Assessed pages": str(category_score.assessed_pages),
            "Issues": str(category_score.issue_count),
            "High": str(category_score.high_count),
            "Medium": str(category_score.medium_count),
            "Low": str(category_score.low_count),
            "Info": str(category_score.info_count),
            "Average penalty": f"{category_score.average_penalty:.1f}",
        }
        for category_score in score_summary.category_scores
    ]

    with st.expander("Score breakdown and methodology"):
        st.dataframe(
            pd.DataFrame(score_rows).astype("string"),
            hide_index=True,
            width="stretch",
        )

        st.write(
            "Each assessable page begins at 100 points in each category. "
            "High, medium, and low findings subtract 20, 8, and 3 points. "
            "Informational findings do not reduce the score. Repeated instances "
            "of the same rule on one page receive a capped multiplier so one "
            "repeated issue cannot dominate the entire website score."
        )

        st.caption(
            "Category weights: Technical 30%, SEO 25%, Accessibility 25%, "
            "Content 20%. Categories that could not be assessed are excluded "
            "from the overall weighted average."
        )


def display_export_buttons(
    batch_result: BatchScanResult,
    score_summary: ScoreSummary,
) -> None:
    """Display CSV and JSON report download controls."""

    st.divider()
    st.subheader("Export reports")

    issues_csv = create_issues_csv(batch_result)
    pages_csv = create_pages_csv(batch_result)
    scan_json = create_scan_json(
        batch_result,
        score_summary,
    )

    export_columns = st.columns(3)

    with export_columns[0]:
        st.download_button(
            "Download issues CSV",
            data=issues_csv,
            file_name="website-audit-issues.csv",
            mime="text/csv",
            width="stretch",
            key="download_issues_csv",
        )

    with export_columns[1]:
        st.download_button(
            "Download pages CSV",
            data=pages_csv,
            file_name="website-audit-pages.csv",
            mime="text/csv",
            width="stretch",
            key="download_pages_csv",
        )

    with export_columns[2]:
        st.download_button(
            "Download full JSON",
            data=scan_json,
            file_name="website-audit-report.json",
            mime="application/json",
            width="stretch",
            key="download_scan_json",
        )


def display_scan_configuration(scan_request: ScanRequest) -> None:
    """Display the validated scan configuration."""

    configuration = {
        "Setting": [
            "Scan mode",
            "Number of starting URLs",
            "Maximum pages",
            "Request delay",
            "Respect robots.txt",
        ],
        "Value": [
            scan_request.mode.value,
            str(len(scan_request.urls)),
            str(scan_request.max_pages),
            f"{scan_request.request_delay_seconds:.1f} seconds",
            "Yes" if scan_request.respect_robots_txt else "No",
        ],
    }

    configuration_dataframe = pd.DataFrame(configuration).astype(
        {
            "Setting": "string",
            "Value": "string",
        }
    )

    st.subheader("Validated scan configuration")

    st.dataframe(
        configuration_dataframe,
        hide_index=True,
        width="stretch",
    )

    st.subheader("Starting URLs")

    url_rows = [
        {
            "Number": index,
            "URL": str(url),
        }
        for index, url in enumerate(scan_request.urls, start=1)
    ]

    url_dataframe = pd.DataFrame(url_rows)

    st.dataframe(
        url_dataframe,
        hide_index=True,
        width="stretch",
        column_config={
            "Number": st.column_config.NumberColumn(
                "Number",
                format="%d",
            ),
            "URL": st.column_config.LinkColumn(
                "URL",
                width="large",
            ),
        },
    )


def display_fetch_result(result: FetchResult) -> None:
    """Display the result of fetching one page."""

    st.divider()
    st.subheader("Page fetch result")

    if result.fetch_succeeded:
        st.success("The request completed successfully.")
    else:
        st.error(result.error_message or "The page could not be fetched successfully.")

    metric_columns = st.columns(4)

    with metric_columns[0]:
        status_value = str(result.status_code) if result.status_code is not None else "Unavailable"

        st.metric(
            label="HTTP status",
            value=status_value,
        )

    with metric_columns[1]:
        response_time = (
            f"{result.response_time_ms:,.0f} ms"
            if result.response_time_ms is not None
            else "Unavailable"
        )

        st.metric(
            label="Response time",
            value=response_time,
        )

    with metric_columns[2]:
        st.metric(
            label="Decoded HTML size",
            value=format_bytes(result.body_size_bytes),
        )

    with metric_columns[3]:
        st.metric(
            label="Redirects",
            value=len(result.redirect_chain),
        )

    detail_rows = [
        {
            "Property": "Requested URL",
            "Value": result.requested_url,
        },
        {
            "Property": "Final URL",
            "Value": result.final_url or "Unavailable",
        },
        {
            "Property": "Status description",
            "Value": result.reason_phrase or "Unavailable",
        },
        {
            "Property": "Content type",
            "Value": result.content_type or "Unavailable",
        },
        {
            "Property": "Character encoding",
            "Value": result.encoding or "Unavailable",
        },
        {
            "Property": "Declared content length",
            "Value": format_bytes(result.declared_content_length_bytes),
        },
        {
            "Property": "HTML document",
            "Value": "Yes" if result.is_html else "No",
        },
    ]

    st.dataframe(
        pd.DataFrame(detail_rows),
        hide_index=True,
        width="stretch",
    )

    if result.redirect_chain:
        st.subheader("Redirect chain")

        redirect_rows = [
            {
                "Step": index,
                "Status": redirect.status_code,
                "URL": redirect.url,
                "Location": redirect.location or "",
            }
            for index, redirect in enumerate(
                result.redirect_chain,
                start=1,
            )
        ]

        st.dataframe(
            pd.DataFrame(redirect_rows),
            hide_index=True,
            width="stretch",
        )

    if result.body_truncated:
        st.warning(
            "The response exceeded the maximum permitted size. The page will not be analyzed."
        )

    elif result.fetch_succeeded and not result.is_html:
        st.warning(
            "The URL did not return an HTML document. "
            "HTML quality checks cannot be performed on this resource."
        )

    elif result.fetch_succeeded and result.is_html:
        st.info("The HTML response was fetched and processed successfully.")

    with st.expander("Response headers"):
        if result.headers:
            header_rows = [
                {
                    "Header": key,
                    "Value": redact_header_value(key, value),
                }
                for key, value in sorted(result.headers.items())
            ]

            header_dataframe = pd.DataFrame(header_rows).astype(
                {
                    "Header": "string",
                    "Value": "string",
                }
            )

            st.dataframe(
                header_dataframe,
                hide_index=True,
                width="stretch",
            )
        else:
            st.write("No response headers were recorded.")


def display_page_data(page: PageData) -> None:
    """Display information extracted from the HTML document."""

    st.divider()
    st.subheader("Parsed page data")

    metric_columns = st.columns(4)

    with metric_columns[0]:
        st.metric(
            "Visible words",
            f"{page.word_count:,}",
        )

    with metric_columns[1]:
        st.metric(
            "Headings",
            len(page.headings),
        )

    with metric_columns[2]:
        st.metric(
            "Links",
            len(page.links),
        )

    with metric_columns[3]:
        st.metric(
            "Images",
            len(page.images),
        )

    metadata_rows = [
        {
            "Property": "Title",
            "Value": page.title or "Missing",
        },
        {
            "Property": "Title length",
            "Value": (str(len(page.title)) if page.title is not None else "0"),
        },
        {
            "Property": "Meta description",
            "Value": page.meta_description or "Missing",
        },
        {
            "Property": "Meta description length",
            "Value": (
                str(len(page.meta_description)) if page.meta_description is not None else "0"
            ),
        },
        {
            "Property": "Canonical URL",
            "Value": page.canonical_url or "Missing",
        },
        {
            "Property": "Document language",
            "Value": page.language or "Missing",
        },
        {
            "Property": "Robots directives",
            "Value": (
                ", ".join(page.robots_directives) if page.robots_directives else "None declared"
            ),
        },
        {
            "Property": "Viewport meta tag",
            "Value": "Present" if page.has_viewport_meta else "Missing",
        },
        {
            "Property": "Character encoding",
            "Value": page.charset or "Unknown",
        },
    ]

    metadata_dataframe = pd.DataFrame(metadata_rows).astype(
        {
            "Property": "string",
            "Value": "string",
        }
    )

    st.dataframe(
        metadata_dataframe,
        hide_index=True,
        width="stretch",
    )

    with st.expander(
        f"Headings ({len(page.headings)})",
        expanded=True,
    ):
        if page.headings:
            heading_rows = [
                {
                    "Position": heading.index,
                    "Level": f"H{heading.level}",
                    "Text": heading.text,
                }
                for heading in page.headings
            ]

            st.dataframe(
                pd.DataFrame(heading_rows),
                hide_index=True,
                width="stretch",
            )
        else:
            st.warning("No headings were found.")

    with st.expander(f"Links ({len(page.links)})"):
        if page.links:
            displayed_links = page.links[:200]

            link_rows = [
                {
                    "Position": link.index,
                    "Text": link.text,
                    "Original href": link.href or "",
                    "Resolved URL": link.resolved_url or "",
                    "Internal": link.is_internal,
                    "Nofollow": link.is_nofollow,
                }
                for link in displayed_links
            ]

            st.dataframe(
                pd.DataFrame(link_rows),
                hide_index=True,
                width="stretch",
                column_config={
                    "Resolved URL": st.column_config.LinkColumn("Resolved URL"),
                },
            )

            if len(page.links) > len(displayed_links):
                st.caption(
                    f"Showing the first {len(displayed_links):,} of {len(page.links):,} links."
                )
        else:
            st.write("No links were found.")

    with st.expander(f"Images ({len(page.images)})"):
        if page.images:
            displayed_images = page.images[:200]

            image_rows = [
                {
                    "Position": image.index,
                    "Source": image.resolved_url or image.src or "",
                    "Alt attribute present": image.has_alt_attribute,
                    "Alt text": (image.alt if image.alt is not None else ""),
                }
                for image in displayed_images
            ]

            st.dataframe(
                pd.DataFrame(image_rows),
                hide_index=True,
                width="stretch",
                column_config={
                    "Source": st.column_config.LinkColumn("Source"),
                },
            )

            if len(page.images) > len(displayed_images):
                st.caption(
                    f"Showing the first {len(displayed_images):,} of {len(page.images):,} images."
                )
        else:
            st.write("No images were found.")


def display_audit_issues(
    issues: list[AuditIssue],
    *,
    title: str = "Page quality issues",
    key_prefix: str = "audit",
) -> None:
    """Display audit findings for one or more pages."""

    st.divider()
    st.subheader(title)

    severity_counts = Counter(issue.severity for issue in issues)

    metric_columns = st.columns(5)

    with metric_columns[0]:
        st.metric(
            "Total issues",
            len(issues),
        )

    with metric_columns[1]:
        st.metric(
            "High",
            severity_counts[IssueSeverity.HIGH],
        )

    with metric_columns[2]:
        st.metric(
            "Medium",
            severity_counts[IssueSeverity.MEDIUM],
        )

    with metric_columns[3]:
        st.metric(
            "Low",
            severity_counts[IssueSeverity.LOW],
        )

    with metric_columns[4]:
        st.metric(
            "Information",
            severity_counts[IssueSeverity.INFO],
        )

    if not issues:
        st.success("No issues were found by the currently implemented rules.")
        return

    issue_rows = [
        {
            "Severity": issue.severity.value,
            "Category": issue.category.value,
            "URL": issue.url,
            "Rule": issue.rule_id,
            "Issue": issue.title,
            "Location": issue.location,
            "Evidence": issue.evidence or "",
            "Explanation": issue.message,
            "Recommendation": issue.recommendation or "",
        }
        for issue in issues
    ]

    issue_dataframe = pd.DataFrame(issue_rows).astype("string")

    st.dataframe(
        issue_dataframe,
        hide_index=True,
        width="stretch",
        height=min(700, 70 + len(issues) * 35),
        column_config={
            "Severity": st.column_config.TextColumn(
                "Severity",
                width="small",
            ),
            "Category": st.column_config.TextColumn(
                "Category",
                width="small",
            ),
            "URL": st.column_config.LinkColumn(
                "Affected URL",
                width="large",
            ),
            "Rule": st.column_config.TextColumn(
                "Rule ID",
                width="medium",
            ),
            "Issue": st.column_config.TextColumn(
                "Issue",
                width="medium",
            ),
            "Location": st.column_config.TextColumn(
                "Location",
                width="medium",
            ),
            "Evidence": st.column_config.TextColumn(
                "Evidence",
                width="large",
            ),
            "Explanation": st.column_config.TextColumn(
                "Explanation",
                width="large",
            ),
            "Recommendation": st.column_config.TextColumn(
                "Recommendation",
                width="large",
            ),
        },
    )

    severity_filter = st.multiselect(
        "Filter by severity",
        options=list(IssueSeverity),
        default=list(IssueSeverity),
        format_func=lambda severity: severity.value,
        key=f"{key_prefix}_severity_filter",
    )

    filtered_issues = [issue for issue in issues if issue.severity in severity_filter]

    st.caption(f"Showing {len(filtered_issues):,} of {len(issues):,} issues.")

    for issue in filtered_issues:
        with st.expander(
            f"{issue.severity.value} · {issue.category.value} · {issue.title}",
        ):
            st.write(issue.message)

            detail_rows = [
                {
                    "Property": "Rule ID",
                    "Value": issue.rule_id,
                },
                {
                    "Property": "Affected URL",
                    "Value": issue.url,
                },
                {
                    "Property": "Location",
                    "Value": issue.location,
                },
                {
                    "Property": "Evidence",
                    "Value": issue.evidence or "Not recorded",
                },
                {
                    "Property": "Recommendation",
                    "Value": (issue.recommendation or "No recommendation recorded"),
                },
            ]

            detail_dataframe = pd.DataFrame(detail_rows).astype("string")

            st.dataframe(
                detail_dataframe,
                hide_index=True,
                width="stretch",
            )


def display_batch_summary(
    batch_result: BatchScanResult,
) -> None:
    """Display aggregate metrics and one summary row per page."""

    pages = batch_result.pages

    successful_fetches = sum(page.fetch_result.fetch_succeeded for page in pages)

    parsed_pages = sum(page.page_data is not None for page in pages)

    all_issues = [issue for page in pages for issue in page.issues]

    severity_counts = Counter(issue.severity for issue in all_issues)

    st.divider()
    st.subheader("Scan summary")

    first_row = st.columns(5)

    with first_row[0]:
        st.metric("Requested pages", len(pages))

    with first_row[1]:
        st.metric("Fetched", successful_fetches)

    with first_row[2]:
        st.metric(
            "Failed",
            len(pages) - successful_fetches,
        )

    with first_row[3]:
        st.metric("Parsed HTML pages", parsed_pages)

    with first_row[4]:
        st.metric(
            "Total duration",
            f"{batch_result.total_duration_ms / 1_000:,.2f} s",
        )

    second_row = st.columns(4)

    with second_row[0]:
        st.metric(
            "High issues",
            severity_counts[IssueSeverity.HIGH],
        )

    with second_row[1]:
        st.metric(
            "Medium issues",
            severity_counts[IssueSeverity.MEDIUM],
        )

    with second_row[2]:
        st.metric(
            "Low issues",
            severity_counts[IssueSeverity.LOW],
        )

    with second_row[3]:
        st.metric(
            "Information",
            severity_counts[IssueSeverity.INFO],
        )

    if batch_result.crawl_metadata is not None:
        crawl = batch_result.crawl_metadata

        st.subheader("Crawl details")

        crawl_columns = st.columns(4)

        with crawl_columns[0]:
            st.metric(
                "Discovered URLs",
                crawl.discovered_url_count,
            )

        with crawl_columns[1]:
            st.metric(
                "Blocked by robots.txt",
                len(crawl.robots_blocked_urls),
            )

        with crawl_columns[2]:
            st.metric(
                "Skipped links",
                crawl.skipped_url_count,
            )

        with crawl_columns[3]:
            st.metric(
                "Effective delay",
                f"{crawl.effective_delay_seconds:.1f} s",
            )

        if crawl.reached_page_limit:
            st.warning(
                "The crawler reached the selected page limit. "
                "Additional internal URLs remained in the queue."
            )

        if crawl.robots_txt_url is not None:
            robots_status = (
                str(crawl.robots_txt_status_code)
                if crawl.robots_txt_status_code is not None
                else "Unavailable"
            )

            st.caption(f"robots.txt: {crawl.robots_txt_url} — HTTP status: {robots_status}")

        if crawl.robots_txt_error:
            st.warning(
                "robots.txt could not be loaded: "
                f"{crawl.robots_txt_error}. "
                "The crawl continued using an allow-all policy."
            )

        if crawl.robots_blocked_urls:
            with st.expander("URLs blocked by robots.txt"):
                blocked_rows = [{"URL": url} for url in crawl.robots_blocked_urls]

                st.dataframe(
                    pd.DataFrame(blocked_rows),
                    hide_index=True,
                    width="stretch",
                    column_config={"URL": st.column_config.LinkColumn("Blocked URL")},
                )

    summary_rows = []

    for result in pages:
        fetch = result.fetch_result
        page = result.page_data
        page_score = calculate_page_score(result)

        page_severity_counts = Counter(issue.severity for issue in result.issues)

        summary_rows.append(
            {
                "Requested URL": fetch.requested_url,
                "Final URL": fetch.final_url or "",
                "Fetch": ("Successful" if fetch.fetch_succeeded else "Failed"),
                "HTTP status": (str(fetch.status_code) if fetch.status_code is not None else ""),
                "Response time": (
                    f"{fetch.response_time_ms:,.0f} ms"
                    if fetch.response_time_ms is not None
                    else ""
                ),
                "Score": (
                    f"{page_score.overall_score:.1f}"
                    if page_score.overall_score is not None
                    else "Not assessed"
                ),
                "Content type": fetch.content_type or "",
                "Title": (page.title if page is not None and page.title else ""),
                "Words": (str(page.word_count) if page is not None else ""),
                "High": str(page_severity_counts[IssueSeverity.HIGH]),
                "Medium": str(page_severity_counts[IssueSeverity.MEDIUM]),
                "Low": str(page_severity_counts[IssueSeverity.LOW]),
                "Info": str(page_severity_counts[IssueSeverity.INFO]),
            }
        )

    summary_dataframe = pd.DataFrame(summary_rows).astype("string")

    st.dataframe(
        summary_dataframe,
        hide_index=True,
        width="stretch",
        height=min(700, 70 + len(summary_rows) * 35),
        column_config={
            "Requested URL": st.column_config.LinkColumn("Requested URL"),
            "Final URL": st.column_config.LinkColumn("Final URL"),
        },
    )


st.title("Website Quality Auditor")

st.write("Analyze a single page, a supplied collection of pages, or crawl an entire website.")

st.caption("Only scan websites you own or are otherwise authorized to test.")

mode = st.radio(
    "What would you like to scan?",
    options=list(ScanMode),
    format_func=lambda selected_mode: selected_mode.value,
    horizontal=True,
    key="scan_mode",
)

with st.form("scan_configuration"):
    raw_url_input = ""

    if mode == ScanMode.SINGLE_PAGE:
        raw_url_input = st.text_input(
            "Page URL",
            placeholder="https://example.com/about",
        )

    elif mode == ScanMode.MULTIPLE_PAGES:
        raw_url_input = st.text_area(
            "Page URLs",
            placeholder=(
                "Enter one URL per line:\n"
                "https://example.com/\n"
                "https://example.com/about\n"
                "https://example.com/contact"
            ),
            height=180,
        )

    else:
        raw_url_input = st.text_input(
            "Starting website URL",
            placeholder="https://example.com",
            help="The crawler will discover internal pages from this URL.",
        )

    left_column, right_column = st.columns(2)

    with left_column:
        if mode == ScanMode.WHOLE_WEBSITE:
            selected_max_pages = st.number_input(
                "Maximum pages",
                min_value=1,
                max_value=1_000,
                value=50,
                step=10,
            )
        else:
            selected_max_pages = 1

    with right_column:
        request_delay = st.number_input(
            "Delay between requests in seconds",
            min_value=0.0,
            max_value=10.0,
            value=0.5,
            step=0.1,
        )

    respect_robots_txt = st.checkbox(
        "Respect robots.txt",
        value=True,
        help="Recommended for whole-website scans.",
    )

    submitted = st.form_submit_button(
        "Validate scan",
        type="primary",
        width="stretch",
    )


if submitted:
    try:
        if mode == ScanMode.MULTIPLE_PAGES:
            urls = parse_url_list(raw_url_input)
        else:
            urls = [normalize_url(raw_url_input)]

        if mode == ScanMode.WHOLE_WEBSITE:
            maximum_pages = selected_max_pages
        else:
            maximum_pages = len(urls)

        scan_request = ScanRequest(
            mode=mode,
            urls=urls,
            max_pages=maximum_pages,
            request_delay_seconds=request_delay,
            respect_robots_txt=respect_robots_txt,
        )

        serialized_request = scan_request.model_dump(mode="json")

        if st.session_state.get("scan_request") != serialized_request:
            st.session_state.pop("batch_scan_result", None)
            st.session_state.pop("fetch_result", None)
            st.session_state.pop("selected_scan_page", None)

        st.session_state["scan_request"] = serialized_request

    except (ValueError, ValidationError) as error:
        st.error(str(error))

if "scan_request" in st.session_state:
    validated_request = ScanRequest.model_validate(st.session_state["scan_request"])

    st.success("The scan configuration is valid.")
    display_scan_configuration(validated_request)

    scan_urls = [str(url) for url in validated_request.urls]

    if validated_request.mode == ScanMode.SINGLE_PAGE:
        scan_button_label = "Scan page"

    elif validated_request.mode == ScanMode.MULTIPLE_PAGES:
        scan_button_label = f"Scan {len(scan_urls):,} pages"

    else:
        scan_button_label = f"Crawl website (up to {validated_request.max_pages:,} pages)"

    if st.button(
        scan_button_label,
        type="primary",
        width="stretch",
    ):
        progress_bar = st.progress(0.0)
        status_placeholder = st.empty()

        page_results = []
        crawl_metadata = None

        scan_started_at = perf_counter()

        with PageFetcher() as fetcher:
            scanner = BatchScanner(fetcher)

            if validated_request.mode == ScanMode.WHOLE_WEBSITE:
                crawler = WebsiteCrawler(scanner)

                def update_crawl_progress(
                    scanned_count: int,
                    maximum_pages: int,
                    page_result,
                    queued_count: int,
                ) -> None:
                    status_placeholder.write(
                        f"Crawled {scanned_count:,} page(s); "
                        f"{queued_count:,} URL(s) queued. "
                        f"Current: "
                        f"{page_result.fetch_result.requested_url}"
                    )

                    progress_bar.progress(
                        min(
                            scanned_count / maximum_pages,
                            1.0,
                        )
                    )

                crawl_result = crawler.crawl(
                    scan_urls[0],
                    max_pages=validated_request.max_pages,
                    request_delay_seconds=(validated_request.request_delay_seconds),
                    respect_robots_txt=(validated_request.respect_robots_txt),
                    progress_callback=update_crawl_progress,
                )

                page_results = crawl_result.pages
                crawl_metadata = crawl_result.metadata

            else:
                for index, page_result in enumerate(
                    scanner.scan_urls(
                        scan_urls,
                        request_delay_seconds=(validated_request.request_delay_seconds),
                    ),
                    start=1,
                ):
                    page_results.append(page_result)

                    status_placeholder.write(
                        f"Scanned {index:,} of "
                        f"{len(scan_urls):,}: "
                        f"{page_result.fetch_result.requested_url}"
                    )

                    progress_bar.progress(index / len(scan_urls))

        total_duration_ms = round(
            (perf_counter() - scan_started_at) * 1_000,
            2,
        )

        batch_result = BatchScanResult(
            mode=validated_request.mode,
            pages=page_results,
            total_duration_ms=total_duration_ms,
            crawl_metadata=crawl_metadata,
        )

        st.session_state["batch_scan_result"] = batch_result.model_dump(mode="json")

        progress_bar.empty()
        status_placeholder.empty()

    if "batch_scan_result" in st.session_state:
        stored_batch_result = BatchScanResult.model_validate(st.session_state["batch_scan_result"])

        display_batch_summary(stored_batch_result)

        batch_score = calculate_batch_score(stored_batch_result)

        display_score_dashboard(
            batch_score,
            title="Website quality score",
        )

        display_export_buttons(
            stored_batch_result,
            batch_score,
        )

        all_issues = [
            issue for page_result in stored_batch_result.pages for issue in page_result.issues
        ]

        display_audit_issues(
            all_issues,
            title="Issues across all scanned pages",
            key_prefix="batch",
        )

        if stored_batch_result.pages:
            st.divider()
            st.subheader("Inspect individual page")

            selected_page_index = st.selectbox(
                "Page",
                options=range(len(stored_batch_result.pages)),
                format_func=lambda index: (
                    stored_batch_result.pages[index].fetch_result.final_url
                    or stored_batch_result.pages[index].fetch_result.requested_url
                ),
                key="selected_scan_page",
            )

            selected_result = stored_batch_result.pages[selected_page_index]

            selected_page_score = calculate_page_score(selected_result)

            display_score_dashboard(
                selected_page_score,
                title="Selected page quality score",
            )

            display_fetch_result(selected_result.fetch_result)

            if selected_result.processing_error_message:
                st.error(f"Page processing error: {selected_result.processing_error_message}")

            if selected_result.page_data is not None:
                display_page_data(selected_result.page_data)

            display_audit_issues(
                selected_result.issues,
                title="Issues for selected page",
                key_prefix=f"page_{selected_page_index}",
            )

        else:
            st.warning(
                "No pages were scanned. Check the starting URL and robots.txt crawl permissions."
            )
