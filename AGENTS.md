# News Buddy - Agent Instructions

This repository is a working daily AI news digest. It originally explored `deepagents`, but the current implementation is a deterministic LangGraph pipeline with LLM calls only for article summarization. Do not describe it as an active `deepagents` curator unless the code is changed back.

## Ground Truth

Start from these files for repo-specific answers:

- `news_buddy/agent.py` - graph nodes and pipeline behavior.
- `news_buddy/__main__.py` - CLI flags, notifications, and run output.
- `news_buddy/llm.py` - provider selection and model construction.
- `config.yaml` - feeds, filters, limits, and active LLM provider.
- `.github/workflows/daily-digest.yml` - scheduled run, test-run behavior, and deploy path.
- `news_buddy/buttondown_notify.py`, `telegram_notify.py`, `slack_notify.py` - notification behavior.
- `news_buddy/rag.py` and `news_buddy/semantic_search_cli.py` - semantic search implementation.

## Runtime Model

The graph flow is:

1. Fetch feeds in parallel.
2. Filter for AI stories.
3. Deduplicate against `state.db`.
4. Widen lookback and optionally add ICYMI items if too few stories remain.
5. Extract article bodies.
6. Summarize with `get_sub_model(config)`.
7. Apply the summary rubric and retry weak summaries once.
8. Mark URLs seen and optionally embed in Chroma.
9. Write Markdown, HTML, and archive files.
10. Let the CLI send notifications for non-empty successful digests.

`main_model` is currently unused by the graph. `sub_model` is the summarizer.

## Safety Rules

- Use `python -m news_buddy run --test-run --verbose` for live verification that must not mutate `state.db`, write RAG entries, deploy, or notify subscribers.
- Use `python -m news_buddy run --dry-run --verbose` when no network or file side effects are desired.
- Do not run a normal live digest just to test notifications unless the user explicitly asks for production side effects.
- Empty digests should stay quiet: no Telegram, Slack, or Buttondown sends.
- If diagnosing Buttondown, verify GitHub Actions logs and the final notification status, not only local code.

## Current Known Gaps

- Dedup is URL-based, not story-cluster based.
- CI disables RAG with `NEWS_BUDDY_RAG_ENABLED=false`.
- `state.db` is cached in Actions and may be lost if the cache is evicted.
- CI installs with `pip install .` despite the repo having `uv.lock`.
- Test coverage is still narrow around notification and archive paths.

## Preferred Next Steps

For portfolio/demo quality, prioritize:

1. Keep README and diagrams accurate.
2. Add story-level clustering using existing embeddings or title/summary similarity.
3. Persist RAG across CI runs and expose archive search/Q&A.
4. Add focused tests for feed parsing, dedup/backfill, rubric scoring, and HTML output.
5. Harden CI to install from the lockfile.
