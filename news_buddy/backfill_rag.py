#!/usr/bin/env python3
"""
One-time backfill of the RAG vector store from state.db.

Articles are normally embedded into chroma_db at the moment they are first
seen (see agent.py). Any article that was marked "seen" before RAG existed
never got embedded, so semantic search can't find it. This script walks every
row in state.db.seen and embeds it (title-only — the seen table stores no body,
and embed_article falls back to title text). Already-indexed URLs are skipped
by embed_article, so the script is safe to re-run.

Usage:
    python news_buddy/backfill_rag.py
    python news_buddy/backfill_rag.py --db-path /custom/state.db

Requires GOOGLE_API_KEY (loaded from .env).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

# Google free-tier allows ~100 embed requests/minute. Pace below that and
# retry on RESOURCE_EXHAUSTED so the full archive backfills in one pass.
_MIN_INTERVAL = 0.7  # seconds between embed calls (~85/min)
_MAX_RETRIES = 5

_ROOT = Path(__file__).parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(prog="backfill_rag.py")
    parser.add_argument(
        "--db-path",
        default=str(_ROOT / "state.db"),
        help="Path to state.db (default: project root)",
    )
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")

    from news_buddy.rag import embed_article, _get_collection

    db_path = Path(args.db_path).expanduser().resolve()
    if not db_path.exists():
        print(f"error: state.db not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT url, source, title FROM seen").fetchall()
    conn.close()

    before = _get_collection().count()
    print(f"state.db: {len(rows)} seen articles | chroma before: {before}")

    embedded = skipped = failed = 0
    for i, r in enumerate(rows, 1):
        if _get_collection().get(ids=[r["url"]])["ids"]:
            skipped += 1
            continue
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                time.sleep(_MIN_INTERVAL)
                embed_article(url=r["url"], title=r["title"], body="", source=r["source"])
                embedded += 1
                if embedded % 20 == 0:
                    print(f"  ...{embedded} embedded ({i}/{len(rows)})")
                break
            except Exception as e:  # noqa: BLE001
                if "RESOURCE_EXHAUSTED" in str(e) and attempt < _MAX_RETRIES:
                    wait = 30 * attempt
                    print(f"  [rate-limit] sleeping {wait}s (attempt {attempt})", file=sys.stderr)
                    time.sleep(wait)
                    continue
                failed += 1
                print(f"  [warn] failed {r['url']}: {str(e)[:120]}", file=sys.stderr)
                break

    after = _get_collection().count()
    print(
        f"done. embedded={embedded} skipped={skipped} failed={failed} "
        f"| chroma after: {after}"
    )


if __name__ == "__main__":
    main()
