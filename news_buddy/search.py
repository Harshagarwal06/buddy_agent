#!/usr/bin/env python3
"""
Standalone topic-search script for the News Buddy state.db.

Usage:
    python news_buddy/search.py "AI chips"
    python news_buddy/search.py "AI chips" --source "VentureBeat"
    python news_buddy/search.py "AI chips" --limit 10
    python news_buddy/search.py "AI chips" --db-path /custom/path/state.db

Output: JSON to stdout.
  {"query": "AI chips", "source_filter": null, "count": 3, "results": [...]}

Exit codes:
  0  -- success (including 0 results -- check JSON count field)
  1  -- DB not found / schema error
  2  -- bad arguments
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS seen (
    url           TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    title         TEXT NOT NULL,
    first_seen_at TEXT NOT NULL
)
"""


def _open_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        _die(
            1,
            f"Database not found: {db_path}\n"
            "Run the news-buddy agent at least once to initialise state.db.",
        )
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(_SCHEMA_SQL)
        return conn
    except sqlite3.Error as exc:
        _die(1, f"Failed to open database: {exc}")


def _die(code: int, message: str) -> None:
    payload = {"error": message, "query": "", "count": 0, "results": []}
    print(json.dumps(payload, ensure_ascii=False), file=sys.stdout)
    sys.exit(code)


def search(
    db_path: Path,
    keyword: str,
    source: str | None = None,
    limit: int = 20,
) -> dict:
    """
    Return a dict ready for JSON serialisation.

    Each word in the keyword must appear in the title (AND logic).
    Orders results by most-recent first.
    """
    conn = _open_db(db_path)

    words = keyword.strip().split()
    conditions = [f"title LIKE ?" for _ in words]
    params: list = [f"%{w}%" for w in words]

    if source:
        conditions.append("source LIKE ?")
        params.append(f"%{source}%")

    where = " AND ".join(conditions)
    sql = (
        f"SELECT title, source, url, first_seen_at "
        f"FROM seen WHERE {where} "
        f"ORDER BY first_seen_at DESC "
        f"LIMIT ?"
    )
    params.append(limit)

    with conn:
        rows = conn.execute(sql, params).fetchall()

    results = [dict(r) for r in rows]

    count_sql = f"SELECT COUNT(*) FROM seen WHERE {where}"
    with conn:
        total = conn.execute(count_sql, params[:-1]).fetchone()[0]

    return {
        "query": keyword,
        "source_filter": source,
        "limit": limit,
        "total_matches": total,
        "truncated": total > limit,
        "count": len(results),
        "results": results,
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="search.py",
        description="Search past articles in state.db by keyword.",
    )
    p.add_argument(
        "keyword",
        help="Search term (matched against article titles, case-insensitive)",
    )
    p.add_argument(
        "--source",
        default=None,
        help='Filter by source feed name, e.g. --source "VentureBeat"',
    )
    p.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of results to return (default: 20)",
    )
    p.add_argument(
        "--db-path",
        default=None,
        help="Path to state.db. Defaults to state.db in the project root.",
    )
    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.limit < 1 or args.limit > 500:
        _die(2, "--limit must be between 1 and 500")

    if args.db_path:
        db_path = Path(args.db_path).expanduser().resolve()
    else:
        db_path = Path(__file__).parent.parent / "state.db"

    result = search(
        db_path=db_path,
        keyword=args.keyword,
        source=args.source,
        limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
