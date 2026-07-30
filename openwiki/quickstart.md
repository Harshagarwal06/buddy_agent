---
type: Documentation
title: News Buddy Wiki Quickstart
description: Entrypoint for the News Buddy codebase wiki. Explains the system's end-to-end behavior, major components, and how to navigate the documentation.
tags: [news-buddy, overview, navigation]
---

# News Buddy Wiki

News Buddy is a deterministic LangGraph pipeline that fetches AI news,
filters and deduplicates candidates, summarizes selected articles, generates
article-grounded explainers, writes a searchable archive, and optionally sends
Telegram, Slack, and Buttondown notifications.

The active behavior is implemented in
[`news_buddy/agent.py`](../news_buddy/agent.py) and invoked by
[`news_buddy/__main__.py`](../news_buddy/__main__.py). Source code,
configuration, tests, and workflows remain authoritative if this generated
wiki becomes stale.

## System boundaries

- [`news_buddy/`](../news_buddy/) is the digest application.
- [`news_buddy_mcp/`](../news_buddy_mcp/) is a separate read-only MCP server
  over the public JSON archive. It is not a LangGraph node.
- [`openwiki/`](.) is documentation only. The production pipeline never reads
  it.

## Navigation

- [LangGraph pipeline and CLI](architecture/langgraph-pipeline.md) — graph
  nodes, branches, state, and post-graph notification routing.
- [Feeds and article selection](processing/feed-and-article.md) — RSS
  normalization, deterministic AI filtering, URL deduplication, widening
  lookback, and ICYMI.
- [LLM and model providers](llm-and-models.md) — provider construction,
  summary JSON, image briefs, heuristic rubric scoring, and strict retry.
- [Image generation](image-generation.md) — required briefs, caching,
  provider calls, placeholders, and production failure policy.
- [Archive and deployment](archive-and-deployment.md) — Markdown, HTML, JSON,
  archive pages, and the `gh-pages` workflow.
- [Persistence and search](persistence.md) — SQLite seen state, local Chroma
  experiments, public JSON search, and the MCP service.
- [Notifications and operations](notifications-and-operations.md) — side-effect
  boundaries, run modes, scheduled backups, and recovery rules.
- [Testing and known gaps](testing-and-gaps.md) — validation commands,
  separately tested projects, and explicitly unimplemented work.

## Fast mental model

1. The graph fetches configured feeds concurrently.
2. It keeps trusted-source items or entries whose title/summary contains an AI
   keyword.
3. Normal production runs exclude URLs in repository-root `state.db`; the
   selection can widen its lookback and add explicitly marked ICYMI items.
4. `get_sub_model(config)` produces each summary and its image brief.
5. Pure-Python rubric heuristics score the summary and may trigger one stricter
   model retry.
6. Successful summaries can update URL state and optional local Chroma.
7. Images are generated or loaded from cache before the digest is formatted.
8. The graph writes Markdown, HTML, JSON search data, and archive navigation.
9. After the graph returns, the CLI decides whether to send notifications.
10. GitHub Actions separately copies the generated publication to `gh-pages`.

See [the pipeline page](architecture/langgraph-pipeline.md) for the exact graph
edges and [the operations page](notifications-and-operations.md) before running
anything with production side effects.
