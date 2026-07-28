#!/usr/bin/env python3
"""
One-off backfill: build the public search index from already-published
gh-pages HTML digests.

Usage:
    python scripts/backfill_index.py <gh-pages-base-url> <output-dir>

Discovers historical dates from the archive's index.html, fetches each
YYYY-MM-DD.html, parses out article records, and writes YYYY-MM-DD.json +
index.json into <output-dir>. Run once; the caller is responsible for
committing the output into the gh-pages branch (see the plan's deployment
task for the exact git commands).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import httpx

from news_buddy.index_writer import write_index, write_manifest

_DAY_LINK = re.compile(r'href="(\d{4}-\d{2}-\d{2})\.html"')
_ARTICLE = re.compile(r'<article class="article-card[^"]*"[^>]*data-tags="([^"]*)"[^>]*>(.*?)</article>', re.S)
_TITLE = re.compile(r'<a href="([^"]+)"[^>]*class="card-title">([^<]*)</a>')
_META_SOURCE = re.compile(r'<div class="card-meta">([^<]*)')
_META_DATE = re.compile(
    r'(?:datetime="|<span class="dot">·</span>\s*)(\d{4}-\d{2}-\d{2})'
)
_SUMMARY = re.compile(r"<p class='card-summary'>(.*?)</p>", re.S)
_IMPORTANCE = re.compile(r'aria-label="Importance (\d) of 5"')


def parse_archive_dates(index_html: str) -> list[str]:
    """Extract YYYY-MM-DD dates linked from the archive's index.html, in document order."""
    return _DAY_LINK.findall(index_html)


def parse_digest_html(html: str) -> list[dict]:
    """Parse article records out of one day's rendered digest HTML."""
    records: list[dict] = []
    for tags_csv, block in _ARTICLE.findall(html):
        title_m = _TITLE.search(block)
        if not title_m:
            continue
        url, title = title_m.group(1), title_m.group(2)

        source_m = _META_SOURCE.search(block)
        source = source_m.group(1).strip() if source_m else ""

        date_m = _META_DATE.search(block)
        published_at = date_m.group(1) if date_m else ""

        summary_m = _SUMMARY.search(block)
        summary = summary_m.group(1).strip() if summary_m else ""

        importance_m = _IMPORTANCE.search(block)
        # _article_card's aria-label carries the raw importance value.
        # Clamp it so backfilled records match the pipeline's 1-5 range.
        importance = max(1, min(5, int(importance_m.group(1)))) if importance_m else 3

        records.append({
            "title": title,
            "url": url,
            "source": source,
            "published_at": published_at,
            "summary": summary,
            "tags": [t for t in tags_csv.split(",") if t],
            "importance": importance,
        })
    return records


def backfill(base_url: str, output_dir: Path) -> None:
    base_url = base_url.rstrip("/")
    with httpx.Client(timeout=30) as client:
        index_resp = client.get(f"{base_url}/index.html")
        index_resp.raise_for_status()
        dates = parse_archive_dates(index_resp.text)
        print(f"Found {len(dates)} archived digests", file=sys.stderr)

        for date_str in dates:
            resp = client.get(f"{base_url}/{date_str}.html")
            resp.raise_for_status()
            records = parse_digest_html(resp.text)
            write_index(output_dir, date_str, records)
            print(f"  {date_str}: {len(records)} articles", file=sys.stderr)

    write_manifest(output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="Published gh-pages base URL, e.g. https://user.github.io/repo")
    parser.add_argument("output_dir", help="Local directory to write JSON files into")
    args = parser.parse_args()
    backfill(args.base_url, Path(args.output_dir))


if __name__ == "__main__":
    main()
