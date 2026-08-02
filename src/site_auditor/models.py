from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl


class ScanMode(StrEnum):
    """Available website scanning strategies."""

    SINGLE_PAGE = "Single page"
    MULTIPLE_PAGES = "Multiple pages"
    WHOLE_WEBSITE = "Whole website"


class ScanRequest(BaseModel):
    """Validated configuration for a website scan."""

    mode: ScanMode
    urls: list[HttpUrl]

    max_pages: int = Field(default=50, ge=1, le=1_000)
    request_delay_seconds: float = Field(default=0.5, ge=0.0, le=10.0)
    respect_robots_txt: bool = True


class RedirectHop(BaseModel):
    """One HTTP redirect encountered while fetching a page."""

    status_code: int
    url: str
    location: str | None = None


class FetchResult(BaseModel):
    """Structured result returned by the HTTP fetcher."""

    requested_url: str
    final_url: str | None = None

    fetch_succeeded: bool = False

    status_code: int | None = None
    reason_phrase: str | None = None
    response_time_ms: float | None = None

    content_type: str | None = None
    encoding: str | None = None

    body_size_bytes: int = 0
    declared_content_length_bytes: int | None = None
    body_truncated: bool = False

    is_html: bool = False
    html: str | None = None

    headers: dict[str, str] = Field(default_factory=dict)
    redirect_chain: list[RedirectHop] = Field(default_factory=list)

    error_type: str | None = None
    error_message: str | None = None


class HeadingData(BaseModel):
    """One heading extracted from an HTML page."""

    index: int = Field(ge=1)
    level: int = Field(ge=1, le=6)
    text: str


class LinkData(BaseModel):
    """One hyperlink extracted from an HTML page."""

    index: int = Field(ge=1)
    text: str
    href: str | None = None
    resolved_url: str | None = None
    is_internal: bool = False
    is_nofollow: bool = False


class ImageData(BaseModel):
    """One image extracted from an HTML page."""

    index: int = Field(ge=1)
    src: str | None = None
    resolved_url: str | None = None
    alt: str | None = None
    has_alt_attribute: bool = False


class PageData(BaseModel):
    """Structured information extracted from one HTML document."""

    url: str

    title: str | None = None
    meta_description: str | None = None
    canonical_url: str | None = None
    language: str | None = None

    robots_directives: list[str] = Field(default_factory=list)

    has_viewport_meta: bool = False
    charset: str | None = None
    word_count: int = 0

    headings: list[HeadingData] = Field(default_factory=list)
    links: list[LinkData] = Field(default_factory=list)
    images: list[ImageData] = Field(default_factory=list)


class IssueSeverity(StrEnum):
    """Severity assigned to an audit issue."""

    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    INFO = "Info"


class IssueCategory(StrEnum):
    """Website quality category associated with an issue."""

    TECHNICAL = "Technical"
    SEO = "SEO"
    ACCESSIBILITY = "Accessibility"
    CONTENT = "Content"


class AuditIssue(BaseModel):
    """One issue discovered while auditing a page."""

    rule_id: str
    category: IssueCategory
    severity: IssueSeverity

    title: str
    message: str

    url: str
    location: str

    evidence: str | None = None
    recommendation: str | None = None


class PageScanResult(BaseModel):
    """Complete scan result for one requested URL."""

    fetch_result: FetchResult
    page_data: PageData | None = None
    issues: list[AuditIssue] = Field(default_factory=list)

    processing_error_type: str | None = None
    processing_error_message: str | None = None


class CrawlMetadata(BaseModel):
    """Information collected during a whole-website crawl."""

    start_url: str
    discovered_url_count: int = Field(default=0, ge=0)
    skipped_url_count: int = Field(default=0, ge=0)

    robots_blocked_urls: list[str] = Field(default_factory=list)

    reached_page_limit: bool = False

    robots_txt_url: str | None = None
    robots_txt_status_code: int | None = None
    robots_txt_error: str | None = None

    effective_delay_seconds: float = Field(default=0.0, ge=0.0)


class CrawlResult(BaseModel):
    """Pages and metadata returned by a website crawl."""

    pages: list[PageScanResult] = Field(default_factory=list)
    metadata: CrawlMetadata


class BatchScanResult(BaseModel):
    """Results from scanning one or more URLs."""

    mode: ScanMode
    pages: list[PageScanResult] = Field(default_factory=list)
    total_duration_ms: float = Field(ge=0)

    crawl_metadata: CrawlMetadata | None = None
