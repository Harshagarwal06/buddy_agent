---
type: Architecture
title: Persistence & Search Surfaces
description: URL seen state, local Chroma semantic search, the public JSON index, and the separate read-only MCP server.
tags: [sqlite, chroma, search, mcp]
---

# Persistence & Search Surfaces

News Buddy has three persistence/search mechanisms with different lifetimes and
consumers. They are related by article URLs, but they are not one database.

| Surface | Storage | Writer | Reader | Current CI behavior |
| --- | --- | --- | --- | --- |
| Seen state | repository-root `state.db` | successful normal digest runs | deduplication and local search | restored/saved with Actions cache |
| Semantic index | repository-root `chroma_db/` | optional RAG embedding after summaries | local semantic search CLI/tools | disabled by `NEWS_BUDDY_RAG_ENABLED=false` |
| Public archive | dated JSON plus `index.json` on `gh-pages` | output/deploy writers | browsers and `news_buddy_mcp` | published with successful production issues |

## URL seen state

[`news_buddy/state.py`](../news_buddy/state.py) creates one SQLite table:
`seen(url PRIMARY KEY, source, title, first_seen_at)`. Normal runs filter
candidates with `filter_unseen()` and mark accepted summaries with
`mark_seen()`. Force, test, and dry runs do not use cross-run filtering or write
seen state.

This is URL deduplication, not story clustering. Two URLs covering the same
event can both be selected. The Actions cache is convenient rather than durable:
cache eviction can lose historical seen state.

## Local semantic search

[`news_buddy/rag.py`](../news_buddy/rag.py) uses a persistent Chroma collection
named `articles` and Google `models/gemini-embedding-2`. It uses distinct
retrieval-document and retrieval-query task types and requires
`GOOGLE_API_KEY`.

The graph embeds accepted articles only when RAG is enabled. Failures are
treated as warnings so an embedding outage does not block a digest. The daily
workflow currently disables this write path and does not persist `chroma_db/`,
so it remains a local/search experiment rather than the production archive
backend.

[`news_buddy/semantic_search_cli.py`](../news_buddy/semantic_search_cli.py)
provides semantic queries. [`news_buddy/search.py`](../news_buddy/search.py)
and the local topic-search skill combine archive-oriented lookup paths for
maintainer use.

## Public JSON and MCP

[`news_buddy/index_writer.py`](../news_buddy/index_writer.py) creates public
per-day JSON records and the date manifest. The sibling project
[`news_buddy_mcp/`](../news_buddy_mcp/) is a separate FastMCP application; it
is not imported into the LangGraph pipeline.

Its `ArchiveIndexClient` fetches the published JSON archive, caches responses
for a TTL, and can serve stale cached data when a later network request fails.
The server exposes three read-only tools:

- `search_articles` — case-insensitive word matching with optional source and
  date filters;
- `get_digest` — article records for a known date;
- `list_digests` — dates and article counts.

This MCP service performs keyword matching over public JSON. It does not query
Chroma, access `state.db`, summarize articles, mutate the archive, or expose
notification credentials.

## Related pages

- [Feeds and article selection](processing/feed-and-article.md)
- [Archive and deployment](archive-and-deployment.md)
- [Testing and known gaps](testing-and-gaps.md)
