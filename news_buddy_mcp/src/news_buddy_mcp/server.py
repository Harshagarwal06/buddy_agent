"""FastMCP server exposing read-only tools over the public digest archive."""

from __future__ import annotations

import os

from fastmcp import FastMCP

from news_buddy_mcp.index_client import ArchiveIndexClient


def _matches(record: dict, words: list[str]) -> bool:
    haystack = f"{record.get('title', '')} {record.get('summary', '')}".lower()
    return all(w in haystack for w in words)


def _search_articles(
    archive: ArchiveIndexClient,
    query: str,
    source: str | None,
    from_date: str | None,
    to_date: str | None,
    limit: int,
) -> dict:
    limit = max(1, min(limit, 100))
    words = [w.lower() for w in query.strip().split() if w]

    try:
        dates, stale = archive.manifest()
    except Exception as exc:
        return {"error": f"could not load archive manifest: {exc}"}

    dates = [d for d in dates if (not from_date or d >= from_date) and (not to_date or d <= to_date)]

    matches: list[dict] = []
    for date_str in dates:
        try:
            records, _ = archive.day(date_str)
        except Exception:
            continue
        if not records:
            continue
        for record in records:
            if source and source.lower() not in record.get("source", "").lower():
                continue
            if words and not _matches(record, words):
                continue
            matches.append({**record, "date": date_str})

    matches.sort(key=lambda r: r.get("importance", 3), reverse=True)
    truncated = len(matches) > limit
    return {
        "query": query,
        "count": min(len(matches), limit),
        "total_matches": len(matches),
        "truncated": truncated,
        "stale": stale,
        "results": matches[:limit],
    }


def _get_digest(archive: ArchiveIndexClient, date: str) -> dict:
    try:
        records, stale = archive.day(date)
    except Exception as exc:
        return {"error": f"could not load digest for {date}: {exc}"}

    if records is None:
        return {"error": f"no digest for {date}"}

    return {"date": date, "stale": stale, "count": len(records), "articles": records}


def _list_digests(archive: ArchiveIndexClient, limit: int) -> dict:
    limit = max(1, min(limit, 100))
    try:
        dates, stale = archive.manifest()
    except Exception as exc:
        return {"error": f"could not load archive manifest: {exc}"}

    entries = []
    for date_str in dates[:limit]:
        try:
            records, _ = archive.day(date_str)
        except Exception:
            records = None
        entries.append({"date": date_str, "article_count": len(records) if records else 0})

    return {"stale": stale, "count": len(entries), "digests": entries}


def create_server(archive: ArchiveIndexClient) -> FastMCP:
    mcp = FastMCP("News Buddy Archive")

    @mcp.tool()
    def search_articles(
        query: str,
        source: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 20,
    ) -> dict:
        """Keyword-search past digest articles by title and summary text.

        query: space-separated words, all must match (case-insensitive).
        source: optional source feed name filter (case-insensitive substring).
        from_date/to_date: optional YYYY-MM-DD bounds, inclusive.
        limit: max results to return (1-100).
        """
        return _search_articles(archive, query, source, from_date, to_date, limit)

    @mcp.tool()
    def get_digest(date: str) -> dict:
        """Return every article from the digest published on the given date (YYYY-MM-DD)."""
        return _get_digest(archive, date)

    @mcp.tool()
    def list_digests(limit: int = 30) -> dict:
        """List the most recent available digest dates with article counts."""
        return _list_digests(archive, limit)

    return mcp


def main() -> None:
    archive_url = os.environ["NEWS_BUDDY_ARCHIVE_URL"]
    port = int(os.environ.get("PORT", "8000"))
    server = create_server(ArchiveIndexClient(archive_url))
    server.run(transport="http", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
