from urllib.parse import urlparse, urlunparse

SUPPORTED_SCHEMES = {"http", "https"}


def normalize_url(raw_url: str) -> str:
    """
    Normalize and validate a user-provided URL.

    The function:
    - removes surrounding whitespace,
    - adds HTTPS when the scheme is missing,
    - rejects unsupported schemes,
    - removes URL fragments.
    """

    value = raw_url.strip()

    if not value:
        raise ValueError("URL cannot be empty.")

    if "://" not in value:
        value = f"https://{value}"

    parsed = urlparse(value)

    if parsed.scheme.lower() not in SUPPORTED_SCHEMES:
        raise ValueError(
            f"Unsupported URL scheme: {parsed.scheme!r}. Only HTTP and HTTPS URLs are supported."
        )

    if not parsed.netloc:
        raise ValueError(f"Invalid URL: {raw_url!r}")

    if parsed.username or parsed.password:
        raise ValueError("URLs with embedded credentials are not supported.")

    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        fragment="",
    )

    return urlunparse(normalized)


def parse_url_list(raw_text: str) -> list[str]:
    """
    Parse newline-separated URLs and remove duplicates.

    Original ordering is preserved.
    """

    normalized_urls: list[str] = []
    seen: set[str] = set()

    for line in raw_text.splitlines():
        if not line.strip():
            continue

        normalized_url = normalize_url(line)

        if normalized_url not in seen:
            seen.add(normalized_url)
            normalized_urls.append(normalized_url)

    if not normalized_urls:
        raise ValueError("Enter at least one valid URL.")

    return normalized_urls
