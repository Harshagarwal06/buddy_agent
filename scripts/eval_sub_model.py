"""Measure sub_model performance on frozen article fixtures.

Opt-in: this script makes real model calls and is never run by CI.

    python -m scripts.eval_sub_model --capture
    python -m scripts.eval_sub_model --run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

from scripts.eval_store import save_fixtures

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "scripts" / "eval_fixtures"
ARCHIVE_BASE = "https://harshagarwal06.github.io/buddy_agent/"
DEFAULT_CORPUS = 25


def _fetch_json(url: str):
    response = httpx.get(url, timeout=30.0, follow_redirects=True)
    response.raise_for_status()
    return response.json()


def _extract_body(url: str) -> str:
    from news_buddy.extract import extract_body

    return extract_body(url) or ""


def capture(base_url: str, limit: int, fixtures_dir: Path) -> int:
    base = base_url.rstrip("/") + "/"
    manifest = _fetch_json(base + "index.json")

    articles: list[dict] = []
    for date in manifest.get("dates", []):
        if len(articles) >= limit:
            break
        for record in _fetch_json(f"{base}{date}.json"):
            if len(articles) >= limit:
                break
            url = record.get("url", "")
            if not url:
                continue
            body = _extract_body(url)
            if not body.strip():
                print(f"  skipped (no body): {url}", file=sys.stderr)
                continue
            articles.append({
                "url": url,
                "title": record.get("title", ""),
                "source": record.get("source", ""),
                "published_at": record.get("published_at", ""),
                "body": body,
            })
            print(f"  captured: {record.get('title', '')[:60]}", file=sys.stderr)

    save_fixtures(fixtures_dir, articles)
    return len(articles)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true", help="Snapshot fixtures from the published archive")
    parser.add_argument("--limit", type=int, default=DEFAULT_CORPUS, help="Number of articles")
    parser.add_argument("--archive-base", default=ARCHIVE_BASE)
    args = parser.parse_args(argv)

    if args.capture:
        count = capture(args.archive_base, args.limit, FIXTURES_DIR)
        print(f"Captured {count} articles to {FIXTURES_DIR}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
