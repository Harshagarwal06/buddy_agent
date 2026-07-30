---
type: Processing
title: Feed Fetching & Article Processing
description: RSS ingestion, AI filtering, URL deduplication, widening lookback, and ICYMI handling.
tags: [feeds, filtering, deduplication, backfill]
---

# Feed Fetching & Article Processing

Selection is deterministic until article summarization. Feed and selection code
lives in [`news_buddy/feeds.py`](../../news_buddy/feeds.py) and
[`news_buddy/agent.py`](../../news_buddy/agent.py); limits and source lists live
in [`config.yaml`](../../config.yaml).

## Feed Fetching

`fetch_feeds_node()` submits one `_fetch()` task per configured feed to a
`ThreadPoolExecutor`. Each task calls `fetch_feed_items()`:

- HTTP uses a 15-second default timeout, redirects, and a project user agent.
- `feedparser` parses RSS or Atom bytes.
- Entries without a parsed publish/update time are excluded.
- Entries older than the configured lookback are excluded.
- Each item is normalized to `source`, `title`, `url`, `published_at`, and
  cleaned `rss_summary`.
- A failing feed warns and contributes no items; other feed tasks continue.

Dry-run mode skips feed network calls and returns an empty list.

## AI Filtering

`_filter_ai_items()` does not call a model. It keeps an item when either:

- its `source` is in `trusted_ai_sources`; or
- its lowercased title plus RSS summary contains any configured
  `ai_keywords`.

When the keyword list is empty, every item passes.

## URL Deduplication

Within a single candidate list, `_dedupe_by_url()` removes blank and repeated
URLs. Across production runs,
[`news_buddy/state.py`](../../news_buddy/state.py) uses repository-root
`state.db`. The `seen` table contains `url`, `source`, `title`, and
`first_seen_at`.

`--force`, `--test-run`, and `--dry-run` bypass cross-run SQLite filtering.
Normal runs use `filter_unseen()`. After top-up, `max_articles` caps the list to
protect model quota.

## Widening lookback and ICYMI

If fewer than the configured target survive, `_top_up_min_articles()` doubles
the lookback from the base window until it reaches
`max_backfill_lookback_hours` or fills the target. Each pass:

1. Refetches feeds with `backfill_max_items_per_feed`.
2. Reapplies deterministic AI filtering and within-list URL deduplication.
3. Applies normal unseen filtering unless the run mode bypasses it.
4. Adds unique candidates until the target is reached.

If fresh unseen articles remain insufficient and `icymi_backfill` is enabled,
`_top_up_icymi()` performs one maximum-lookback fetch and intentionally selects
already-seen URLs. Those items gain `is_icymi: True`, which appears in digest
metadata. ICYMI is disabled for force, test, and dry runs.

Backfill can run whenever the result is below the target; it is not limited to
the zero-article case.

## Extraction and failure behavior

[`extract_body()`](../../news_buddy/extract.py) first uses Trafilatura, capped at
4,000 characters. Its fallback fetches the page with `httpx`, removes common
non-content elements, and joins substantial `<article>`/`<main>` paragraphs or
all paragraphs when needed. `_summarize_one()` falls back again to the RSS
summary when extraction is empty and sends at most 2,600 body characters to
the model.

The summary model must return a complete article image brief. A failed model
call or invalid brief produces a low-importance title/RSS fallback item, which
later causes required production image validation to stop publication instead
of silently generating a generic image.

## Related pages

- [LLM and model providers](../llm-and-models.md)
- [Persistence and search](../persistence.md)
- [Notifications and operations](../notifications-and-operations.md)
