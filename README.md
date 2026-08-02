# Website Quality Auditor

A Streamlit application that audits websites for technical, SEO, accessibility,
and content quality issues. Scan a single page, a supplied list of pages, or
crawl an entire website, then review scored results and export them as CSV or
JSON.

## Features

- **Three scan modes**
  - **Single page** — audit one URL.
  - **Multiple pages** — audit a list of URLs you paste in.
  - **Whole website** — breadth-first crawl of internal pages starting from
    one URL, with a configurable page limit, request delay, and optional
    `robots.txt` compliance.
- **Quality scoring** — each page is scored 0–100 in four weighted
  categories (Technical 30%, SEO 25%, Accessibility 25%, Content 20%), with an
  overall weighted score per page and per scan.
- **Audit rules** covering HTTP status, HTTPS usage, title/meta description
  length, canonical URLs, document language, viewport meta tag, heading
  structure, image alt attributes, duplicate/empty headings, and thin content.
- **Exports** — download the full issue list and per-page summary as CSV, or
  the complete scan (data + scores) as JSON.
- **SSRF-safe fetching** — outbound requests (including redirects and
  `robots.txt` lookups) are checked against the resolved IP address and
  refused if it's a private, loopback, link-local, or otherwise non-public
  address.

## Requirements

- Python 3.12+

## Installation

```bash
pip install -e ".[dev]"
```

This installs the app's runtime dependencies (`streamlit`, `httpx`,
`beautifulsoup4`, `lxml`, `pydantic`, `pandas`) plus the dev tools
(`pytest`, `ruff`).

## Running the app

```bash
streamlit run app.py
```

Streamlit will open the app in your browser (default `http://localhost:8501`).
Pick a scan mode, enter one or more URLs, click **Validate scan** to check the
configuration, then click the scan button to run it.

> Only scan websites you own or are otherwise authorized to test.

## Project layout

```
app.py                      Streamlit UI
src/site_auditor/
  fetcher.py                 HTTP fetching (redirects, size limits, timeouts)
  crawler.py                 Website crawling, robots.txt handling
  parser.py                  HTML parsing into structured page data
  auditor.py                 Quality rules run against parsed pages
  scanner.py                 Fetch + parse + audit pipeline for one/many URLs
  scoring.py                 Category and overall score calculation
  reporting.py               CSV/JSON export generation
  models.py                  Pydantic data models
  url_utils.py                URL validation and normalization
  net_safety.py               SSRF guard (public-address validation)
tests/                       Test suite (pytest)
```

## Development

Run the test suite:

```bash
pytest
```

Run the linter:

```bash
ruff check .
```
