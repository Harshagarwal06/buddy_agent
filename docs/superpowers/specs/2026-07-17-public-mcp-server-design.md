# Public News Buddy MCP Server — Design

**Date:** 2026-07-17
**Status:** Approved (design), pending implementation plan

## Goal

Let anyone connect a hosted, read-only MCP server to their Claude client and
query the News Buddy archive — search past digests, fetch a specific day, and
list recent digests. No installation, no credentials, no access to the
pipeline itself.

## Context

News Buddy already publishes a public archive to `gh-pages`
(`~/news/YYYY-MM-DD.html` + `index.html`, deployed by
`.github/workflows/daily-digest.yml`). That archive is the only thing this
server exposes. It does not touch `state.db`, `chroma_db/`, notification
credentials, or the pipeline's write path — all of which stay private and
local.

Two things were explicitly ruled out during design:

- **Exposing the pipeline as an MCP tool** (e.g. `run_digest`). The pipeline
  is a minutes-long batch job with side effects (marks articles seen, sends
  notifications) already handled well by scheduled GitHub Actions. MCP tools
  should be fast and safe to call repeatedly; a pipeline trigger is neither.
- **Semantic search in v1.** The Chroma store is local-only and
  `NEWS_BUDDY_RAG_ENABLED=false` in CI, so there is no published embedding
  index to search yet. This follows roadmap item #2 (persist RAG in CI) as a
  fast-follow, not part of this design.

The existing `news_buddy/search.py` was considered as a base for the search
tool and rejected: it queries the *private* `state.db`, which only stores
`url`, `source`, `title`, `first_seen_at` — no summaries, tags, or importance,
and it isn't published anywhere a hosted server could read it. The new index
described below is a distinct, public artifact built for this purpose.

## Components

### 1. `news_buddy/index_writer.py` (new)

Builds the public search index from data the pipeline already has at
`format_digest_node` time (`news_buddy/agent.py:480`, the `enriched_items`
list — title, url, source, published_at, summary, tags, importance).

- `write_index(output_dir: Path, date_str: str, enriched_items: list[dict]) -> Path`
  — writes `output_dir/YYYY-MM-DD.json`: a flat list of article records
  `{title, url, source, published_at, summary, tags, importance}`. Same
  atomic-write pattern as `_write_digest` (write to `.tmp`, then `replace`).
- `write_manifest(output_dir: Path) -> Path` — scans `output_dir` for
  `YYYY-MM-DD.json` files (same glob pattern used in `archive_writer.py`) and
  writes `output_dir/index.json`: `{"dates": ["2026-07-17", "2026-07-16", ...]}`,
  newest first. The MCP server uses this to know what's available without
  fetching every daily file up front.

### 2. `news_buddy/agent.py` (edit)

`write_html_node` (`news_buddy/agent.py:527`) gains two calls alongside its
existing `write_html` / `write_archive` calls:

```python
from news_buddy.index_writer import write_index, write_manifest
...
write_index(output_dir, date_str, state.get("enriched_items", []))
write_manifest(output_dir)
```

Empty-digest runs (`write_empty_node`) do not write an index file — nothing
to search, and `list_digests` already implies "no entry, no digest that day."

### 3. `.github/workflows/daily-digest.yml` (edit)

The deploy step (line 122) currently `cp`s only `${DATE}.html` into the
`gh-pages` staging directory before regenerating the HTML archive index.
Add the JSON file and manifest alongside it:

```bash
cp "${NEWS_DIR}/${DATE}.html" "${DEPLOY_DIR}/${DATE}.html"
cp "${NEWS_DIR}/${DATE}.json" "${DEPLOY_DIR}/${DATE}.json" 2>/dev/null || true
uv run python -c "from news_buddy.index_writer import write_manifest; from pathlib import Path; write_manifest(Path('${DEPLOY_DIR}'))"
uv run python -m news_buddy.archive_writer "$DEPLOY_DIR"
```

(The `|| true` covers empty-digest days, which have no JSON file.)

### 4. Backfill script: `scripts/backfill_index.py` (new)

One-off script, not part of the scheduled pipeline. Fetches each historical
`YYYY-MM-DD.html` from the live `gh-pages` archive and parses each article
card (`news_buddy/html_writer.py:44`, `_article_card`) for title/url
(`card-title` link), source + published date (`card-meta`), tags
(`data-tags` attribute), summary (`card-summary` paragraph text), and
importance (parsed from the `aria-label="Importance N of 5"` attribute — more
reliable than counting star characters). Writes the corresponding
`YYYY-MM-DD.json` + `index.json`, committed directly to `gh-pages`. If a
field is ever missing from an older page (e.g. `published_at` render
changes), the script leaves that field empty rather than fabricating a
value.

### 5. `news_buddy_mcp/` (new package)

A separate, small package — not part of `news_buddy`'s pyproject, since it
has a different deployment target and dependency footprint (just `fastmcp`
and an HTTP client).

- `server.py` — FastMCP app (streamable HTTP transport) exposing three tools:
  - `search_articles(query: str, source: str | None, from_date: str | None, to_date: str | None, limit: int = 20)`
    — loads the manifest, fetches the date-filtered set of daily JSON files
    (in-memory cache, see below), keyword-matches `query` against title +
    summary (AND logic across words, same semantics as `search.py`), ranks by
    match then `importance` descending, truncates to `limit` (max 100).
  - `get_digest(date: str)` — returns the full parsed record set for one day,
    or an explicit `{"error": "no digest for {date}"}` if the date isn't in
    the manifest.
  - `list_digests(limit: int = 30)` — most recent dates from the manifest,
    each with article count, so a client can discover what's queryable.
- `index_client.py` — fetches `index.json` and per-day JSON files from the
  configured archive base URL over HTTP, with an in-memory TTL cache (1 hour)
  keyed by date. On fetch failure, serves the last good cached copy and sets
  `"stale": true` on the response rather than failing the tool call.
- Config: one environment variable, `NEWS_BUDDY_ARCHIVE_URL` (the gh-pages
  base URL). No other configuration, no credentials.

### 6. Deployment

Containerized Python service (Dockerfile in `news_buddy_mcp/`), deployed to
whichever of FastMCP Cloud / Render / Fly.io has the best free-tier fit for a
low-traffic public tool — decided during implementation by checking current
tier limits, with Render as the fallback if FastMCP Cloud isn't suitable.
Public endpoint, unauthenticated, read-only. Whatever basic rate limiting the
chosen host provides is enough for v1; no custom rate limiting is built.

## Data flow

```
Daily pipeline run → format_digest_node (enriched_items)
    → write_html_node → write_index() + write_manifest() → ~/news/*.json
    → gh-pages deploy step → copies *.json + index.json alongside *.html

News Buddy MCP server (separate deploy) → on tool call:
    → index_client fetches index.json + relevant day(s) from gh-pages (cached)
    → search_articles / get_digest / list_digests → response to Claude client
```

Backfill (one-time, run once at implementation time):
```
scripts/backfill_index.py → reads existing gh-pages HTML pages
    → parses article metadata → writes historical *.json + index.json
    → commits to gh-pages directly
```

## Error handling

- Index fetch failure (network, 404, malformed JSON): serve cached data if
  available and mark the response `"stale": true`; if no cache exists yet,
  return a clear tool error rather than a partial/empty result presented as
  complete.
- `get_digest` for a date not in the manifest: explicit
  `{"error": "no digest for {date}"}`, not an empty list.
- Malformed per-day JSON (shouldn't happen, but the file is fetched over
  HTTP): skip that date, log it, continue serving the rest of the manifest.
- No write tools exist, so there's no failure mode to handle on that side.

## Testing

- Unit tests for `index_writer.write_index` / `write_manifest` against
  `enriched_items` fixtures. No test file exists yet for the sibling
  `html_writer`/`archive_writer` output path, so this is new coverage —
  a step toward roadmap item #3.
- Unit tests for `scripts/backfill_index.py`'s HTML parser against a couple
  of real archived digest pages saved as fixtures.
- Unit tests for each MCP tool handler (`search_articles`, `get_digest`,
  `list_digests`) against a fixture manifest + fixture daily JSON files, with
  `index_client` mocked — no network in tests.
- Manual verification: point a local run of the server at the real
  `NEWS_BUDDY_ARCHIVE_URL`, connect it from Claude Desktop/Code as a
  connector, and confirm all three tools return sensible results, including
  a `get_digest` call for a date that doesn't exist and a `search_articles`
  call with no matches.
- Manual verification after deploy: confirm the hosted URL is reachable and
  the connector works from a clean Claude client.

## Out of scope (YAGNI)

- Semantic/RAG search (depends on roadmap item #2, persisting RAG in CI).
- Any write tool (`run_digest`, marking articles, triggering notifications).
- Authentication, per-user state, or rate limiting beyond what the host
  provides.
- Publishing to a public MCP registry — this design covers hosting a working
  endpoint; a registry listing can follow once it's proven out.
- A public path for others to run their own News Buddy pipeline (rejected in
  the audience-scoping discussion; this design is query-only, over one
  curated archive).
