# News Buddy - Current Project Notes

News Buddy is now a deterministic LangGraph daily digest pipeline, not the original fully agentic `deepagents` prototype. Keep future work grounded in the code that exists today.

## Current Shape

The CLI entry point is `news_buddy/__main__.py`. The main runtime function is `run_pipeline()` in `news_buddy/agent.py`.

The graph currently runs:

1. `fetch_feeds_node` - fetch configured RSS feeds in parallel.
2. `filter_ai_node` - keep AI-relevant stories by trusted source and keyword matching.
3. `deduplicate_node` - remove URLs already present in `state.db`, then top up the article count with wider lookback windows and optional ICYMI repeats.
4. `summarize_articles_node` - extract article text and summarize each article with `get_sub_model(config)`.
5. `format_digest_node` - sort by importance and build Markdown.
6. `write_digest_node` - atomically write `~/news/YYYY-MM-DD.md`.
7. `write_html_node` - render the digest HTML and regenerate the archive index.
8. `write_empty_node` - write a short empty digest when nothing survives dedup.

Notifications are handled in the CLI after `run_pipeline()` returns, not inside the graph.

## Model Wiring

All provider construction lives in `news_buddy/llm.py`.

Supported providers:

- `huggingface` / `hf` via `huggingface_hub.InferenceClient`
- `google` via `langchain-google-genai`
- `ollama` via `langchain-ollama`

The current pipeline only calls `get_sub_model(config)` for article summaries. `main_model` remains in `config.yaml` for future compatibility but is not used by the active graph.

## State and Outputs

- Dedup state: `state.db` in the repo root.
- Digest output: `~/news/YYYY-MM-DD.md`.
- HTML output: `~/news/YYYY-MM-DD.html`.
- Archive index: `~/news/index.html`, later deployed to `gh-pages`.
- Optional Chroma vector store: `chroma_db/` in the repo root.

`--test-run` performs live fetching and summarization but skips marking articles seen, skips RAG writes, skips notifications, and skips deployment in the GitHub Actions workflow.

`--dry-run` is stricter: it avoids network and file side effects.

## Scheduled Workflow

`.github/workflows/daily-digest.yml` runs daily in GitHub Actions and can be triggered manually.

Important behavior:

- Scheduled runs send notifications only when the digest has at least one article.
- Manual workflow dispatch defaults to `test_run: true`.
- `NEWS_BUDDY_RAG_ENABLED` is currently set to `false` in CI, so RAG does not grow during the scheduled run.
- `state.db` is restored with `actions/cache`, which is convenient but not a permanent source of truth.
- The workflow installs with `pip install .`; lockfile-based installs are a future hardening step.

## Notification Channels

Configured from environment variables:

- Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- Slack: `SLACK_WEBHOOK_URL`
- Buttondown sending: `BUTTONDOWN_API_KEY`
- Buttondown archive signup form: `BUTTONDOWN_USERNAME`

Buttondown sends are intentionally skipped for empty digests and test runs.

## Development Priorities

High-impact next work:

1. Story-level clustering so duplicate coverage from multiple sources collapses into one story with multiple links.
2. Persist RAG in CI and expose archive Q&A/search from the web archive.
3. Replace `pip install .` in CI with lockfile-respecting installs.
4. Add tests for feed parsing, dedup/backfill, rubric scoring, and HTML generation.
5. Rebuild `state.db` from the published archive if Actions cache is missing.

When debugging digest or notification behavior, prefer evidence from the real workflow logs, `state.db`, generated `~/news` files, and notification adapter responses.
