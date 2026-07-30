# News Buddy - Agent Instructions

This repository is a working daily AI news digest. It originally explored `deepagents`, but the current implementation is a deterministic LangGraph pipeline with model calls for article summarization and editorial image generation. Do not describe it as an active `deepagents` curator unless the code is changed back.

## Ground Truth

Start from these files for repo-specific answers:

- `news_buddy/agent.py` - graph nodes and pipeline behavior.
- `news_buddy/__main__.py` - CLI flags, notifications, and run output.
- `news_buddy/llm.py` - provider selection and model construction.
- `news_buddy/image_generator.py` - article illustration generation, caching, and fallback behavior.
- `config.yaml` - feeds, filters, limits, and active LLM provider.
- `.github/workflows/daily-digest.yml` - scheduled run, test-run behavior, and deploy path.
- `news_buddy/buttondown_notify.py`, `telegram_notify.py`, `slack_notify.py` - notification behavior.
- `news_buddy/rag.py` and `news_buddy/semantic_search_cli.py` - semantic search implementation.

## Documentation Contract

- Source code, configuration, tests, and workflows are authoritative.
- `README.md` is the public introduction and setup guide.
- `AGENTS.md` contains repository-wide operating and safety rules.
- `CLAUDE.md` is a short tool-specific pointer back to these shared rules.
- `openwiki/` is generated, reviewable deep documentation. Treat it as a
  maintained knowledge cache, not as authority when it conflicts with code.
- `docs/superpowers/` contains historical plans and specifications; it does not
  prove that a feature is currently implemented.
- Update or regenerate the OpenWiki Code Brain after meaningful architecture,
  operations, provider, or deployment changes.

## Runtime Model

The graph flow is:

1. Fetch feeds in parallel.
2. Filter for AI stories.
3. Deduplicate against `state.db`.
4. Widen lookback and optionally add ICYMI items if too few stories remain.
5. Extract article bodies.
6. Summarize with `get_sub_model(config)` and create an article image brief.
7. Apply the summary rubric and retry weak summaries once.
8. Mark URLs seen and optionally embed in Chroma.
9. Generate cached article illustrations, with SVG fallbacks on provider failure.
10. Write Markdown, HTML, search-index, and archive files.
11. Let the CLI send notifications for non-empty successful digests.

`main_model` is currently unused by the graph. `sub_model` is the summarizer.

## Safety Rules

- Use `python -m news_buddy run --test-run --verbose` for live verification that must not mutate `state.db`, write RAG entries, deploy, or notify subscribers.
- Normal test runs also skip article image generation unless `images.generate_in_test_run` is explicitly enabled.
- Use `python -m news_buddy run --dry-run --verbose` when no network or file side effects are desired.
- Do not run a normal live digest just to test notifications unless the user explicitly asks for production side effects.
- The scheduled workflow has backup cron entries. Scheduled backups must keep the `gh-pages` preflight guard so late retries do not send duplicate notifications after today's digest is already published.
- Empty digests should stay quiet: no Telegram, Slack, or Buttondown sends.
- If diagnosing Buttondown, verify GitHub Actions logs and the final notification status, not only local code.

## Current Known Gaps

- Dedup is URL-based, not story-cluster based.
- CI disables RAG with `NEWS_BUDDY_RAG_ENABLED=false`.
- `state.db` is cached in Actions and may be lost if the cache is evicted.
- Coverage is still narrow around feed parsing, story selection/dedup/backfill,
  rubric edge cases, and some output/notification failure paths.

## Preferred Next Steps

For portfolio/demo quality, prioritize:

1. Keep README and diagrams accurate.
2. Add story-level clustering using existing embeddings or title/summary similarity.
3. Persist RAG across CI runs and expose archive search/Q&A.
4. Add focused tests for feed parsing, dedup/backfill, rubric scoring, and HTML output.

<!-- OPENWIKI:START -->

## OpenWiki

This repository uses OpenWiki for recurring code documentation. Start with
`openwiki/quickstart.md`, then follow its links to architecture, workflows,
domain concepts, operations, integrations, testing guidance, and source maps.

The scheduled OpenWiki GitHub Actions workflow proposes wiki updates in a draft
pull request. Review and correct generated claims against source before merge;
when an error is likely to recur, also tighten `openwiki/INSTRUCTIONS.md`.

<!-- OPENWIKI:END -->
