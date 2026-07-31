# OKF Article Knowledge Base — Design

**Date:** 2026-07-31
**Status:** Approved (design), pending implementation plan

## Goal

Persist accepted articles as human-/agent-readable knowledge-base files,
using Google Cloud's [Open Knowledge Format](https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing)
(Markdown + YAML frontmatter), so the Chroma semantic index has a durable,
greppable, git-trackable source of truth behind it instead of vectors and
truncated text living only inside `chroma_db/`.

## Context

`news_buddy/rag.py`'s `embed_article(url, title, body, source)` currently
embeds articles straight from in-memory pipeline state into Chroma. There is
no on-disk representation of an article's knowledge-base entry at all — only
a vector, a 2000-char truncated text blob, and `{url, title, source}`
metadata, all inside the opaque `chroma_db/` directory.

This design adds a file-based layer in front of that: one OKF `.md` file per
article, written before embedding, which becomes the thing that actually gets
embedded. It does not change what Chroma is used for (semantic search over
past articles) or its lifecycle (local-only; CI runs with
`NEWS_BUDDY_RAG_ENABLED=false`, so this never touches CI).

Two things were explicitly ruled out during design:

- **Routing this through OpenWiki.** OpenWiki is an LLM-driven CLI that
  documents *source code* on a weekly CI schedule and opens a review PR
  (`openwiki/INSTRUCTIONS.md`). It is not a deterministic, in-process
  formatter, and using it to write one file per article would mean an
  agentic subprocess call per article instead of a template function.
  OpenWiki and this feature both happen to produce OKF-shaped files, but
  they solve unrelated problems.
- **Persisting the full scraped article body.** The pipeline has both the
  full extracted article text (from the source site) and its own
  AI-generated summary. Storing the full third-party text verbatim as files
  copies copyrighted content beyond what's needed. The OKF file body holds
  only the summary — text the pipeline itself generated.

## Components

### 1. `news_buddy/knowledge_base.py` (new)

```python
def write_article(
    url: str,
    title: str,
    summary: str,
    tags: list[str],
    source: str,
    published_at: str,
) -> Path:
    """Write an OKF-formatted article file. No-ops if it already exists."""
```

- Directory: `knowledge_base/articles/`, created alongside `chroma_db/` and
  `state.db` at the repo root (same pattern as `rag.py`'s `_CHROMA_PATH`).
  Gitignored — mirrors how `chroma_db/` is already untracked, and matches
  that CI disables RAG writes entirely, so nothing here needs a CI change.
- Filename: `hashlib.sha256(url.encode()).hexdigest()[:16] + ".md"` —
  deterministic per URL (matches Chroma's own per-URL keying), filesystem-safe,
  and doesn't leak the source URL into a path.
- Idempotent: if the file exists, return its path unchanged. No update-in-place
  behavior — an article's knowledge entry is fixed once written, same as
  `embed_article`'s existing "no-op if already indexed" behavior.
- Frontmatter via `yaml.safe_dump` (already a dependency — `pyproject.toml`):

  ```yaml
  ---
  type: Article
  title: <title>
  description: <first sentence of summary>
  resource: <url>
  tags: <tags>
  timestamp: <published_at>
  source: <source>
  ---

  ## Summary

  <summary>
  ```

  `description` is the first sentence of `summary` (split on the first
  `". "`; falls back to the full summary if there's no sentence break).
  `source` isn't one of OKF's example fields, but the spec is "minimally
  opinionated" (only `type` is required) — `source` stays because
  `semantic_search()` already returns it and it costs nothing to carry.

### 2. `news_buddy/rag.py` (edit)

`embed_article()` signature changes:

```python
# before
def embed_article(url: str, title: str, body: str, source: str) -> None:

# after
def embed_article(
    url: str, title: str, summary: str, tags: list[str],
    source: str, published_at: str,
) -> None:
```

New body (adds `from news_buddy import knowledge_base` to the module's imports):

```python
def embed_article(url, title, summary, tags, source, published_at) -> None:
    collection = _get_collection()
    if collection.get(ids=[url])["ids"]:
        return
    knowledge_base.write_article(url, title, summary, tags, source, published_at)
    text = f"{title}\n\n{summary}"
    vector = _get_doc_embedder().embed_query(text)
    collection.add(
        ids=[url],
        embeddings=[vector],
        documents=[text],
        metadatas=[{"url": url, "title": title, "source": source}],
    )
```

The existing `text[:2000]` truncation is dropped — summaries are already
short (60-110 words), so truncation no longer applies. `semantic_search()` is
unchanged; it only reads `metadatas`/`distances`, not `documents`.

### 3. `news_buddy/agent.py` (edit)

Call site at `agent.py:486` updates from:

```python
_rag.embed_article(url=item["url"], title=item["title"], body=body, source=item["source"])
```

to:

```python
_rag.embed_article(
    url=item["url"],
    title=item["title"],
    summary=enriched_item["summary"],
    tags=enriched_item["tags"],
    source=item["source"],
    published_at=item["published_at"],
)
```

The local `body` variable returned from `_summarize_one` is still needed
earlier in `_process` (nothing else changes there) — it's just no longer
passed to `embed_article`.

## Data flow

```
_process() in agent.py, after rubric passes and force/test_run gates clear:
    enriched_item (summary, tags) + item (url, title, source, published_at)
        → rag.embed_article(...)
            → knowledge_base.write_article(...) → knowledge_base/articles/<hash>.md
            → Chroma collection.add(embedding of title+summary, metadata)
```

## Error handling

No new error handling — the existing wrapper at the call site
(`agent.py:480-493`) already catches any exception from the whole
`embed_article` call and logs `[warn] embed failed for {url}` without
raising. A failure in `write_article` (e.g. disk full, permissions) surfaces
through that same catch and never blocks the digest.

## Testing

- Unit tests for `knowledge_base.write_article`: correct frontmatter fields
  and values, `description` correctly derived from the first sentence (and
  the no-sentence-break fallback), idempotency (second call with a different
  summary does not overwrite the existing file), deterministic filename per
  URL.
- Update existing `rag.py` tests for the new `embed_article` signature and
  the dropped truncation.
- Manual verification: run `python -m news_buddy run --test-run --verbose`
  with `NEWS_BUDDY_RAG_ENABLED=true` locally (a test run skips
  `mark_seen`/embedding entirely per the `force`/`test_run` gate, so this
  requires a real non-test, non-force run against a scratch `state.db`/
  `chroma_db/` to actually exercise the write path) and confirm a matching
  `knowledge_base/articles/<hash>.md` file appears for each embedded article.

## Out of scope (YAGNI)

- Any change to `semantic_search()` or the MCP server — this only changes
  what feeds the existing index, not how it's queried.
- Committing `knowledge_base/` to git, or any CI change to run with RAG
  enabled — stays local-only, matching `chroma_db/` today.
- A backfill script for articles already embedded before this change. Existing
  Chroma entries have no corresponding file; this only affects articles
  embedded going forward.
- Updating `openwiki/INSTRUCTIONS.md` to describe this new module — a
  reasonable follow-up (OpenWiki documents source code and would otherwise
  have to infer this module's purpose from scratch), but a separate,
  optional piece of work, not bundled into this design.
