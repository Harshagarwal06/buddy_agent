#!/usr/bin/env python3
"""
CLI wrapper for RAG-based semantic search over the news archive.

Usage:
    python news_buddy/semantic_search_cli.py "AI chip shortage"
    python news_buddy/semantic_search_cli.py "AI chip shortage" --limit 10

Output: JSON to stdout.
Exit codes: 0 success, 1 error (chroma_db missing or GOOGLE_API_KEY unset)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(prog="semantic_search_cli.py")
    parser.add_argument("query", help="Natural-language search topic")
    parser.add_argument("--limit", type=int, default=10, help="Max results (default 10)")
    args = parser.parse_args()

    if not (_ROOT / "chroma_db").exists():
        print(json.dumps({
            "error": "chroma_db/ not found — run the pipeline at least once to build the vector store.",
            "query": args.query, "count": 0, "results": [],
        }))
        sys.exit(1)

    try:
        from dotenv import load_dotenv
        load_dotenv(_ROOT / ".env")

        from news_buddy.rag import semantic_search
        results = semantic_search(args.query, n_results=args.limit)
        print(json.dumps({
            "query": args.query,
            "count": len(results),
            "results": results,
        }, ensure_ascii=False, indent=2))
    except RuntimeError as exc:
        print(json.dumps({"error": str(exc), "query": args.query, "count": 0, "results": []}))
        sys.exit(1)


if __name__ == "__main__":
    main()
