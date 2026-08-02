import pytest

from site_auditor.url_utils import normalize_url, parse_url_list


def test_adds_https_when_scheme_is_missing() -> None:
    assert normalize_url("example.com") == "https://example.com"


def test_preserves_path_and_query_string() -> None:
    result = normalize_url("https://example.com/products?page=2")

    assert result == "https://example.com/products?page=2"


def test_removes_fragment() -> None:
    result = normalize_url("https://example.com/about#team")

    assert result == "https://example.com/about"


def test_converts_domain_to_lowercase() -> None:
    result = normalize_url("HTTPS://EXAMPLE.COM/About")

    assert result == "https://example.com/About"


def test_rejects_unsupported_scheme() -> None:
    with pytest.raises(ValueError, match="Unsupported URL scheme"):
        normalize_url("ftp://example.com/file.txt")


def test_rejects_empty_url() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        normalize_url("   ")


def test_parses_and_deduplicates_url_list() -> None:
    result = parse_url_list(
        """
        example.com
        https://example.com
        https://example.com/about
        """
    )

    assert result == [
        "https://example.com",
        "https://example.com/about",
    ]
