# News Buddy — Complete Project Reference

Everything built and used in this project, in one document.

This is a descriptive inventory of the repository as it stands, derived from the
source, configuration, prompts, workflows, and tests. Where documentation and
code disagree, the code is authoritative (see the Documentation Contract in
`AGENTS.md`).

---

## Table of Contents

1. [What the project is](#1-what-the-project-is)
2. [Full technology inventory](#2-full-technology-inventory)
3. [Repository map](#3-repository-map)
4. [The LangGraph pipeline](#4-the-langgraph-pipeline)
5. [Feed ingestion layer](#5-feed-ingestion-layer)
6. [Article extraction layer](#6-article-extraction-layer)
7. [The LLM layer](#7-the-llm-layer)
8. [The prompt system](#8-the-prompt-system)
9. [The rubric (quality gate)](#9-the-rubric-quality-gate)
10. [Editorial image generation](#10-editorial-image-generation)
11. [Image-brief validation and repair](#11-image-brief-validation-and-repair)
12. [Persistence: SQLite, Chroma, OKF](#12-persistence-sqlite-chroma-okf)
13. [Search surfaces](#13-search-surfaces)
14. [The MCP server](#14-the-mcp-server)
15. [Publishing: Markdown, HTML, archive, design tokens](#15-publishing-markdown-html-archive-design-tokens)
16. [Notifications](#16-notifications)
17. [Observability](#17-observability)
18. [The model evaluation harness](#18-the-model-evaluation-harness)
19. [CI/CD and deployment](#19-cicd-and-deployment)
20. [Documentation system](#20-documentation-system)
21. [Agent tooling and skills](#21-agent-tooling-and-skills)
22. [Configuration reference](#22-configuration-reference)
23. [Run modes and safety semantics](#23-run-modes-and-safety-semantics)
24. [Test suite](#24-test-suite)
25. [Known gaps](#25-known-gaps)
26. [Project statistics](#26-project-statistics)

---

## 1. What the project is

**News Buddy** is a daily AI-news digest system. Every morning it fetches a set
of RSS/Atom feeds, filters them down to AI-relevant stories, deduplicates
against everything it has already covered, summarizes the survivors with an LLM,
plans and generates one editorial explainer illustration per story, renders a
Markdown digest plus a styled HTML page, publishes the page to a GitHub Pages
archive, and pushes the digest to Telegram, Slack, and an email subscriber list.

**Package name:** `news-buddy` (version 0.1.0)
**Python:** ≥ 3.11
**Console script:** `news-buddy` → `news_buddy.__main__:main`
**Live archive:** https://harshagarwal06.github.io/buddy_agent/

### Architectural history

The project started as a fully agentic `deepagents` experiment — an LLM curator
that called tools (`list_feeds`, `fetch_feed`, `filter_unseen`,
`extract_article`, `mark_seen`, `save_digest`) and delegated summarization to a
sub-agent. That original orchestration prompt survives at `prompts/curator.md`
as a historical artifact but is **not loaded by any running code path**.

The orchestration was deliberately moved to a **deterministic LangGraph
pipeline**. The reasoning: agentic orchestration was expensive and hard to debug
for a workflow whose control flow is actually fixed. LLM judgment is now
retained only where it genuinely adds value:

- article summarization,
- editorial importance scoring (1–5),
- article-specific image planning.

Everything else — fetching, filtering, dedup, ranking, rendering, publishing —
is plain deterministic Python. This is enforced as a repo-wide rule in
`AGENTS.md`, `CLAUDE.md`, and `openwiki/INSTRUCTIONS.md`: the running system must
never be described as an active `deepagents` curator. `scripts/validate_openwiki.py`
has an automated tripwire that fails the build if the word "deepagents" reaches a
generated documentation page.

---

## 2. Full technology inventory

### Core orchestration

| Technology | Where used | Purpose |
|---|---|---|
| **LangGraph** (`langgraph>=1.2.11`) | `news_buddy/agent.py` | `StateGraph` with a `TypedDict` state, 9 nodes, one conditional edge, compiled with a checkpointer |
| **LangGraph `MemorySaver`** | `agent.py:build_graph` | In-process checkpointer; thread id `"news-buddy"` |
| **LangChain Core** | `agent.py`, `llm.py` | `SystemMessage` / `HumanMessage` message types, `InMemoryRateLimiter` |
| **LangChain** (`langchain`) | dependency | Base runtime for the LangChain integrations |

### LLM providers (four, swappable)

| Provider | Config value | Implementation | Notes |
|---|---|---|---|
| **NVIDIA NIM** | `nvidia` | `_NvidiaChatModel` in `llm.py` — hand-written `httpx` adapter over the OpenAI-compatible endpoint | **Current production default**. Base URL `https://integrate.api.nvidia.com/v1` |
| **Google Gemini** | `google` | `langchain-google-genai` → `ChatGoogleGenerativeAI` | Supports true JSON mode via `response_mime_type` |
| **Hugging Face** | `huggingface` / `hf` | `_HuggingFaceChatModel` — adapter over `huggingface_hub.InferenceClient` | Routes through HF Inference Providers (`hf_provider: auto`) |
| **Ollama** | `ollama` | `langchain-ollama` → `ChatOllama` | Local models; pre-flight verified against `/api/tags` |

**Production summarizer model:** `meta/llama-3.1-8b-instruct` (NVIDIA NIM)

### Optional dependency extras

The NVIDIA pipeline is the minimal default install: a bare `pip install .`
brings only LangChain/LangGraph, feedparser, trafilatura, httpx, lxml, pillow,
pyyaml, python-dotenv, and tenacity. Because `config.yaml` ships with
`provider: nvidia` and the NVIDIA adapters are hand-written over `httpx`, the
production path needs no extra at all.

Everything else is opt-in, so an unused provider stack is never installed in
production:

| Extra | Installs | Needed for |
|---|---|---|
| `google` | `langchain-google-genai` | `llm.provider: google` |
| `huggingface` | `huggingface-hub` | `llm.provider: huggingface`, and the HF image provider |
| `ollama` | `langchain-ollama` | `llm.provider: ollama` |
| `rag` | `chromadb`, `langchain-google-genai` | `rag.py`, `semantic_search_cli.py`, `backfill_rag.py`, and the knowledge base |
| `observability` | `arize-phoenix-otel`, `openinference-instrumentation-langchain` | `OTEL_TRACING=true` |

```bash
pip install '.[google]'
pip install '.[huggingface]'
pip install '.[ollama]'
pip install '.[rag]'
pip install '.[observability]'
```

Two consequences worth knowing:

- The **full `arize-phoenix` UI package is no longer a dependency at all.** Only
  the OTel client remains, in the `observability` extra — the Phoenix collector
  is expected to be run separately. This is the single largest contributor to
  the reduced lockfile.
- The `rag` extra carries a **documented security caveat**. ChromaDB 1.5.9 has
  an unfixed pre-authentication server vulnerability
  ([PYSEC-2026-311](https://osv.dev/vulnerability/PYSEC-2026-311)) in an API
  path News Buddy does not use. Because the project only ever uses the
  in-process `PersistentClient`, the mitigation recorded in `SECURITY.md` is
  "do not expose a Chroma HTTP server from this environment" rather than a
  version bump.

The `dev` dependency group installs every extra, so the test suite exercises all
providers regardless of which extras a deployment selects.

**Version floors:** `langchain>=1.3.9`, `langgraph>=1.2.11`, `httpx>=0.28.1`,
with `ruff` pinned exactly to `0.15.22` in both packages.

### Image generation

| Technology | Purpose |
|---|---|
| **NVIDIA Visual GenAI / FLUX.2-klein-4B** (`black-forest-labs/flux.2-klein-4b`) | Text-to-image for editorial explainer illustrations |
| **Hugging Face `InferenceClient`** | Alternate image provider path |
| **Pillow (PIL)** | Image fitting/resizing (LANCZOS), WebP encoding, and the publisher-rendered label band (`ImageDraw`, `ImageFont`, `ImageOps`) |
| **Hand-written SVG** | Deterministic branded fallback when remote generation fails |

### Data, storage, and retrieval

| Technology | Purpose |
|---|---|
| **SQLite** (stdlib `sqlite3`) | `state.db` — cross-day URL dedup (`seen` table) |
| **ChromaDB** | Persistent local vector store at `chroma_db/`, collection `articles`, cosine space, HNSW index |
| **Google `models/gemini-embedding-2`** | Embeddings via `GoogleGenerativeAIEmbeddings`, with separate `retrieval_document` and `retrieval_query` task types |
| **OKF (Open Knowledge Format) 0.1** | Google Cloud's knowledge format; each accepted article is written as Markdown + YAML frontmatter before embedding |

### Content acquisition

| Technology | Purpose |
|---|---|
| **feedparser** | RSS/Atom parsing |
| **httpx** | All HTTP: feeds, LLM calls, image API, Telegram, Slack, Buttondown, MCP archive client |
| **trafilatura** | Primary full-text article body extraction |
| **lxml** | Fallback DOM-based paragraph extraction when trafilatura fails |

### Reliability

| Technology | Purpose |
|---|---|
| **tenacity** | `@retry` with exponential backoff (3 attempts, 2–30s) on every LLM invocation |
| **`InMemoryRateLimiter`** | Client-side RPM throttle across all hosted providers |
| **`ThreadPoolExecutor`** | Parallel feed fetching (one worker per feed), parallel summarization (5 workers), parallel image generation (configurable, capped 1–4) |

### Output and presentation

| Technology | Purpose |
|---|---|
| **Hand-written HTML generator** | `html_writer.py` / `archive_writer.py` — no template engine |
| **CSS custom properties in OKLCH** | `tokens.css` — shared design tokens, light + dark themes |
| **Newsreader + IBM Plex Sans** | Google Fonts typography pairing (display/body + UI) |
| **Vanilla JavaScript** | Theme toggle with `localStorage` persistence, desk/tag filtering, archive search |
| **Mermaid** | Architecture diagrams in `README.md`, `DIAGRAM.md`, and generated OpenWiki pages |

### Notifications

| Service | Implementation |
|---|---|
| **Telegram Bot API** | `telegram_notify.py` — Markdown→HTML conversion, 4096-char chunking |
| **Slack Incoming Webhooks** | `slack_notify.py` — Markdown→mrkdwn, Block Kit, 50-block batching |
| **Buttondown** | `buttondown_notify.py` — subscriber list, double opt-in, unsubscribe handling |

### Observability

| Technology | Purpose |
|---|---|
| **OpenTelemetry** | Trace protocol |
| **Arize Phoenix OTel client** (`arize-phoenix-otel`) | Sends traces to a separately run Phoenix collector, default `http://localhost:6006` |
| **OpenInference LangChain instrumentor** | Auto-instruments every LangChain LLM call |

### MCP

| Technology | Purpose |
|---|---|
| **FastMCP** (`fastmcp>=2.3`) | Standalone read-only MCP server over the public archive |
| **Docker** | `news_buddy_mcp/Dockerfile` — `python:3.11-slim`, uv-installed, HTTP transport on `$PORT` |

### Tooling and infrastructure

| Technology | Purpose |
|---|---|
| **uv** (`uv.lock`) | Dependency resolution and locked installs, both locally and in CI |
| **hatchling** | Build backend for both packages |
| **pytest** | 124 tests in the main package, 15 in the MCP package |
| **ruff** | Linting for both packages |
| **GitHub Actions** | Three workflows: daily digest, CI, OpenWiki update |
| **GitHub Pages** (`gh-pages` branch) | Public archive hosting |
| **PyYAML** | `config.yaml` loading, OKF frontmatter serialization |
| **python-dotenv** | `.env` loading |
| **OpenWiki 0.2.4** | Generated, reviewable maintainer documentation ("Code Brain") |
| **Node.js 22 + mermaid 11.16.0 + jsdom 29.1.1** | OpenWiki toolchain in CI |
| **Hallmark** | Design-critique metadata embedded in `tokens.css`, `html_writer.py`, and `prompts/image_style.md`; scan record at `.hallmark/preflight.json` |
| **Superpowers (SDD)** | Spec/plan/subagent-driven development workflow; artifacts under `.superpowers/sdd/` and `docs/superpowers/` |

---

## 3. Repository map

```
buddy_agent/
├── news_buddy/                    # Main package (22 modules, ~3,000 LOC)
│   ├── __main__.py                # CLI entry point, notification routing (205 lines)
│   ├── paths.py                   # Checkout/package resources + writable runtime roots
│   ├── agent.py                   # LangGraph pipeline — the core (864 lines)
│   ├── llm.py                     # Provider factory + 2 hand-written adapters (260)
│   ├── feeds.py                   # RSS/Atom fetch and normalization (65)
│   ├── extract.py                 # trafilatura + lxml fallback extraction (59)
│   ├── rubric.py                  # Heuristic summary quality scoring (151)
│   ├── image_generator.py         # Image planning, generation, caching, fallback (806)
│   ├── html_writer.py             # Dated digest HTML page generator (591)
│   ├── archive_writer.py          # Archive index page + email signup form (459)
│   ├── index_writer.py            # Public JSON search index + manifest (47)
│   ├── state.py                   # SQLite seen-URL dedup (53)
│   ├── knowledge_base.py          # OKF article file writer (54)
│   ├── rag.py                     # Chroma vector store + semantic search (116)
│   ├── backfill_rag.py            # One-time vector-store backfill from state.db (100)
│   ├── search.py                  # Keyword search CLI over state.db (162)
│   ├── semantic_search_cli.py     # Semantic search CLI over Chroma (52)
│   ├── telegram_notify.py         # Telegram delivery (112)
│   ├── slack_notify.py            # Slack delivery (110)
│   ├── buttondown_notify.py       # Email delivery (46)
│   └── observability.py           # Opt-in OTel/Phoenix tracing (29)
│
│   # Hatch bundles config.yaml, prompts/, tokens.css, and favicon.svg under
│   # news_buddy/resources/ in built wheels.
│
├── news_buddy_mcp/                # Separate MCP server package
│   ├── src/news_buddy_mcp/
│   │   ├── server.py              # FastMCP server, 3 read-only tools (133)
│   │   └── index_client.py        # Cached HTTP client over the public archive (65)
│   ├── tests/                     # 15 tests
│   ├── Dockerfile                 # python:3.11-slim + uv, HTTP transport
│   ├── pyproject.toml             # Independent dependency set
│   └── uv.lock                    # Independent lockfile
│
├── prompts/                       # LLM prompt contracts
│   ├── summarizer.md              # Summary + image-brief JSON schema (18)
│   ├── image_style.md             # The single visual contract (72)
│   ├── image_repair.md            # Image-plan repair prompt (18)
│   └── curator.md                 # Legacy deepagents prompt — NOT loaded (40)
│
├── scripts/                       # Offline tooling
│   ├── eval_sub_model.py          # Model evaluation runner + fixture capture (251)
│   ├── eval_scoring.py            # Pure scoring/aggregation functions (145)
│   ├── eval_report.py             # Markdown report rendering (114)
│   ├── eval_store.py              # Fixture store with SHA-256 manifest (91)
│   ├── eval_fixtures/
│   │   ├── manifest.json          # Committed: URLs + body hashes
│   │   └── articles.json          # Gitignored: third-party article bodies
│   ├── backfill_index.py          # Rebuild JSON index from published HTML (105)
│   └── validate_openwiki.py       # Dependency-free doc validator (227)
│
├── tests/                         # 124 tests, 19 files
├── openwiki/                      # Generated "Code Brain" documentation (12 pages)
├── docs/
│   ├── buttondown-setup.md
│   ├── rag-architecture.html
│   ├── evals/2026-07-30-sub-model-baseline.md
│   └── superpowers/{plans,specs}/ # 4 plans, 6 design specs
│
├── .github/workflows/
│   ├── daily-digest.yml           # Scheduled run + gh-pages deploy
│   ├── ci.yml                     # Lint + test, two jobs
│   └── openwiki-update.yml        # Weekly doc regeneration → draft PR
│
├── .agents/skills/topicsearch/    # Portable agent skill
├── .claude/skills/topicsearch/    # Claude Code copy of the same skill
├── .superpowers/sdd/              # SDD task briefs, reports, review diffs
├── .hallmark/                     # Design system scan + change log
│
├── config.yaml                    # Feeds, filters, limits, LLM + image settings
├── tokens.css                     # OKLCH design tokens, light + dark
├── favicon.svg
├── state.db                       # SQLite dedup (gitignored in principle)
├── chroma_db/                     # Vector store (gitignored)
├── pyproject.toml / uv.lock
├── README.md                      # Public introduction
├── AGENTS.md                      # Repo-wide agent operating rules
├── CLAUDE.md                      # Pointer to AGENTS.md
└── DIAGRAM.md                     # Node-level Mermaid flow diagrams
```

---

### Packaging and path resolution

**File:** `news_buddy/paths.py`

The project must work in two very different layouts: a **source checkout**,
where `config.yaml` and `prompts/` sit next to the package, and an **installed
wheel**, where they do not. Before this module existed, roughly ten modules
computed their own `Path(__file__).parent.parent`, which silently resolves to
`site-packages/` once installed. `paths.py` is the single place that decides.

Three functions, three distinct jobs:

| Function | Answers |
|---|---|
| `runtime_root()` | Where do I *write*? (`state.db`, `chroma_db/`, `knowledge_base/`, `.env`) |
| `resource_path(rel)` | Where do I *read* a shipped asset? (prompts, tokens.css, favicon.svg) |
| `default_config_path()` | Which `config.yaml` applies? |

**`runtime_root()`** resolves in priority order:

1. `NEWS_BUDDY_HOME` if set — an explicit, expanded, resolved path.
2. The source root, if `config.yaml` sits beside the package (checkout).
3. The current working directory (installed wheel).

**`resource_path()`** resolves in priority order:

1. The path itself, if already absolute.
2. The source root — so a checkout always overrides bundled copies, which is
   what keeps local prompt edits effective.
3. The runtime root.
4. `news_buddy/resources/` — the bundled fallback.

**Wheel bundling.** Hatch force-includes four assets into the wheel:

```toml
[tool.hatch.build.targets.wheel.force-include]
"config.yaml" = "news_buddy/resources/config.yaml"
"prompts"     = "news_buddy/resources/prompts"
"tokens.css"  = "news_buddy/resources/tokens.css"
"favicon.svg" = "news_buddy/resources/favicon.svg"
```

So an installed `news-buddy` has a working default configuration, the full
prompt set, and the design tokens needed to render a digest page — with no
checkout present.

**Modules converted:** `agent.py` (`_PROMPTS`, `_DB`), `__main__.py` (the
`--config` default and `.env` loading), `html_writer.py` and `archive_writer.py`
(`tokens.css`, `favicon.svg`), `image_generator.py` (the style guide, including
relative `style_guide` config values), `knowledge_base.py` (`_KB_PATH`),
`rag.py` (`_CHROMA_PATH`), `search.py`, `semantic_search_cli.py`, and
`backfill_rag.py`.

**Verified in CI, not just unit-tested.** Beyond the four tests in
`tests/test_paths.py`, the `test` job builds the wheel, installs it into a fresh
virtualenv, and runs `news-buddy run --dry-run --verbose` **from a temporary
directory**. That is the check that actually catches a resource path resolving
into `site-packages/`, because it runs with no checkout anywhere near the
working directory.

---

## 4. The LangGraph pipeline

**File:** `news_buddy/agent.py`

### Typed state — `DigestState`

A `TypedDict` carried through every node:

| Field | Type | Meaning |
|---|---|---|
| `config` | `dict` | The parsed `config.yaml` |
| `date_str` | `str` | ISO date for this digest |
| `dry_run` / `force` / `test_run` / `verbose` | `bool` | Run-mode flags |
| `raw_items` | `list[dict]` | All fetched articles (mutated in place by the filter node) |
| `unseen_items` | `list[dict]` | Survivors of dedup + backfill + cap |
| `enriched_items` | `list[dict]` | Post-summarization, post-image articles |
| `digest` | `str` | Final Markdown |
| `output_path` / `html_path` | `str` | Written file paths |
| `total_tokens` | `int` | Cumulative LLM tokens this run |
| `rubric_failures` | `int` | Summaries that failed quality scoring |
| `images_ready` / `image_failures` | `int` | Image outcome counters |

### The graph

```
                      fetch_feeds
                           ↓
                       filter_ai
                           ↓
                      deduplicate
                           ↓
                  ┌─ should_summarize ─┐   (conditional edge)
        unseen ≠ ∅│                    │unseen = ∅
                  ↓                    ↓
          summarize_articles      write_empty
                  ↓                    │
      generate_article_images          │
                  ↓                    │
            format_digest              │
                  ↓                    │
             write_digest              │
                  ↓                    │
                  └──→ write_html ←────┘
                           ↓
                          END
```

Entry point: `fetch_feeds`. Compiled with `MemorySaver()` when `checkpointing=True`.

### Node-by-node

**`fetch_feeds_node`**
Fetches every feed in `config.feeds` in parallel with a `ThreadPoolExecutor`
sized to the feed count. A failing feed logs a warning and returns `[]` — one
broken feed never aborts the run. Skipped entirely under `--dry-run`.

**`filter_ai_node`**
Two-mode filter. An item passes if **either**:
- its `source` is in `trusted_ai_sources` (the feed is already AI-scoped), **or**
- its title or RSS summary contains one of the 17 `ai_keywords` (case-insensitive).

**`deduplicate_node`**
1. Filters against `state.db` (skipped under `--force`, `--test-run`, `--dry-run`).
2. Runs `_top_up_min_articles` — the backfill ladder (below).
3. Hard-caps at `max_articles` to protect API quota.

**The backfill ladder.** If fewer than `min_articles` (8) survive, the pipeline
progressively widens its lookback window: `lookback_hours` doubles each round
(24 → 48 → 96 → 168) up to `max_backfill_lookback_hours`, refetching every feed
with a larger `backfill_max_items_per_feed` (25 instead of 10) and taking any
newly-discovered unseen items. If it *still* falls short and `icymi_backfill` is
true, `_top_up_icymi` deliberately re-includes articles that **were** already
seen, tagging them `is_icymi: True` so they render with a "From the archive"
badge. The digest would rather run short than repeat a story silently.

**`should_summarize`** — conditional edge. Routes to `summarize_articles` if
`unseen_items` is non-empty, otherwise to `write_empty`.

**`summarize_articles_node`**
The most complex node. Builds one `sub_llm` and processes articles across 5
worker threads. Per article, the nested failure ladder is:

1. `_summarize_one` — extract body, build prompt, call the model, parse JSON.
2. If the model returns a bad **image plan** → `IncompleteImageBrief` is raised.
   - If `images.brief_retry` is on, `_repair_image_brief` asks the model to fix
     *only* the image fields, keeping the accepted summary.
   - If repair also fails, `_without_image_brief` strips every `image_*` key and
     the article publishes **without an image** rather than being lost.
3. If the **rubric** fails and `rubric.retry_on_failure` is on, the article is
   re-summarized once with a `strict=True` prompt suffix that names exactly what
   was wrong. Only an improved result replaces the original.
4. Marks the URL seen and (if RAG is enabled) writes the OKF file and embeds it.
5. Any uncaught exception falls back to `{summary: rss_summary or title,
   tags: ["world"], importance: 2}` — the article still appears.

**`generate_article_images_node`**
Delegates to `image_generator.generate_article_images`. Skipped when images are
disabled, under `--dry-run`, and under `--test-run` unless
`images.generate_in_test_run` is explicitly true. If `images.require_all` is on
and any generation failed, it raises and stops publication.

**`format_digest_node`**
Sorts by `importance` descending. The top `max_top_stories` (5) go under
"Top Stories"; the remainder are grouped by their first tag into themed
sections. Emits Markdown.

**`write_digest_node`** — atomic write to `~/news/YYYY-MM-DD.md` via a `.tmp`
file and `Path.replace`.

**`write_html_node`** — the publishing node. It:
1. Scans `output_dir` for existing `YYYY-MM-DD.html` files to compute prev/next
   navigation links.
2. Calls `write_html` for the dated page.
3. Calls `write_index` for the day's JSON search record (skipped on empty days)
   and `write_manifest` to refresh `index.json` against whatever is on disk.
4. Calls `write_archive` to regenerate the archive landing page.

**`write_empty_node`** — writes a short "No new articles found." digest so the
archive stays continuous.

### Cross-cutting mechanisms in `agent.py`

**`SummarizationMiddleware`** — a hand-rolled middleware mirroring what
LangChain's `SummarizationMiddleware` does for agent message histories, adapted
for a single-turn pipeline. `before_invoke` estimates token count at ~4
chars/token; if the payload exceeds the 1,800-token budget, it parses the
`HumanMessage` JSON and truncates only the `body` field (never below 200 chars),
preserving title and URL. `after_invoke` logs actual token usage when
compression occurred.

**`_invoke_with_retry`** — tenacity `@retry`, 3 attempts, exponential backoff
2–30s, `reraise=True`. Wraps every model call including repairs.

**`_parse_json_object`** — tolerates markdown code fences by stripping any line
starting with ` ``` ` before `json.loads`. Returns `None` on failure, which
triggers the safe fallback dict.

**`_prompt_section`** — reads a delimited region out of a Markdown file using
HTML-comment markers. This is how the same prompt file serves both humans and
machines: `prompts/image_style.md` is a readable design document, but
`<!-- article-planner-directive:start/end -->` and
`<!-- image-model-directive:start/end -->` carve out the exact strings injected
into the summarizer prompt and the image request. Missing markers raise.

**`_rag_enabled()`** — reads `NEWS_BUDDY_RAG_ENABLED`, treating
`0/false/no/off` as disabled. CI sets this to `false`.

---

## 5. Feed ingestion layer

**File:** `news_buddy/feeds.py`

`fetch_feed_items(url, source_name, lookback_hours, max_items, timeout)` fetches
with `httpx` (15s timeout, redirects followed, custom `User-Agent`), parses with
`feedparser`, and normalizes each entry to:

```python
{"source", "title", "url", "published_at", "rss_summary"}
```

Two details worth noting:

- **Timezone correctness.** `feedparser` exposes `time.struct_time` in UTC. The
  code uses `calendar.timegm` rather than `time.mktime` — `mktime` would
  interpret the struct as local time and silently shift every timestamp.
- **HTML cleaning.** `_clean_html` strips tags, unescapes entities, and collapses
  whitespace so the RSS summary is usable as fallback body text.

Entries with no parseable date, or dated before the cutoff, are dropped.

### The 17 configured feeds

Vendor blogs: OpenAI News, Google AI Blog, NVIDIA Deep Learning Blog, Hugging
Face Blog, Apple ML Research, Berkeley AI Research.
Press: MIT Tech Review, The Verge AI, VentureBeat AI, TechCrunch AI, Ars
Technica, MarkTechPost.
Aggregators: Hacker News AI (`hnrss.org`), plus four Google News RSS searches
scoped to `when:1d` — general AI, OpenAI/ChatGPT, Anthropic/Claude, and
Gemini/DeepMind.

15 of the 17 are listed in `trusted_ai_sources` and bypass keyword filtering.

---

## 6. Article extraction layer

**File:** `news_buddy/extract.py`

A two-stage extractor with a hard 4,000-character cap:

1. **trafilatura** — `fetch_url` then `extract(include_comments=False,
   include_tables=False)`. This is the primary path.
2. **lxml fallback** — if trafilatura returns nothing, fetch with `httpx`, parse
   with `lxml.html`, strip `script/style/noscript/nav/footer/aside`, then try
   `//article//p | //main//p`. If that yields under 250 chars, fall back to all
   `//p`. Paragraphs under 40 chars are discarded as chrome.

If both fail, returns `""`. The summarizer then falls back to the RSS summary,
and the prompt instructs the model to state that only headline-level information
is known and set `importance: 2` — it must not invent detail to reach the word
target.

The body is further truncated to 2,600 chars before being sent to the model.

---

## 7. The LLM layer

**File:** `news_buddy/llm.py` — the single place any LLM client is constructed.

### Dispatch

`_build(config, model_key, json_mode)` reads `config.llm.provider` and routes to
one of four builders. Unknown providers raise a clear error naming the valid
values.

Public API:
- `get_sub_model(config)` — the summarizer. Always built with `json_mode=True`.
- `get_main_model(config)` — **currently unused by the graph.** Kept as a seam;
  `AGENTS.md` documents this explicitly so nobody assumes it is live.

### Missing-extra guards

Because three of the four providers now live behind optional extras, each
import site is wrapped so a missing package produces an actionable message
instead of a bare `ModuleNotFoundError`:

```python
try:
    from langchain_ollama import ChatOllama
except ModuleNotFoundError as exc:
    raise RuntimeError(
        "Ollama support is not installed. Run: pip install 'news-buddy[ollama]'"
    ) from exc
```

The same pattern guards `langchain_google_genai` in `_build_google` and
`huggingface_hub` in `_HuggingFaceChatModel.__init__`. Each preserves the
original exception via `from exc`. NVIDIA needs no guard — its adapter is
hand-written over `httpx`, which is a core dependency.

The imports remain **inside** the builder functions, so selecting one provider
never imports another provider's stack.

### Provider details

**NVIDIA (`_NvidiaChatModel`)** — a hand-written adapter, not a LangChain
integration. Posts to the OpenAI-compatible `/chat/completions` endpoint with
`model`, `messages`, `temperature`, `top_p`, `max_tokens`, `stream: false`.
Raises a helpful error pointing at https://build.nvidia.com/ when
`NVIDIA_API_KEY` is unset.

**Google (`_build_google`)** — `ChatGoogleGenerativeAI` with `max_retries=3` and
a rate limiter defaulting to 9 RPM (the free-tier cap). In `json_mode` it sets
`response_mime_type: application/json`, which forces genuinely raw JSON — no
code fences, no parse failures.

**Hugging Face (`_HuggingFaceChatModel`)** — wraps
`huggingface_hub.InferenceClient` with `provider` routing (default `auto`). In
`json_mode` it sets `response_format: {"type": "json_object"}`.

**Ollama (`_build_ollama`)** — pre-flight checks `GET {base_url}/api/tags` and
verifies the requested model is actually pulled, raising
`Run: ollama pull {model}` or `Run: ollama serve` rather than failing opaquely
mid-run.

### Shared plumbing

- **`_ChatResponse`** — a small frozen dataclass (`content`, `usage_metadata`)
  so the hand-written adapters are duck-type compatible with LangChain chat
  models from the pipeline's perspective.
- **`_to_hf_message`** — normalizes LangChain message types to OpenAI roles
  (`human`→`user`, `ai`→`assistant`, else `user`; `system` preserved).
- **`_usage_metadata`** — normalizes token accounting across providers,
  accepting both dict and attribute shapes and both `prompt_tokens`/`input_tokens`
  naming conventions.
- **Rate limiting** — every hosted provider gets an `InMemoryRateLimiter` at
  `requests_per_minute / 60` requests per second, `max_bucket_size=1`, checked
  every 0.5s. Production runs at 8 RPM.

---

## 8. The prompt system

Four prompt files, three of them live.

### `prompts/summarizer.md` (live)

Defines the strict JSON contract the summarizer must return:

- **`summary`** — a self-contained 3-sentence briefing of 70–110 words with a
  mandated structure: sentence 1 names the subject and what happened; sentence 2
  adds concrete context (mechanism, evidence, numbers); sentence 3 states the
  practical consequence, using only implications the article supports. Explicitly
  forbids opening with "The article", "This", "It", "They", "The company",
  "The deal", or any unnamed subject.
- **`tags`** — 1–3 from a closed vocabulary: technology, ai, science, world,
  business, politics, health, climate, security, culture.
- **`importance`** — integer 1–5.
- **Four image fields**, wrapped in `<!-- image-fields:start/end -->` markers so
  the repair prompt can re-inject only those definitions:
  `image_prompt`, `image_layout`, `image_labels`, `image_alt`.

### `prompts/image_style.md` (live)

The single visual contract for every article image — "the article changes; the
visual grammar does not." It specifies:

- **Fixed frame** — 1184×880 landscape, warm cream paper, exactly three object
  groups, thick charcoal linework, one muted brick-red or ochre accent, generous
  whitespace. The model draws wordless symbols; the *publisher* renders the
  numbered legend.
- **Article grounding** — reduce the article to Subject → Action/Change →
  Consequence; each object group and each label must map to one of those. Show
  the central mechanism, not the broad topic.
- **Layout vocabulary** — six named layouts: `pipeline`, `branching`,
  `comparison`, `before_after`, `bottleneck`, `layers`.
- **A four-question quality gate** — if any answer is "no", reject the brief.
- Two machine-extracted regions: the planner directive (injected into the
  summarizer system prompt) and the model directive (appended to every image
  request as "Visual direction").

The file carries a Hallmark pre-emit critique header (`P5 H5 E5 S5 R5 V4`).

### `prompts/image_repair.md` (live)

Used only on the repair path. Receives `{title, summary, rejected, problems}`,
must fix every field named in `problems`, must not repeat rejected values, must
stay grounded in the supplied summary, and must return only the four image keys
as raw JSON.

### `prompts/curator.md` (legacy)

The original `deepagents` orchestration prompt — tool workflow, digest structure,
style rules. Retained as a historical artifact. **No code path loads it.**

---

## 9. The rubric (quality gate)

**File:** `news_buddy/rubric.py` — `RubricMiddleware`

Pure heuristics, **zero LLM calls**. This is deliberate: a cheap deterministic
gate that catches malformed or lazy summaries before they reach readers.

### Four scored dimensions

| Dimension | Range | How it's measured |
|---|---|---|
| **specificity** | 1–3 | `3 − (count of vague phrases)`, floored at 1 |
| **completeness** | 1–3 | Character length, word count, and sentence count thresholds |
| **context** | 1–3 | Whether the summary opens with a thin pronoun, and whether it shares meaningful vocabulary with the title |
| **tag_quality** | 0–1 | Whether any tag is non-generic (not `world`/`other`/empty) |

**Pass condition:** `specificity ≥ 2 AND completeness ≥ 2 AND context ≥ 2`.
`tag_quality` is recorded but does not gate.

### The eight vague phrases

"new development", "according to reports", "it was reported", "sources say",
"has been announced", "significant implications", "could change the landscape",
"marks a major step".

### The ten thin openers

`it`, `this`, `they`, `he`, `she`, `his`, `her`, `the company`,
`the organization`, `the decision`, `the deal`.

### Subject coverage

`_covers_title_subject` extracts title words ≥ 4 characters, drops 15
stopwords (`about`, `after`, `against`, `from`, `into`, `over`, `that`, `their`,
`this`, `through`, `under`, `with`, `will`, `your`, …), and requires at least one
to appear in the summary. Word tokenization normalizes curly apostrophes and
strips possessive `'s`.

### Consequences

- **Fail** → `importance` drops by `importance_penalty` (2), floored at 1, and a
  strict retry fires if enabled.
- **Barely pass** (all three dimensions exactly 2) → `importance` drops by 1. A
  mediocre summary should not lead the digest.

The full rubric block (all scores, word count, sentence count, `passed`) is
attached to the enriched item for downstream inspection.

Production thresholds: `min_summary_length: 200`, `min_summary_words: 65`.

---

## 10. Editorial image generation

**File:** `news_buddy/image_generator.py` (806 lines — the second-largest module)

### `ImageSettings`

A frozen dataclass built from the `images` config block, with **defensive
clamping on every numeric field**: width ≥ 320, height ≥ 240, quality 1–100,
`max_workers` 1–4, timeout ≥ 10s, retries 0–5, retry delay 0–30s, steps 1–50.
A bad config value degrades rather than crashing.

### Prompt construction

`_visual_prompt(item)` builds the request from the model's `image_prompt`
(truncated to 280 chars), plus a layout direction, plus an explicit instruction
that all three object groups stay **unlabeled** because the publisher adds the
legend. `_request_prompt` appends the style directive and truncates the whole
thing to 800 characters.

`_LAYOUT_DIRECTIONS` maps each of the six layout names to a concrete drawing
instruction ("Arrange the three stages left to right with bold directional
arrows", "Show several inputs narrowing through one constrained gate", …).
If the model supplies an unknown layout, `_layout_direction` infers one from
article text keywords.

### The content-filter fallback path

The image provider sometimes refuses a prompt — usually because it names a real
company or person. `_safe_infographic_concept` holds a 17-entry keyword→concept
table mapping article topics to **name-free, brand-free** visual descriptions.
For example, an article about shared chats leaking into search becomes "a sealed
speech bubble passing through an open chain-link gate into a magnifying glass
over public nodes". `_fallback_labels` provides a matching 17-entry
keyword→label-triad table.

`ImageContentFilteredError` exists because NVIDIA returns **HTTP 200** with
`finishReason: "CONTENT_FILTERED"` — a success status for a refusal. Without
explicit detection, this would decode as an empty artifact and produce a
confusing error. On this exception the generator swaps in the neutral prompt and
retries.

### Label rendering — the publisher's job, not the model's

Image models cannot reliably render text. So the pipeline generates a **wordless**
illustration and composites the legend itself:

`_add_label_band` (Pillow) crops the generated art to remove any band where the
model may have hallucinated captions, whitens near-white pixels to the cream
paper color so the art blends with the band, then draws:
- three numbered accent circles at width/6, width/2, width×5/6,
- the three labels in DejaVu Sans Bold (with a graceful `load_default` fallback),
- accent arrows with polygon arrowheads between the circles.

`_image_labels` sanitizes each label through a regex that keeps only
`[A-Za-z0-9 +/&-]`, fits to at most 3 words and 18 characters, deduplicates
case-insensitively, and upper-cases. Over-long labels are trimmed rather than
rejected — a fix made in commit `746dcd1` after long labels killed a digest.

### Caching

`_cache_stem` hashes URL/title + prompt + model + provider + style version +
style text + labels into a 20-char SHA-256 prefix. Any change to the visual
contract (bumping `style_version`, currently `explainer-v10`) invalidates the
entire cache. The safe-prompt variant gets its own cache key and is checked
before making a network call. Images are stored as WebP at quality 82,
method 6, written atomically via `.tmp` + `replace`.

### Retry and failure semantics

`_is_retryable_request_error` retries everything **except** 4xx errors, with
`408`, `409`, `425`, and `429` explicitly carved out as retryable. There is no
point retrying a 400.

`_validate_image` opens the returned bytes with Pillow and calls `verify()` —
catching empty or malformed payloads while retries are still available.

On total failure, `_placeholder_svg` writes a deterministic branded SVG:
cream background, coral circle, blue rectangle, ochre triangle, the tag name,
and the article title wrapped to 3 lines of 34 chars.

### Publication gates

Three commits in the git history are specifically about not letting image
problems destroy a digest:

- `require_article_brief: true` — if **every** article has an invalid brief,
  that's a prompt or model regression worth stopping for, and it raises. If only
  **some** do, those articles publish imageless with a warning (commit `8eed72e`).
- Deliberate skips return `failed=False` so they don't trip `require_all`.
- `require_all: false` in production — a provider rejection must not suppress a
  complete digest (commits `746dcd1`, `44c320d`).

---

## 11. Image-brief validation and repair

### `_article_brief_errors(item)`

Returns a list of error codes for an unpublishable image plan:

| Code | Condition |
|---|---|
| `image_prompt` | Empty |
| `image_layout` | Not one of the six approved layouts |
| `image_labels` | Not a list of exactly 3 non-empty strings |
| `article-specific image_labels` | Labels are literally `["input", "system", "result"]` |
| `image_alt` | Empty |

That fourth check is the interesting one. The style guide explicitly forbids
defaulting to INPUT → SYSTEM → RESULT, so a model producing that triad has
ignored the grounding requirement even though the output is structurally valid.

### `IncompleteImageBrief`

A custom `ValueError` carrying `errors`, the parsed `item`, and `tokens`. The
exception message wording is a **documented contract** — `scripts/eval_sub_model`
parses it to score brief validity, so the docstring states it must not be
reworded.

Crucially, it carries the item: the summary is usually fine even when the image
plan is not, so the caller can keep one and drop the other.

### The repair loop

`describe_brief_errors` translates each error code into a plain-English
objection ("image_labels used the generic INPUT / SYSTEM / RESULT triad. Use
concrete nouns taken from this specific story instead."). The rationale, stated
in the source: the model already had the rules and broke them anyway — naming
the specific objection is what makes a retry worth doing.

`_repair_image_brief` sends the repair prompt plus the field definitions
(extracted from `summarizer.md` via markers) plus the planner directive
(extracted from `image_style.md`), along with the rejected values and the
problems. It merges only the four image keys back over the accepted item and
re-validates. Still invalid → raise again → publish imageless.

This was added in `#12` / commit `76b84da`.

---

## 12. Persistence: SQLite, Chroma, OKF

### SQLite — `news_buddy/state.py`

One table:

```sql
CREATE TABLE IF NOT EXISTS seen (
    url           TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    title         TEXT NOT NULL,
    first_seen_at TEXT NOT NULL
)
```

API: `ensure_schema`, `is_seen`, `filter_unseen` (single batched `IN` query),
`mark_seen` (`INSERT OR IGNORE`). Every function calls `ensure_schema` first, so
a missing database self-heals. Timestamps are UTC ISO 8601.

### OKF knowledge base — `news_buddy/knowledge_base.py`

Before an article is embedded, it is written once as a Markdown file following
**Google Cloud's Open Knowledge Format (OKF), `okf_version 0.1`**, at
`runtime_root() / "knowledge_base" / "articles" / f"{sha256(url)[:16]}.md"`:

```markdown
---
type: Article
title: ...
description: <first sentence of the summary>
resource: <url>
tags: [...]
timestamp: <published_at>
source: <feed name>
---

## Summary

<full summary>
```

This file — not the raw article body — is the source of truth for what gets
embedded. The directory is gitignored, mirroring `chroma_db/`.

This was introduced across commits `732555f` → `bb35b53` (design spec at
`docs/superpowers/specs/2026-07-31-okf-article-knowledge-base-design.md`).

### Chroma vector store — `news_buddy/rag.py`

- The whole module is guarded by a single module-level `try`/`except
  ModuleNotFoundError` that raises
  `"RAG support is not installed. Run: pip install 'news-buddy[rag]'"`. Unlike
  the provider guards this sits at import time, because Chroma and the embedder
  are used throughout the module rather than in one builder.
- `chromadb.PersistentClient` at `runtime_root() / "chroma_db"`, collection `articles`,
  `{"hnsw:space": "cosine"}`.
- **Two separate embedders**, both `models/gemini-embedding-2`: one with
  `task_type="retrieval_document"` for indexing, one with
  `task_type="retrieval_query"` for search. Asymmetric embedding measurably
  improves retrieval quality over using one model for both sides.
- `embed_article` is idempotent — it checks `collection.get(ids=[url])` first
  and no-ops if already indexed. It writes the OKF file, then embeds
  `f"{title}\n\n{summary}"` (title alone if the summary is empty).
- `semantic_search` returns title, source, URL, and `similarity = 1 − distance`
  rounded to 3 places.
- Module-level singletons for the collection and both embedders.

### `news_buddy/backfill_rag.py`

A one-time migration for articles marked seen *before* RAG existed. Walks every
row of `state.db.seen` and embeds it title-only. Paces at 0.7s between calls
(~85/min, under Google's ~100/min free tier) and retries `RESOURCE_EXHAUSTED`
up to 5 times with escalating 30s/60s/90s… backoff. Safe to re-run because
`embed_article` skips already-indexed URLs.

---

## 13. Search surfaces

The project has **four distinct search surfaces**, deliberately separated.

### 1. Keyword search over `state.db` — `news_buddy/search.py`

```bash
python news_buddy/search.py "AI chips" --source "VentureBeat" --limit 10
```

Every word in the query must appear in the title (AND logic via chained
`title LIKE ?`). Optional source substring filter. Returns JSON with `query`,
`source_filter`, `limit`, `total_matches`, `truncated`, `count`, `results`.
Documented exit codes: `0` success (including zero results), `1` DB/schema
error, `2` bad arguments. Errors are emitted as JSON on stdout so a calling
agent never has to parse a traceback.

### 2. Semantic search over Chroma — `news_buddy/semantic_search_cli.py`

```bash
python news_buddy/semantic_search_cli.py "AI chip capacity" --limit 10
```

Checks `chroma_db/` exists before importing anything, loads `.env`, and returns
JSON results with similarity scores. Same JSON-error discipline.

### 3. Public JSON index — `news_buddy/index_writer.py`

Two artifacts published alongside the HTML:

- **`YYYY-MM-DD.json`** — one record per article: title, url, source,
  `published_at` (truncated to 10 chars / `YYYY-MM-DD`), summary, tags,
  importance, image_url, image_alt.
- **`index.json`** — `{"dates": [...]}` newest-first, rebuilt by scanning the
  output directory for `YYYY-MM-DD.json` files. Because it scans disk rather
  than tracking state, it self-heals.

Both written atomically.

`scripts/backfill_index.py` reconstructs these from already-published HTML by
regex-parsing the archive `index.html` for dated links and each digest page for
`<article class="article-card">` blocks. This is why `html_writer._article_card`
carries the comment "preserving markup consumed by the backfill parser" — the
HTML structure is a contract.

### 4. The MCP server (next section).

### Combining surfaces: the `topicsearch` skill

`.agents/skills/topicsearch/SKILL.md` (mirrored at
`.claude/skills/topicsearch/SKILL.md`) is a packaged agent skill that runs the
keyword and semantic CLIs **in parallel**, merges and deduplicates by URL, marks
each result `[keyword]` / `[semantic]` / `[both]`, sorts (both-matches first,
then semantic by similarity, then keyword by recency), and synthesizes a
"Topic Briefing" with a landscape paragraph, a results table, and a
"What to Read First" recommendation. It specifies handling for every edge case:
zero results, missing `chroma_db`, truncated results, uninitialized DB.

---

## 14. The MCP server

**Package:** `news_buddy_mcp/` — a fully separate Python package with its own
`pyproject.toml`, `uv.lock`, tests, lint, Dockerfile, and CI job.

It reads **only the public JSON archive** on `gh-pages`. It never touches
`state.db` or Chroma. That isolation is the point: the archive is already
public, so the server exposes nothing private and needs no credentials.

### `ArchiveIndexClient`

An HTTP client with a 1-hour in-memory TTL cache. Its failure policy is
explicit: on fetch failure, serve the last good cached copy and **mark it
stale**; if there is no cache yet, let the original error propagate. `404` on a
day file returns `(None, False)` — a missing digest is a legitimate answer, not
an error.

### Three read-only FastMCP tools

| Tool | Signature | Behavior |
|---|---|---|
| `search_articles` | `query, source?, from_date?, to_date?, limit=20` | All query words must match title+summary (case-insensitive). Optional source substring and inclusive date bounds. Results sorted by importance. Limit clamped 1–100. |
| `get_digest` | `date` | Every article from one `YYYY-MM-DD` digest |
| `list_digests` | `limit=30` | Recent digest dates with article counts |

Every response carries a `stale` flag so the consuming LLM knows whether it is
reading cached data. Every failure path returns `{"error": ...}` rather than
raising — an MCP client gets a usable message.

### Deployment

```bash
cd news_buddy_mcp
uv sync
NEWS_BUDDY_ARCHIVE_URL=https://harshagarwal06.github.io/buddy_agent \
  uv run python -m news_buddy_mcp.server
```

Or via Docker: `python:3.11-slim`, `uv sync --frozen --no-dev`, HTTP transport
bound to `0.0.0.0:$PORT` (default 8000).

Built across commits `5984185` → `993c642`; design spec at
`docs/superpowers/specs/2026-07-17-public-mcp-server-design.md`.

---

## 15. Publishing: Markdown, HTML, archive, design tokens

### Markdown digest

```markdown
# News Digest — YYYY-MM-DD

## Top Stories
### [Title](url)
*Source · YYYY-MM-DD · ICYMI*

Summary.

## Technology        ← themed sections for the remainder, grouped by first tag
...
```

### HTML digest — `news_buddy/html_writer.py`

A hand-written generator (no template engine) producing a complete editorial
page:

- **Theme** — an inline script runs *before* paint, reading `localStorage`
  (`nb-theme`) and falling back to `prefers-color-scheme`, setting
  `data-theme` on `<html>`. This avoids a flash of the wrong theme.
- **Card hierarchy** — `card-hero` (first story, `loading="eager"`,
  `fetchpriority="high"`), `card-large` (stories 2–5), `card-normal` (rest,
  `loading="lazy"`).
- **Importance labels** — 5 = "Lead story", 4 = "Must read", 3 = "Recommended",
  ≤2 = "Briefing", with a `card-stars-quiet` class below 3.
- **Desk filtering** — a `filter-bar` of tag buttons with `aria-pressed`, plus a
  `sr-only` `aria-live="polite"` status region announcing the visible count.
  Rendered only when there is more than one tag.
- **Adaptive copy** — with a single tag, the section reads "More stories /
  N additional stories"; with several, it reads "{Tag} / N items in this desk".
- **Reading time** — computed at 220 WPM from summary word counts.
- **Source stats** — per-source article counts sorted descending.
- **Prev/next navigation** — computed in `write_html_node` by listing existing
  dated HTML files; disabled states render as non-link spans.
- **Empty state** — a dedicated section pointing back at the archive.
- **Accessibility** — `alt` on every image, explicit `width`/`height` (no layout
  shift), `decoding="async"`, `<time datetime>` elements, `aria-hidden` on
  decorative arrows and separators, `aria-label` on importance.

### Archive index — `news_buddy/archive_writer.py`

Regenerated on every run. It parses each published digest HTML with best-effort
regexes to recover the article count and up to 4 tags, then renders one
`day-row` per date with a `data-search` attribute powering client-side
filtering. The newest date gets a "Latest issue" label.

It also renders a **Buttondown email signup form**, but only when
`BUTTONDOWN_USERNAME` is set — otherwise the form is omitted entirely rather
than rendering broken.

Runnable standalone: `python -m news_buddy.archive_writer <dir>` — this is how
the deploy workflow rebuilds the index inside the `gh-pages` checkout.

### Design tokens — `tokens.css`

A shared token file copied next to every generated page (along with
`favicon.svg`). All colors are **OKLCH**. Tokens cover paper/ink/muted/rule/
accent/focus/error/selection colors, the Newsreader + IBM Plex Sans font stacks,
a named type scale (`--text-2xs` through `--text-xl`+), and a named spacing
scale. Light and dark palettes both defined.

The file carries a Hallmark provenance header recording macrostructure
(Long Document), tone (editorial), theme (studied-DNA), and passing checks for
contrast, slop, honesty, chrome, tokens, responsiveness, icons, and mobile.
`.hallmark/preflight.json` records the design scan: Python-generated static HTML,
vanilla JS (no motion library), GitHub Pages deployment, and six preserved
behaviors (dated routes, archive navigation, topic filters, light/dark themes,
article images, source links).

---

## 16. Notifications

All three run from the **CLI after the graph completes** — they are not graph
nodes. All three are best-effort: they log and return `False` rather than
raising, so a notification failure never breaks publication.

**Empty digests stay quiet.** No Telegram, no Slack, no email when
`item_count == 0`. This is a stated safety rule in `AGENTS.md`.

### Telegram — `telegram_notify.py`

Converts digest Markdown to Telegram-safe HTML (`### [T](u)` → bold link,
`##` → bold, `#` → bold+underline, `*x*` → italic), chunks to the 4,096-char
limit splitting at the last newline before the boundary, and appends
"Part i of N" when multi-chunk. Header line carries article count, duration,
token count, and estimated cost. `send_error_alert` posts failures as
`<code>`-wrapped text.

### Slack — `slack_notify.py`

Converts to mrkdwn (`*<url|Title>*`), builds Block Kit blocks — a `header`, a
stats `section`, then one `section` + `divider` per paragraph — and batches into
messages of ≤ 50 blocks (Slack's hard limit). Section text truncated to 3,000
chars.

### Buttondown — `buttondown_notify.py`

Posts to `https://api.buttondown.com/v1/emails` with
`status: "about_to_send"` and the `X-Buttondown-Live-Dangerously: true` header.
Buttondown renders Markdown natively, so the digest is sent as-is. Buttondown
owns the subscriber list, double opt-in, and unsubscribe links. Expects HTTP
201. Setup documented in `docs/buttondown-setup.md`; design spec at
`docs/superpowers/specs/2026-07-04-buttondown-email-digest-design.md`.

### `--notify-at-utc`

Decouples *when the digest is computed* from *when subscribers are notified*.
`_seconds_until_utc_time` parses `HH:MM`, validates the range, and computes the
delay to the next occurrence today (0 if already past). Production runs the job
at 02:10 UTC and notifies at 02:30 UTC (08:00 IST).

### Status reporting

`_status(sent, configured, skip_reason)` renders each channel as
`not configured` / `sent ✅` / `failed ❌` / `skipped (test run)` /
`skipped (0 articles)`. The run summary line prints all three plus article
count, tokens, estimated cost, duration, rubric failures, images ready, and
image failures.

---

## 17. Observability

**File:** `news_buddy/observability.py`

Opt-in only — activates when `OTEL_TRACING` is `1`/`true`/`yes`. Called from
`main()` **before** the pipeline imports or constructs any LangChain model, so
the OpenInference LangChain instrumentor can hook every call.

`phoenix.otel.register(project_name=..., auto_instrument=True)` with
`PHOENIX_PROJECT` (default `news-buddy-langgraph`) and
`PHOENIX_COLLECTOR_ENDPOINT` (default `http://localhost:6006`).

Fail-soft: a missing or broken Phoenix install prints a notice and returns.
Tracing must never break a production run.

---

## 18. The model evaluation harness

**Files:** `scripts/eval_sub_model.py`, `eval_scoring.py`, `eval_report.py`,
`eval_store.py`

Purpose: decide model swaps on evidence rather than impressions. **Opt-in and
never run by CI** because it makes real model calls.

```bash
python -m scripts.eval_sub_model --capture   # freeze fixtures once
python -m scripts.eval_sub_model --run       # score candidates against them
```

### Fixture store — `eval_store.py`

`--capture` pulls real articles from the **published archive** (`index.json` →
each day's JSON → re-extract the body), skipping any article with no body.

The storage split is deliberate:
- **`articles.json`** holds third-party article bodies and is **gitignored**.
- **`manifest.json`** is committed and holds URL, title, source, date, and a
  **SHA-256 of each body**.

`load_fixtures` verifies every body against the manifest and raises
`FixtureError` on drift, with a message telling you to re-capture. So the corpus
is verifiable without redistributing copyrighted text. An `Article` `TypedDict`
defines the shape.

### The scoring model — `eval_scoring.py`

Pure functions, no network, fully unit-tested.

`ArticleResult` per article: ok, summary, `rubric_passed`, `brief_errors`,
`json_failure`, `total_tokens`, `latency_s`, `word_count`, `error`.

`ModelAggregate` per model: availability, article count, ok count,
**brief validity rate** (the headline metric — an invalid brief blocks
publication), first-pass rubric rate, strict-recovery rate, JSON failure count,
error count, per-field failure breakdown, p50/p95 latency, mean tokens over
successful calls only, and word-count-in-range rate against the 70–110 target.

Two documented honesty notes in the source:
- `classify_failure` is a **heuristic**: `_summarize_one` collapses a JSON parse
  failure and a genuinely bad brief into the same exception, so all four image
  fields missing at once is treated as the fallback-dict signature.
- `_percentile` is **nearest-rank, not interpolated**, and says so — it will
  disagree with `numpy.percentile`.

### The runner

Monkeypatches `_extract.extract_body` to serve frozen bodies instead of hitting
the network, and restores it in a `finally` block (there is a dedicated test
asserting restoration happens even when an exception is in flight). Fails fast
if `NVIDIA_API_KEY` is missing rather than reporting every model as
"unavailable". Runs a first pass, then a strict-retry pass over only the
articles whose rubric failed.

### The published baseline

`docs/evals/2026-07-30-sub-model-baseline.md` compares four candidates against
the production default across 24 articles:

| Model | Brief valid | First-pass rubric | p50 | Words in range |
|---|---|---|---|---|
| `meta/llama-3.1-8b-instruct` *(baseline)* | 96% | 42% | 2.1s | 17% |
| `nvidia/nemotron-3-super-120b-a12b` | 0% | 0% | 6.2s | 0% |
| `poolside/laguna-xs-2.1` | 88% | 88% | 2.6s | 83% |
| `mistralai/mistral-medium-3.5-128b` | 67% | 21% | 86.7s | 4% |
| `google/gemma-4-31b-it` | 67% | 38% | 25.1s | 21% |

**The incumbent was kept** — every candidate fell short on brief validity, the
pass/fail gate fixed *before* the run. The report also documents and corrects a
bug found afterward (mean tokens were being divided by all attempts including
zero-token failures, pulling the mean toward zero) and shows the reconstruction
arithmetic rather than silently republishing.

---

## 19. CI/CD and deployment

### `.github/workflows/daily-digest.yml`

**Schedules:** `10 2 * * *` primary, plus `10 3` and `10 4` UTC as backups —
GitHub's scheduler can delay or drop runs.

**The gh-pages preflight guard.** Before doing anything, a scheduled run shallow-
clones `gh-pages` and checks whether `{today}.html` already exists. If it does,
every subsequent step is skipped. This is what stops a delayed backup schedule
from sending duplicate notifications after the day's digest already published.
Manual `workflow_dispatch` runs explicitly bypass the guard.

**Steps:** checkout → preflight → Python 3.11 → uv (cached) →
`uv sync --frozen --no-dev` → restore `state.db` and `~/news/images` from
`actions/cache` → run the digest → deploy.

**Deploy:** clones (or inits) `gh-pages` into a temp dir, copies
`{DATE}.html`, `{DATE}.json`, and the whole `images/` directory, calls
`write_manifest` and `python -m news_buddy.archive_writer` inside the checkout,
commits as `github-actions[bot]`, and pushes. Exits cleanly if there is nothing
to commit or no HTML was produced.

**Concurrency group** `daily-news-digest-${{ github.ref }}` with
`cancel-in-progress: false` prevents overlapping runs.
**Timeout:** 45 minutes. **Permissions:** `contents: write`.
**`NEWS_BUDDY_RAG_ENABLED: "false"`** — RAG is disabled in CI.
Manual dispatch defaults `test_run: true`.

### `.github/workflows/ci.yml`

Runs on pushes to `main` and all pull requests. **Two independent jobs:**

1. `test` — lint + 124 tests, audit runtime dependencies, then build and smoke-test the wheel from an unrelated directory.
2. `mcp-server` — lint + 15 tests, audit runtime dependencies, then build the MCP Docker image.

Both on Python 3.11 with uv caching, 15-minute timeouts.

### `.github/workflows/openwiki-update.yml`

Weekly (Sunday 18:47 UTC) or manual. Regenerates the OpenWiki Code Brain.
Notably hardened:

- **All third-party actions are pinned to full commit SHAs.**
- `persist-credentials: false` — keeps the write-capable `GITHUB_TOKEN` out of
  `.git/config`, because the OpenWiki CLI and its transitive npm dependencies
  run against this checkout.
- Pinned toolchain: `openwiki@0.2.4`, `mermaid@11.16.0`, `jsdom@29.1.1`.
- A **retry loop**: two 10-minute attempts with a 60s cooldown; a timed-out
  attempt is cleaned with `git checkout -- openwiki && git clean -fd openwiki`
  so the retry starts from a clean tree.
- **Model choice is documented in a comment**: `nvidia/nemotron-3-super-120b-a12b`,
  deliberately *not* a reasoning model — the previous nano-omni reasoning model
  returned 4,246 tokens against a 1,200-token cap, and that overhead compounded
  across agentic turns until the attempt timed out. This MoE (120B total, ~12B
  active) finished the same probe in 20.8s within the limit.
- Runs `scripts/validate_openwiki.py` before opening the PR.
- Opens a **draft** PR restricted to `add-paths: openwiki` — `AGENTS.md` and
  `CLAUDE.md` are deliberately excluded so an automated run cannot rewrite the
  rules future agents follow.

---

## 20. Documentation system

### Human-facing

| File | Role |
|---|---|
| `README.md` | Public introduction, architecture diagram, repository tour, setup, running, deployment, search, MCP, evaluation, gaps |
| `DIAGRAM.md` | Node-level Mermaid diagrams: full graph flow, CLI/notification flow, scheduled run, CI, plus a text dump of state at every stage and a flag reference |
| `docs/rag-architecture.html` | Standalone RAG/search architecture view |
| `docs/buttondown-setup.md` | Email setup guide |
| `docs/evals/` | Worked evaluation results |

### Agent-facing

| File | Role |
|---|---|
| `AGENTS.md` | Repo-wide ground truth: authoritative file list, documentation contract, the 11-step runtime model, safety rules, known gaps, preferred next steps |
| `CLAUDE.md` | Short pointer to `AGENTS.md` + OpenWiki, restating the no-`deepagents` rule |
| `openwiki/INSTRUCTIONS.md` | Constrains OpenWiki generation to preserve key boundaries |

### The OpenWiki "Code Brain" — 12 generated pages

`index.md`, `quickstart.md`, `architecture/langgraph-pipeline.md`,
`processing/feed-and-article.md`, `llm-and-models.md`, `image-generation.md`,
`archive-and-deployment.md`, `persistence.md`,
`notifications-and-operations.md`, `testing-and-gaps.md`, `INSTRUCTIONS.md`,
`log.md`, plus two directory index pages.

The `index.md` itself carries OKF frontmatter (`okf_version: "0.1"`) — the same
format used for the article knowledge base.

**Nothing at runtime reads `openwiki/`.** It is documentation only.

### `scripts/validate_openwiki.py` — the documentation tripwire

A dependency-free validator (stdlib only, so it runs anywhere) checking:

- **Required pages exist** — all 12.
- **Known hallucinations are absent** — a hardcoded set of six identifiers that
  appeared in an inaccurate first generation and exist nowhere in the code:
  `asyncio.gather`, `filter_ai_stories`, `dedupe_urls`, `score_and_summarize`,
  `seen_urls.db`, `newspaper3k`. Their return is a review tripwire.
- **The `deepagents` prohibition** — the term must not reach any generated page.
  `INSTRUCTIONS.md` is exempt because it *states* the prohibition.
- **Required facts** — specific substrings must appear on specific pages
  (e.g. `quickstart.md` must contain "remain authoritative"; the pipeline page
  must contain "ThreadPoolExecutor" and "are not graph nodes").
- **Structural claims** — `_force_persistence_errors` asserts the `--force`
  persistence fact structurally rather than as prose (commit `7c1ee4a`, after a
  brittle prose check).
- **OKF frontmatter** and **internal link resolution**.

### `docs/superpowers/` — plans and specs

Four implementation plans and six design specs, dated:

- `2026-07-04` Buttondown email digest
- `2026-07-17` Public MCP server
- `2026-07-30` Sub-model baseline eval
- `2026-07-31` OKF article knowledge base
- `2026-08-01` Resilient image briefs
- `2026-08-01` Image brief repair

`AGENTS.md` is explicit that these are historical and **do not prove a feature is
currently implemented**.

---

## 21. Agent tooling and skills

### The `topicsearch` skill

Present in two locations for two harnesses: `.agents/skills/topicsearch/SKILL.md`
(portable) and `.claude/skills/topicsearch/SKILL.md` (Claude Code). Version 2.0,
`allowed-tools: [Bash]`. Detailed in [§13](#13-search-surfaces).

### Superpowers / SDD artifacts — `.superpowers/sdd/`

The evaluation-harness feature was built with a spec → plan → subagent-driven
execution workflow. The directory retains the full audit trail:

- `task-1-brief.md` … `task-6-brief.md` — per-task instructions
- `task-1-report.md` … `task-5-report.md` — per-task outcome reports
- `review-{sha}..{sha}.diff` — 10 committed review diffs
- `progress.md` — task-by-task status with minor findings explicitly *carried
  forward* to a final review rather than dropped
- `final-review-fix-report.md`

`progress.md` records real engineering rigor, e.g.: a restoration test that
"did not discriminate" was replaced with one that monkeypatches
`evaluate_model` and asserts propagation via `pytest.raises`, then verified by a
**mutation check** — removing the `try/finally` makes the test fail, then
reverted byte-identical.

### Hallmark — `.hallmark/`

A design-system record: `preflight.json` captures the scanned framework, font
stack, palette approach, motion policy, spacing scale, deployment target, and
six preserved behaviors. `log.json` tracks changes. Hallmark critique headers
are embedded directly in `tokens.css`, `html_writer.py`, and
`prompts/image_style.md`.

---

## 22. Configuration reference

### Install profile

A default `pip install .` covers the configured NVIDIA pipeline and nothing
else. Provider stacks, RAG, and tracing are opt-in extras — see
[Optional dependency extras](#optional-dependency-extras) for the table and the
install commands.

### Where state is written

Resolved by `runtime_root()` in `news_buddy/paths.py`:

| Situation | Writable root |
|---|---|
| `NEWS_BUDDY_HOME` is set | That path, expanded and resolved |
| Source checkout (`config.yaml` beside the package) | The repository root |
| Installed wheel | The current working directory |

This governs `state.db`, `chroma_db/`, `knowledge_base/`, and which `.env` is
loaded. Setting `NEWS_BUDDY_HOME` is the supported way to keep runtime data
somewhere stable when running an installed package, since the default otherwise
follows whatever directory the command was invoked from.

### `config.yaml`

**Feeds and filtering**

| Key | Value | Meaning |
|---|---|---|
| `feeds` | 17 entries | `{name, url}` per source |
| `trusted_ai_sources` | 15 names | Bypass keyword filtering |
| `ai_keywords` | 17 terms | artificial intelligence, machine learning, deep learning, large language model, llm, generative ai, openai, anthropic, google deepmind, mistral, gemini, gpt, claude, neural network, ai model, ai agent, foundation model |

**Volume and windows**

| Key | Value | Meaning |
|---|---|---|
| `output_dir` | `~/news` | Where digests are written |
| `lookback_hours` | 24 | Base freshness window |
| `max_items_per_feed` | 10 | Normal per-feed cap |
| `max_articles` | 8 | Hard cap on summarized articles (protects API quota) |
| `min_articles` | 8 | Backfill target |
| `max_backfill_lookback_hours` | 168 | Stop widening after 7 days |
| `backfill_max_items_per_feed` | 25 | Deeper inspection when topping up |
| `icymi_backfill` | true | Re-include seen items as a last resort |
| `max_top_stories` | 5 | Size of the "Top Stories" section |
| `summary_style` | prose string | Descriptive style hint |

**Rubric**

`enabled: true`, `min_summary_length: 200`, `min_summary_words: 65`,
`importance_penalty: 2`, `retry_on_failure: true`.

**Images**

`enabled: true`, `provider: nvidia`,
`model: black-forest-labs/flux.2-klein-4b`, `width: 1184`, `height: 880`,
`quality: 82`, `max_workers: 1`, `timeout: 180`, `retries: 2`,
`retry_delay: 2`, `steps: 4`, `require_all: false`,
`require_article_brief: true`, `style_guide: prompts/image_style.md`,
`style_version: explainer-v10`, `generate_in_test_run: false`,
`brief_retry: true`.

**LLM**

`provider: nvidia`, `main_model: meta/llama-3.1-8b-instruct` *(unused by the
graph)*, `sub_model: meta/llama-3.1-8b-instruct`, `hf_provider: auto`,
`temperature: 0.2`, `max_tokens: 512`, `requests_per_minute: 8`. Commented
guidance for switching to local Ollama is retained inline.

### Environment variables (`.env` / GitHub secrets)

| Variable | Required when |
|---|---|
| `NVIDIA_API_KEY` | `llm.provider: nvidia` or `images.provider: nvidia`; also the OpenWiki workflow |
| `NEWS_BUDDY_HOME` | Optional writable root for `state.db`, `chroma_db/`, and `knowledge_base/` |
| `GOOGLE_API_KEY` | `llm.provider: google`; **always required for RAG embeddings** |
| `HF_TOKEN` / `HUGGINGFACEHUB_API_TOKEN` | `llm.provider: huggingface` |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Telegram delivery (both needed) |
| `SLACK_WEBHOOK_URL` | Slack delivery |
| `BUTTONDOWN_API_KEY` | Email delivery |
| `BUTTONDOWN_USERNAME` | Archive signup form |
| `NEWS_BUDDY_RAG_ENABLED` | Set `false` to disable embedding (CI does) |
| `OTEL_TRACING` | Set truthy to enable tracing |
| `PHOENIX_PROJECT`, `PHOENIX_COLLECTOR_ENDPOINT` | Tracing targets |
| `NEWS_BUDDY_ARCHIVE_URL` | MCP server (required) |
| `PORT` | MCP server port (default 8000) |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | Reserved; unused |

### Gitignored runtime state

`.env`, `state.db`, `chroma_db/`, `knowledge_base/`, `news/`, `.claude/`,
`scripts/eval_fixtures/articles.json`.

---

## 23. Run modes and safety semantics

```bash
python -m news_buddy run [--config PATH] [--date YYYY-MM-DD]
                         [--dry-run] [--test-run] [--force]
                         [--notify-at-utc HH:MM] [--verbose]
```

| Mode | Network | Writes files | Marks seen | Embeds RAG | Generates images | Notifies | Deploys |
|---|---|---|---|---|---|---|---|
| `--dry-run` | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| `--test-run` | ✓ | ✓ | ✗ | ✗ | ✗ * | ✗ | ✗ |
| `--force` | ✓ | ✓ | ✗ | ✗ | ✓ | ✓ | ✓ |
| normal | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

\* unless `images.generate_in_test_run: true`

`--test-run` is the documented mechanism for **live verification that must not
mutate production state**. `--dry-run` is for pure logic checks with no side
effects at all.

### Safety rules (from `AGENTS.md`)

- Use `--test-run --verbose` for live verification.
- Use `--dry-run --verbose` when no network or file side effects are wanted.
- Do not run a normal live digest just to test notifications.
- Empty digests stay quiet on every channel.
- Scheduled backups must keep the `gh-pages` preflight guard.
- When diagnosing Buttondown, check GitHub Actions logs and the final
  notification status, not just local code.

### Exit behavior

On pipeline error the CLI prints `❌ Pipeline failed: {error}` to stderr and
exits `1`. Telegram and Slack error alerts fire (when configured and not in a
test/dry run); Buttondown does not — subscribers should not receive failure mail.

### Cost estimation

`est_cost_usd = (tokens / 1_000_000) * 0.15` — a blended estimate anchored to
the Gemini 2.5 Flash pay-as-you-go input rate. It is an estimate, and the source
labels it as such.

---

## 24. Test suite

**124 tests** in the main package across 19 files; **15 tests** in the MCP
package across 2 files.

| File | Tests what |
|---|---|
| `test_agent_selection.py` | Filtering, dedup, backfill, and selection logic |
| `test_agent_images.py` | The image node's skip/enable/require paths |
| `test_summarize_image_brief.py` | Summarization + image brief extraction |
| `test_image_brief_repair.py` | The repair loop and its fallbacks |
| `test_image_generator.py` | Largest test file (426 lines) — settings clamping, caching, retries, content-filter path, label rendering, SVG fallback |
| `test_rubric.py` | All four rubric dimensions and edge cases |
| `test_llm.py` | Provider dispatch and adapters |
| `test_paths.py` | Checkout/installed-package resource and writable-data paths |
| `test_rag.py` | Embedding and semantic search |
| `test_knowledge_base.py` | OKF file writing |
| `test_index_writer.py` | JSON records and manifest |
| `test_write_html_node_index.py` | HTML node's index/manifest interaction |
| `test_archive_writer_signup.py` | Signup form presence/absence |
| `test_backfill_index.py` | HTML→JSON reconstruction parsing |
| `test_buttondown_notify.py` | Email delivery |
| `test_cli_notifications.py` | Notification suppression rules |
| `test_eval_store.py` | Fixture manifest verification |
| `test_eval_scoring.py` | Pure scoring functions |
| `test_eval_report.py` | Report rendering and cell escaping |
| `test_eval_runner.py` | Patch restoration, config isolation, limit/rpm handling |
| MCP `test_index_client.py` | Caching, staleness, 404 handling |
| MCP `test_server.py` | All three tools including exception paths |

---

## 25. Known gaps

Documented openly in both `README.md` and `AGENTS.md`:

1. **Dedup is URL-based, not story-cluster based.** The same story from five
   outlets appears as five entries. The fix would use the existing embeddings or
   title/summary similarity for story-level clustering.
2. **RAG is disabled in CI** (`NEWS_BUDDY_RAG_ENABLED=false` in the daily
   workflow), so Chroma is effectively a local experiment until persistence
   across runs is solved.
3. **`state.db` lives in the Actions cache** and would be lost on eviction —
   causing already-covered articles to resurface.
4. **Coverage gaps** — `feeds.py` (raw parsing) and `state.py` (SQLite mechanics)
   lack direct tests; rubric edge cases and some output/notification failure
   paths are thin.
5. **`main_model` is configured but unused** by the graph.

**Preferred next steps** (from `AGENTS.md`): keep docs and diagrams accurate;
add story-level clustering; persist RAG across CI runs and expose archive
search/Q&A; add focused tests for feed parsing, dedup/backfill, rubric scoring,
and HTML output.

---

## 26. Project statistics

| Metric | Value |
|---|---|
| Total commits | 97 |
| Merged pull requests | 12 |
| Python modules (main package) | 22 |
| Python modules (MCP package) | 3 |
| Total Python LOC (source + scripts + tests) | ~7,744 |
| Largest module | `agent.py` (864 lines) |
| Second largest | `image_generator.py` (806 lines) |
| Tests (main / MCP) | 124 / 15 |
| GitHub Actions workflows | 3 |
| RSS feeds | 17 |
| AI keywords | 17 |
| LLM providers supported | 4 |
| Notification channels | 3 |
| Search surfaces | 4 |
| MCP tools | 3 |
| Prompt files | 4 (3 live) |
| OpenWiki pages | 12 |
| Design specs / implementation plans | 6 / 4 |
| Agent skills | 1 (`topicsearch`, in 2 locations) |

### Recurring design principles visible across the codebase

- **Degrade, don't fail.** Every layer has a fallback: trafilatura→lxml→RSS
  summary; generated image→safe prompt→SVG placeholder→no image; remote
  archive→stale cache; failed summary→title-based stub. A digest gets published.
- **Deterministic where possible, LLM only where it earns its cost.** Fetching,
  filtering, dedup, ranking, and rendering are plain Python. The rubric is pure
  heuristics. The legend is publisher-rendered, not model-rendered.
- **Contracts are enforced, not assumed.** Image briefs are validated;
  fixtures are hash-verified; documentation is validated against known
  hallucinations; the exception message the eval harness parses is documented as
  a contract.
- **The unhappy path is designed.** Content filters, rate limits, dropped cron
  runs, delayed backup schedules, empty digests, truncated model output — each
  has explicit, tested handling.
- **Honesty in the record.** Gaps are documented rather than hidden; a published
  evaluation was corrected in place with the arithmetic shown; `main_model` is
  flagged as unused; heuristics are labeled as heuristics.
