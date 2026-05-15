# News Buddy — Agent Plan (`deepagents` 0.6)

## Context

A daily news "buddy agent" built on **`langchain-ai/deepagents`** (v0.6, released
2026-05-13). The agent reads a configured list of RSS feeds, deduplicates against
prior runs, summarizes new articles, and writes a curated Markdown digest to
`~/news/YYYY-MM-DD.md`. A scheduled Claude routine invokes it once per day.

**Models**: starting with **local Ollama models** for both the curator and the
summarizer sub-agent. All LLM construction is centralized in a single
`llm.py` module so we can swap to Anthropic / OpenAI / a hosted provider later
by changing one file.

Why an agent instead of a deterministic pipeline:
- We get `write_todos` planning, sub-agent delegation, and auto-summarization
  for free from deepagents.
- The agent can adapt — e.g. skip a flaky feed, retry an extraction, group
  themes intelligently — without us coding every branch.
- Deterministic work (fetch, dedup, file write) still lives in **tools** so it
  stays predictable and cheap.

Project location: `~/Documents/buddy_agent/` (already a git repo, remote =
`https://github.com/manishbabel/buddy_agent`).

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  News Curator Agent (create_deep_agent)                         │
│   model: get_main_model() from llm.py  (Ollama: llama3.1:8b)    │
│   built-in tools: write_todos, ls, read_file, write_file, task  │
│   custom tools (see below)                                      │
│   sub-agent: article-summarizer                                 │
│     model: get_sub_model() from llm.py  (Ollama: llama3.2:3b)   │
└─────────────────────────────────────────────────────────────────┘
          │ tool calls
          ▼
┌────────────────────────────────────────────────────────────┐
│  Custom tools  (Python @tool functions in news_buddy/tools.py)  │
│   list_feeds()                → reads config.yaml          │
│   fetch_feed(name)            → RSS via feedparser         │
│   extract_article(url)        → trafilatura                │
│   filter_unseen(items)        → SQLite check               │
│   mark_seen(url, source, …)   → SQLite insert              │
│   save_digest(date, markdown) → atomic write to ~/news/    │
└────────────────────────────────────────────────────────────┘
          │
          ▼
   ~/news/YYYY-MM-DD.md   +   state.db (sqlite)
```

The Python entry point is thin: load config → build agent → invoke once with
"run today's curation job" → exit. All orchestration lives inside the agent.

## Components

### 1. Config (`config.yaml`)
- `feeds`: list of `{name, url, weight?, tags?}`
- Global options: `output_dir`, `max_items_per_feed`, `lookback_hours` (default 24),
  `summary_style`, `max_top_stories` (default 5)
- `llm` block (consumed by `llm.py`):
  ```yaml
  llm:
    provider: ollama
    base_url: http://localhost:11434
    main_model: llama3.1:8b      # tool-calling curator
    sub_model: llama3.2:3b       # summarizer sub-agent
    temperature: 0.2
  ```
- Loaded once at startup; exposed to the agent via the `list_feeds` tool.

### 1b. LLM module (`news_buddy/llm.py`)
- Single source of truth for LLM client construction.
- Starting with **Ollama** via `langchain-ollama`'s `ChatOllama`.
- Reads the `llm` block from `config.yaml`. Verifies the configured models exist
  at the Ollama server on first call; raises a clear error otherwise.
- Public API:
  - `get_main_model(config) -> BaseChatModel` — used by the curator agent.
  - `get_sub_model(config) -> BaseChatModel` — used by the article-summarizer
    sub-agent.
- Internal `_build_ollama(...)` factory; later we add `_build_anthropic(...)`,
  etc., and branch on `config.llm.provider`. Keeps the swap surface tiny.
- Note: Ollama must be running locally (`ollama serve`) and the configured
  models must be pulled (`ollama pull llama3.1:8b && ollama pull llama3.2:3b`).
  Document this in `.env.example` / README.

### 2. RSS helper (`news_buddy/feeds.py`)
- Pure functions — not tools themselves.
- `fetch_feed_items(url, lookback_hours) -> list[Item]` using `feedparser`.
- Async with `httpx.AsyncClient` + a small semaphore for concurrent feeds.
- Item dataclass: `source, title, url, published_at, rss_summary`.
- Used by the `fetch_feed` tool.

### 3. Article extractor (`news_buddy/extract.py`)
- `extract_body(url) -> str` using `trafilatura`.
- Truncate to N chars before returning.
- Returns `""` on failure; tool will fall back to RSS summary.
- Used by the `extract_article` tool.

### 4. State / dedup (`news_buddy/state.py`)
- SQLite at `~/Documents/buddy_agent/state.db`.
- Table: `seen(url_hash PRIMARY KEY, url, source, title, first_seen_at)`.
- Helpers: `ensure_schema()`, `is_seen(url)`, `mark_seen(item)`,
  `filter_unseen(items) -> list[Item]`.
- Used by the `filter_unseen` and `mark_seen` tools.

### 5. Tools (`news_buddy/tools.py`)
LangChain `@tool` decorators wrap the helpers above and the file writer.

```python
@tool
def list_feeds() -> list[dict]: ...
@tool
def fetch_feed(name: str) -> list[dict]: ...
@tool
def extract_article(url: str) -> str: ...
@tool
def filter_unseen(items: list[dict]) -> list[dict]: ...
@tool
def mark_seen(url: str, source: str, title: str) -> None: ...
@tool
def save_digest(date: str, markdown: str) -> str: ...   # returns the file path
```

Each tool returns JSON-friendly dicts so the agent can reason over them.

### 6. Sub-agent: `article-summarizer`
- Defined via the `subagents=[...]` param of `create_deep_agent`.
- Model: `anthropic:claude-haiku-4-5-20251001` (cheap, fast).
- Isolated context — the main agent calls it via the built-in `task` tool with
  a single article's `{title, url, body}`. It returns a structured summary:
  `{summary: str (2-3 sentences), tags: list[str], importance: 1-5}`.
- Keeps article bodies out of the curator's main context window.

### 7. Curator agent (`news_buddy/agent.py`)
- One `create_deep_agent(...)` call:
  - `model=get_main_model(config)`   # from llm.py
  - `tools=[list_feeds, fetch_feed, extract_article, filter_unseen, mark_seen, save_digest]`
  - `system_prompt=<contents of prompts/curator.md>`
  - `subagents=[{"name": "article-summarizer", "description": "...", "prompt": "...", "model": get_sub_model(config)}]`
- Returns a compiled LangGraph — exposed as `build_agent(config, dry_run, force)`
  in this module. No model strings inside this file — all provider-specific
  wiring lives in `llm.py`.

### 8. Prompts (`prompts/`)
- `prompts/curator.md` — system prompt for the main agent. Explains the daily
  job, output structure (top stories + themed sections), style, and the
  expectation to call `save_digest` exactly once at the end.
- `prompts/summarizer.md` — sub-agent system prompt with the JSON output
  contract.

### 9. CLI entry (`news_buddy/__main__.py`)
- Loads `.env`, parses flags, builds agent, invokes once.
- Flags: `--config` (path), `--date` (override "today"), `--dry-run`
  (substitute no-op tools that log instead of executing), `--force` (skip
  dedup), `--verbose` (stream tool calls to stderr).
- The invocation:
  ```python
  agent = build_agent(config, dry_run=args.dry_run, force=args.force)
  agent.invoke({"messages": [{"role": "user",
                              "content": f"Run the daily curation job for {date_str}."}]})
  ```

### 10. Daily trigger via `/schedule`
- A Claude scheduled routine fires each morning.
- Routine body: `cd ~/Documents/buddy_agent && uv run python -m news_buddy run`
  (or `python -m news_buddy run` if not using uv).
- On success, optionally `PushNotification` with the digest path + item count.

## File layout

```
~/Documents/buddy_agent/
  CLAUDE.md                  # this plan
  pyproject.toml             # deps + entry
  config.yaml                # feeds + preferences
  .env.example               # ANTHROPIC_API_KEY
  .gitignore                 # state.db, .env, __pycache__, .venv
  prompts/
    curator.md
    summarizer.md
  news_buddy/
    __init__.py
    __main__.py              # CLI
    agent.py                 # create_deep_agent wiring
    llm.py                   # LLM factories (Ollama first)
    tools.py                 # @tool definitions
    feeds.py                 # RSS helpers
    extract.py               # trafilatura helpers
    state.py                 # SQLite dedup
  state.db                   # created at runtime, gitignored
```

## Dependencies

- `deepagents` (≥0.6)
- `langchain` (for `@tool` decorator)
- `langchain-ollama` (Ollama chat model client)
- `feedparser`, `trafilatura`, `httpx`, `pyyaml`, `python-dotenv`

(Future provider additions: `langchain-anthropic`, `langchain-openai`. Add and
wire into `llm.py` when needed; nothing else changes.)

## External prerequisites

- **Ollama** running locally: `brew install ollama && ollama serve`
- Pull the default models:
  ```
  ollama pull llama3.1:8b
  ollama pull llama3.2:3b
  ```

## Verification

0. **Ollama reachable**: `curl http://localhost:11434/api/tags` lists the two
   configured models. `llm.py` raises a clear error if not.
1. **Dry run**: `python -m news_buddy run --dry-run` → agent runs, tools log
   intended actions but make no network/file calls; exits 0.
2. **Live single source**: trim `config.yaml` to one feed → real run with
   `ANTHROPIC_API_KEY` set → inspect `~/news/$(date +%F).md`. Verify file
   exists, today's items present, summaries read cleanly, links resolve.
3. **Dedup**: re-run immediately → second digest should be empty/short; `state.db`
   has all yesterday's URLs.
4. **Sub-agent isolation**: with `--verbose`, confirm article bodies appear in
   the summarizer sub-agent's traces but not in the curator's main thread.
5. **Scheduled routine**: invoke the `/schedule` routine on demand → file is
   produced and notification (if enabled) fires.
6. **Cost check**: after first real run, check Anthropic dashboard for
   reasonable token usage (sub-agent ≪ curator tokens because article bodies
   stay in the sub-agent).

## Open questions

- Seed `config.yaml` feed list (5–15 to start)?
- **Default Ollama models**: `llama3.1:8b` (curator) + `llama3.2:3b`
  (summarizer) — confirm these match what you have / want pulled? Alternatives
  with good tool-calling: `qwen2.5:7b`, `mistral-nemo`.
- Time of day for the `/schedule` routine?
- Push notification on completion, or quiet file write only?
- Default summary tone — neutral wire-service vs analytical?
- Do we want the agent to also write a `_history.jsonl` log of its tool calls
  per run, for later eval / debugging?
