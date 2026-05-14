# News Buddy — Component Plan

## Context

A "buddy agent" that runs once a day, reads news from a list of configured
websites, curates a summary tuned for the user, and writes it to a Markdown
file the user can open each morning. Goals:

- Low-touch: user only edits a feed list; the agent handles the rest.
- Trustworthy: deterministic fetch + dedup, with LLM only for summarization.
- Cheap to run: Claude Haiku/Sonnet with prompt caching; ~one API call per item
  plus one synthesis call per day.

Decisions locked in:
- Runtime: **Python**.
- Schedule: **Claude scheduled routine (`/schedule`)** that invokes the CLI daily.
- Output: **one Markdown file per day**, e.g. `~/news/2026-05-14.md`.
- Sources: **YAML config of RSS feeds** (RSS is far more robust than scraping).

Project location: `~/Documents/buddy_agent/`.

## Architecture at a glance

```
config.yaml ──► fetcher ──► extractor ──► dedup/state ──► summarizer ──► renderer ──► ~/news/YYYY-MM-DD.md
                (RSS)       (full text)   (SQLite)        (Claude API)   (Markdown)
                                                                ▲
                                                                │
                                                  Claude /schedule routine (daily)
```

## Components

### 1. Config (`config.yaml`)
- List of feeds: `name`, `url`, optional `weight`, optional `tags`.
- Global options: `output_dir`, `max_items_per_feed`, `lookback_hours` (default 24),
  `summary_style` (e.g. "concise, neutral, 2–3 sentences").
- Keeps source list editable without touching code.

### 2. Feed fetcher (`news_buddy/fetcher.py`)
- Use **`feedparser`** to parse RSS/Atom for each configured URL.
- Filter to items published within `lookback_hours`.
- Normalize to: `{source, title, url, published_at, rss_summary}`.
- Concurrent fetch with `httpx.AsyncClient` + a small semaphore.

### 3. Article extractor (`news_buddy/extractor.py`)
- For each item, GET the article URL and run **`trafilatura`** to get clean body
  text (drops nav, ads, comments).
- Truncate to N chars before sending to the LLM.
- Fall back to `rss_summary` on extraction failure; never block the pipeline on
  a single bad article.

### 4. State / dedup (`news_buddy/state.py`)
- **SQLite** at `~/Documents/buddy_agent/state.db`.
- Table `seen(url_hash PRIMARY KEY, first_seen_at, source, title)`.
- Skip items already digested so re-runs are safe and the daily file isn't
  padded with yesterday's content.

### 5. Summarizer (`news_buddy/summarizer.py`)
- Anthropic SDK (`anthropic` package). Default model: **`claude-haiku-4-5-20251001`**
  for per-article passes; **`claude-sonnet-4-6`** for the daily synthesis.
- Two passes:
  1. **Per-article**: input = title + extracted body → output = 2–3 sentence
     summary + 1–3 topic tags + importance score (1–5).
  2. **Daily synthesis**: input = all per-article summaries → output = Markdown
     digest grouped by theme, with "top stories" lead.
- **Prompt caching**: cache the system prompt (style guide + user preferences)
  across all per-article calls in a run. Cuts cost meaningfully on busy days.

### 6. Renderer (`news_buddy/renderer.py`)
- Writes `~/news/YYYY-MM-DD.md` with:
  - H1 date header
  - "Top stories" (3–5 cross-cutting picks from synthesis)
  - Themed sections (e.g. *AI*, *Markets*, *Geopolitics*) — themes come from
    summarizer tags
  - Per-item line: `**Title** — 2-line summary. *[source]* [link](url)`
- Atomic write: write to `.tmp` then `os.replace`.

### 7. CLI entry (`news_buddy/__main__.py`)
- One command: `python -m news_buddy run`
- Flags: `--config`, `--date` (override "today"), `--dry-run` (no API calls,
  print plan), `--force` (ignore dedup).
- Exit code 0 on success, non-zero with stderr detail on failure (so the
  scheduled routine can surface errors).

### 8. Daily trigger via `/schedule`
- A scheduled Claude routine fires each morning (user picks the time).
- The routine:
  1. `cd ~/Documents/buddy_agent && python -m news_buddy run`
  2. Reads the produced Markdown file
  3. (Optional) Sends a one-line `PushNotification` like "Today's digest: 12
     stories across 4 themes — ~/news/2026-05-14.md"
- The routine is a thin orchestrator; all logic lives in the Python CLI, so the
  user can also run it manually any time.

### 9. Project setup
- Layout:
  ```
  ~/Documents/buddy_agent/
    CLAUDE.md          # this plan
    pyproject.toml
    config.yaml
    news_buddy/
      __init__.py
      __main__.py
      fetcher.py
      extractor.py
      state.py
      summarizer.py
      renderer.py
    state.db           # gitignored
    .env               # ANTHROPIC_API_KEY
  ```
- Dependencies: `feedparser`, `trafilatura`, `httpx`, `pyyaml`, `anthropic`,
  `python-dotenv`.
- Output dir `~/news/` is created on first run.

## Files to be created (when we implement)

| Path | Purpose |
| --- | --- |
| `~/Documents/buddy_agent/pyproject.toml` | deps + entry point |
| `~/Documents/buddy_agent/config.yaml` | feed list + preferences |
| `~/Documents/buddy_agent/news_buddy/__main__.py` | CLI |
| `~/Documents/buddy_agent/news_buddy/fetcher.py` | RSS fetch |
| `~/Documents/buddy_agent/news_buddy/extractor.py` | article body extraction |
| `~/Documents/buddy_agent/news_buddy/state.py` | SQLite dedup |
| `~/Documents/buddy_agent/news_buddy/summarizer.py` | Claude calls + prompt caching |
| `~/Documents/buddy_agent/news_buddy/renderer.py` | Markdown writer |
| `~/Documents/buddy_agent/.env.example` | API key template |

## Verification (how we'll know it works)

1. **Dry run**: `python -m news_buddy run --dry-run --config config.yaml` prints
   the items it would summarize, exits 0, makes no API calls, writes no files.
2. **Live single source**: config with one feed (e.g. one tech blog) → run →
   inspect `~/news/$(date +%F).md`. Check: file exists, contains today's items,
   summaries read cleanly, links resolve.
3. **Dedup**: run twice in a row → second run produces an empty/short file
   (because everything was already seen).
4. **Scheduled routine**: invoke the `/schedule` routine on demand → confirm it
   runs the CLI, the file is produced, and the optional notification fires.
5. **Cost check**: after first real run, inspect the Anthropic dashboard to
   confirm cache hits on the per-article system prompt.

## Open questions to settle before we implement

- Which feeds go in the seed `config.yaml`? (5–15 to start.)
- What time of day should the scheduled routine fire?
- Push notification on completion, or quiet file write only?
- Default summary tone — "neutral wire-service" vs "analytical/opinionated"?
