"""SQLite-backed seen-URL tracking for cross-day dedup."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def ensure_schema(db_path: str | Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen (
                url           TEXT PRIMARY KEY,
                source        TEXT NOT NULL,
                title         TEXT NOT NULL,
                first_seen_at TEXT NOT NULL
            )
            """
        )


def is_seen(db_path: str | Path, url: str) -> bool:
    ensure_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT 1 FROM seen WHERE url = ?", (url,)).fetchone()
    return row is not None


def filter_unseen(db_path: str | Path, items: list[dict]) -> list[dict]:
    if not items:
        return []
    ensure_schema(db_path)
    urls = [it["url"] for it in items]
    placeholders = ",".join("?" * len(urls))
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT url FROM seen WHERE url IN ({placeholders})", urls
        ).fetchall()
    seen = {r[0] for r in rows}
    return [it for it in items if it["url"] not in seen]


def mark_seen(db_path: str | Path, item: dict) -> None:
    ensure_schema(db_path)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen (url, source, title, first_seen_at) "
            "VALUES (?, ?, ?, ?)",
            (item["url"], item["source"], item["title"], now),
        )
