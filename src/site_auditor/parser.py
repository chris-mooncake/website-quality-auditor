from __future__ import annotations

import re
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from site_auditor.models import (
    FetchResult,
    HeadingData,
    ImageData,
    LinkData,
    PageData,
)

HTTP_SCHEMES = {"http", "https"}


class PageParser:
    """Convert a fetched HTML document into structured page data."""

    @classmethod
    def parse(cls, fetch_result: FetchResult) -> PageData:
        """Parse one successful HTML fetch result."""

        if not fetch_result.fetch_succeeded:
            raise ValueError("Cannot parse an unsuccessful fetch result.")

        if not fetch_result.is_html:
            raise ValueError("Cannot parse a non-HTML response.")

        if fetch_result.html is None:
            raise ValueError("The fetch result does not contain HTML.")

        page_url = fetch_result.final_url or fetch_result.requested_url
        soup = BeautifulSoup(fetch_result.html, "lxml")

        title = cls._extract_title(soup)
        meta_description = cls._find_meta_content(
            soup,
            name="description",
        )
        canonical_url = cls._extract_canonical_url(
            soup,
            base_url=page_url,
        )
        language = cls._extract_language(soup)

        robots_content = cls._find_meta_content(
            soup,
            name="robots",
        )

        robots_directives = cls._parse_directives(robots_content)

        headings = cls._extract_headings(soup)
        links = cls._extract_links(
            soup,
            base_url=page_url,
        )
        images = cls._extract_images(
            soup,
            base_url=page_url,
        )

        word_count = cls._calculate_visible_word_count(soup)

        return PageData(
            url=page_url,
            title=title,
            meta_description=meta_description,
            canonical_url=canonical_url,
            language=language,
            robots_directives=robots_directives,
            has_viewport_meta=cls._has_meta_name(
                soup,
                name="viewport",
            ),
            charset=fetch_result.encoding,
            word_count=word_count,
            headings=headings,
            links=links,
            images=images,
        )

    @classmethod
    def _extract_title(
        cls,
        soup: BeautifulSoup,
    ) -> str | None:
        if soup.title is None:
            return None

        return cls._clean_text(soup.title)

    @classmethod
    def _extract_language(
        cls,
        soup: BeautifulSoup,
    ) -> str | None:
        html_element = soup.find("html")

        if not isinstance(html_element, Tag):
            return None

        language = html_element.get("lang")

        if not isinstance(language, str):
            return None

        language = language.strip()

        return language or None

    @classmethod
    def _extract_canonical_url(
        cls,
        soup: BeautifulSoup,
        *,
        base_url: str,
    ) -> str | None:
        for link_element in soup.find_all("link"):
            relation = link_element.get("rel")
            relation_values = cls._attribute_tokens(relation)

            if "canonical" not in relation_values:
                continue

            href = cls._non_empty_attribute(
                link_element,
                "href",
            )

            if href is None:
                return None

            return cls._resolve_http_url(
                href,
                base_url=base_url,
            )

        return None

    @classmethod
    def _extract_headings(
        cls,
        soup: BeautifulSoup,
    ) -> list[HeadingData]:
        heading_elements = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])

        headings: list[HeadingData] = []

        for index, heading_element in enumerate(
            heading_elements,
            start=1,
        ):
            level = int(heading_element.name[1])

            headings.append(
                HeadingData(
                    index=index,
                    level=level,
                    text=cls._clean_text(heading_element),
                )
            )

        return headings

    @classmethod
    def _extract_links(
        cls,
        soup: BeautifulSoup,
        *,
        base_url: str,
    ) -> list[LinkData]:
        links: list[LinkData] = []

        base_hostname = cls._hostname(base_url)

        for index, link_element in enumerate(
            soup.find_all("a"),
            start=1,
        ):
            href = cls._non_empty_attribute(
                link_element,
                "href",
            )

            resolved_url = None

            if href is not None:
                resolved_url = cls._resolve_http_url(
                    href,
                    base_url=base_url,
                )

            resolved_hostname = cls._hostname(resolved_url) if resolved_url is not None else None

            relation_values = cls._attribute_tokens(link_element.get("rel"))

            links.append(
                LinkData(
                    index=index,
                    text=cls._clean_text(link_element),
                    href=href,
                    resolved_url=resolved_url,
                    is_internal=(
                        resolved_hostname is not None and resolved_hostname == base_hostname
                    ),
                    is_nofollow="nofollow" in relation_values,
                )
            )

        return links

    @classmethod
    def _extract_images(
        cls,
        soup: BeautifulSoup,
        *,
        base_url: str,
    ) -> list[ImageData]:
        images: list[ImageData] = []

        for index, image_element in enumerate(
            soup.find_all("img"),
            start=1,
        ):
            source = cls._non_empty_attribute(
                image_element,
                "src",
            )

            alt_value = image_element.get("alt")
            has_alt_attribute = alt_value is not None

            if alt_value is None:
                alt = None
            else:
                alt = str(alt_value).strip()

            resolved_url = None

            if source is not None:
                resolved_url = cls._resolve_http_url(
                    source,
                    base_url=base_url,
                )

            images.append(
                ImageData(
                    index=index,
                    src=source,
                    resolved_url=resolved_url,
                    alt=alt,
                    has_alt_attribute=has_alt_attribute,
                )
            )

        return images

    @classmethod
    def _calculate_visible_word_count(
        cls,
        soup: BeautifulSoup,
    ) -> int:
        body = soup.body or soup

        hidden_elements = body.find_all(
            [
                "script",
                "style",
                "noscript",
                "template",
                "svg",
            ]
        )

        for hidden_element in hidden_elements:
            hidden_element.decompose()

        visible_text = body.get_text(
            separator=" ",
            strip=True,
        )

        words = re.findall(
            r"\b[\w'-]+\b",
            visible_text,
            flags=re.UNICODE,
        )

        return len(words)

    @classmethod
    def _find_meta_content(
        cls,
        soup: BeautifulSoup,
        *,
        name: str,
    ) -> str | None:
        expected_name = name.lower()

        for meta_element in soup.find_all("meta"):
            meta_name = meta_element.get("name")

            if not isinstance(meta_name, str):
                continue

            if meta_name.strip().lower() != expected_name:
                continue

            content = meta_element.get("content")

            if not isinstance(content, str):
                return None

            content = content.strip()

            return content or None

        return None

    @classmethod
    def _has_meta_name(
        cls,
        soup: BeautifulSoup,
        *,
        name: str,
    ) -> bool:
        expected_name = name.lower()

        for meta_element in soup.find_all("meta"):
            meta_name = meta_element.get("name")

            if isinstance(meta_name, str) and meta_name.strip().lower() == expected_name:
                return True

        return False

    @staticmethod
    def _parse_directives(
        raw_directives: str | None,
    ) -> list[str]:
        if raw_directives is None:
            return []

        return [
            directive.strip().lower()
            for directive in raw_directives.split(",")
            if directive.strip()
        ]

    @staticmethod
    def _attribute_tokens(
        value: object,
    ) -> set[str]:
        if value is None:
            return set()

        if isinstance(value, str):
            values = value.split()
        elif isinstance(value, list):
            values = [str(item) for item in value]
        else:
            values = [str(value)]

        return {item.strip().lower() for item in values if item.strip()}

    @staticmethod
    def _non_empty_attribute(
        element: Tag,
        attribute_name: str,
    ) -> str | None:
        value = element.get(attribute_name)

        if value is None:
            return None

        value = str(value).strip()

        return value or None

    @staticmethod
    def _resolve_http_url(
        raw_url: str,
        *,
        base_url: str,
    ) -> str | None:
        resolved_url = urljoin(base_url, raw_url)
        resolved_url, _fragment = urldefrag(resolved_url)

        parsed_url = urlparse(resolved_url)

        if parsed_url.scheme.lower() not in HTTP_SCHEMES:
            return None

        if not parsed_url.netloc:
            return None

        return resolved_url

    @staticmethod
    def _hostname(url: str | None) -> str | None:
        if url is None:
            return None

        return urlparse(url).hostname

    @staticmethod
    def _clean_text(element: Tag) -> str:
        text = element.get_text(
            separator=" ",
            strip=True,
        )

        return " ".join(text.split())
