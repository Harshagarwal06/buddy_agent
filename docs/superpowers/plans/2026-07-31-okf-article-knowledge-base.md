# OKF Article Knowledge Base Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist each accepted article as an OKF-formatted `.md` file (Markdown + YAML frontmatter) before it's embedded into Chroma, so the semantic index has a durable, human-readable source of truth on disk instead of only living inside `chroma_db/`.

**Architecture:** A new `news_buddy/knowledge_base.py` module owns file writing only (no Chroma, no LLM calls). `news_buddy/rag.py`'s `embed_article()` calls it before embedding, and now embeds the article's title+summary instead of title+truncated-full-body. `news_buddy/agent.py`'s call site is updated to pass summary/tags/published_at instead of the raw extracted body.

**Tech Stack:** Python, `pyyaml` (already a dependency), `pytest` + `monkeypatch` for tests (this repo's existing test stack — no new dependencies).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-31-okf-article-knowledge-base-design.md` — follow it exactly; do not add fields, files, or behavior beyond what it describes.
- `knowledge_base/` is gitignored, local-only, mirrors `chroma_db/`. Do not commit it or add CI steps for it.
- The OKF file body holds only the AI-generated summary — never the full scraped article text (copyright reasons, per spec Context section).
- `description` frontmatter field = first sentence of summary (split on first `". "`); falls back to the full summary when there's no sentence break.
- Filename = `hashlib.sha256(url.encode()).hexdigest()[:16] + ".md"`.
- Test runner for this repo: `uv run pytest <path> -v` (see `.github/workflows/ci.yml`).
- Follow existing test conventions: plain `pytest` functions (no test classes), `monkeypatch.setattr(module, "_CONST", ...)` to isolate module-level path/singleton constants (see `tests/test_agent_selection.py:39-40` for the established pattern in this codebase).

---

### Task 1: `news_buddy/knowledge_base.py` — OKF file writer

**Files:**
- Create: `news_buddy/knowledge_base.py`
- Test: `tests/test_knowledge_base.py`

**Interfaces:**
- Produces: `write_article(url: str, title: str, summary: str, tags: list[str], source: str, published_at: str) -> Path` — writes (or, if the file already exists, no-ops and returns the existing path) an OKF-formatted `.md` file. Later tasks (`rag.py`) call this by name with these exact keyword arguments.
- Produces: module constant `_KB_PATH: Path` (default `Path(__file__).parent.parent / "knowledge_base" / "articles"`), monkeypatchable in tests exactly like `agent._DB`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_knowledge_base.py`:

```python
import hashlib

import yaml

from news_buddy import knowledge_base as kb


def _read_frontmatter(path):
    text = path.read_text(encoding="utf-8")
    _, frontmatter, body = text.split("---\n", 2)
    return yaml.safe_load(frontmatter), body


def test_write_article_creates_expected_frontmatter_and_body(monkeypatch, tmp_path):
    monkeypatch.setattr(kb, "_KB_PATH", tmp_path)

    path = kb.write_article(
        url="https://example.test/a",
        title="Model launches",
        summary="A new model launched today. It handles longer contexts.",
        tags=["ai", "product"],
        source="Test Feed",
        published_at="2026-07-17T09:00:00+00:00",
    )

    frontmatter, body = _read_frontmatter(path)
    assert frontmatter == {
        "type": "Article",
        "title": "Model launches",
        "description": "A new model launched today.",
        "resource": "https://example.test/a",
        "tags": ["ai", "product"],
        "timestamp": "2026-07-17T09:00:00+00:00",
        "source": "Test Feed",
    }
    assert "## Summary" in body
    assert "A new model launched today. It handles longer contexts." in body


def test_write_article_description_falls_back_to_full_summary_without_sentence_break(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(kb, "_KB_PATH", tmp_path)

    path = kb.write_article(
        url="https://example.test/b",
        title="Short update",
        summary="No period-space break here",
        tags=[],
        source="Test Feed",
        published_at="2026-07-17T09:00:00+00:00",
    )

    frontmatter, _ = _read_frontmatter(path)
    assert frontmatter["description"] == "No period-space break here"


def test_write_article_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(kb, "_KB_PATH", tmp_path)

    first = kb.write_article(
        url="https://example.test/c",
        title="Original title",
        summary="Original summary.",
        tags=["ai"],
        source="Test Feed",
        published_at="2026-07-17T09:00:00+00:00",
    )
    second = kb.write_article(
        url="https://example.test/c",
        title="Changed title",
        summary="Changed summary.",
        tags=["changed"],
        source="Test Feed",
        published_at="2026-07-18T09:00:00+00:00",
    )

    assert first == second
    frontmatter, _ = _read_frontmatter(first)
    assert frontmatter["title"] == "Original title"


def test_write_article_filename_is_deterministic_per_url(monkeypatch, tmp_path):
    monkeypatch.setattr(kb, "_KB_PATH", tmp_path)

    path = kb.write_article(
        url="https://example.test/d",
        title="A",
        summary="A summary.",
        tags=[],
        source="Test Feed",
        published_at="2026-07-17T09:00:00+00:00",
    )

    expected_name = hashlib.sha256(b"https://example.test/d").hexdigest()[:16] + ".md"
    assert path.name == expected_name
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_knowledge_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'news_buddy.knowledge_base'`

- [ ] **Step 3: Write the implementation**

Create `news_buddy/knowledge_base.py`:

```python
"""OKF-formatted knowledge-base files for accepted articles.

Each article is written once as a Markdown file with YAML frontmatter,
following Google Cloud's Open Knowledge Format (okf_version 0.1). This is
the source of truth for what news_buddy/rag.py embeds into Chroma.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

_KB_PATH = Path(__file__).parent.parent / "knowledge_base" / "articles"


def _description(summary: str) -> str:
    first, sep, _rest = summary.partition(". ")
    if sep:
        return first + "."
    return summary


def write_article(
    url: str,
    title: str,
    summary: str,
    tags: list[str],
    source: str,
    published_at: str,
) -> Path:
    """Write an OKF-formatted article file. No-ops if it already exists."""
    _KB_PATH.mkdir(parents=True, exist_ok=True)
    filename = hashlib.sha256(url.encode()).hexdigest()[:16] + ".md"
    path = _KB_PATH / filename
    if path.exists():
        return path

    frontmatter = yaml.safe_dump(
        {
            "type": "Article",
            "title": title,
            "description": _description(summary),
            "resource": url,
            "tags": tags,
            "timestamp": published_at,
            "source": source,
        },
        sort_keys=False,
    )
    path.write_text(
        f"---\n{frontmatter}---\n\n## Summary\n\n{summary}\n", encoding="utf-8"
    )
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_knowledge_base.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add news_buddy/knowledge_base.py tests/test_knowledge_base.py
git commit -m "feat: write OKF-formatted article files for the knowledge base"
```

---

### Task 2: `news_buddy/rag.py` — write-then-embed

**Files:**
- Modify: `news_buddy/rag.py` (full file shown below — small file, easier to replace than patch)
- Test: `tests/test_rag.py` (new — no test file exists for `rag.py` today)

**Interfaces:**
- Consumes: `knowledge_base.write_article(url, title, summary, tags, source, published_at) -> Path` from Task 1.
- Produces: `embed_article(url: str, title: str, summary: str, tags: list[str], source: str, published_at: str) -> None` — replaces the old `(url, title, body, source)` signature. `agent.py` (Task 3) calls this by these exact keyword arguments. `semantic_search(query: str, n_results: int = 5) -> list[dict]` is unchanged.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rag.py`:

```python
from news_buddy import rag


class _FakeCollection:
    def __init__(self):
        self._ids = set()
        self.added = []

    def get(self, ids):
        return {"ids": [i for i in ids if i in self._ids]}

    def add(self, ids, embeddings, documents, metadatas):
        self._ids.update(ids)
        self.added.append(
            {"ids": ids, "embeddings": embeddings, "documents": documents, "metadatas": metadatas}
        )


class _FakeEmbedder:
    def embed_query(self, text):
        return [float(len(text))]


def test_embed_article_writes_okf_file_before_embedding(monkeypatch):
    fake_collection = _FakeCollection()
    write_calls = []

    monkeypatch.setattr(rag, "_get_collection", lambda: fake_collection)
    monkeypatch.setattr(rag, "_get_doc_embedder", lambda: _FakeEmbedder())
    monkeypatch.setattr(
        rag.knowledge_base, "write_article", lambda **kwargs: write_calls.append(kwargs)
    )

    rag.embed_article(
        url="https://example.test/a",
        title="Model launches",
        summary="A new model launched today.",
        tags=["ai"],
        source="Test Feed",
        published_at="2026-07-17T09:00:00+00:00",
    )

    assert write_calls == [
        {
            "url": "https://example.test/a",
            "title": "Model launches",
            "summary": "A new model launched today.",
            "tags": ["ai"],
            "source": "Test Feed",
            "published_at": "2026-07-17T09:00:00+00:00",
        }
    ]
    assert fake_collection.added[0]["ids"] == ["https://example.test/a"]
    assert fake_collection.added[0]["documents"] == [
        "Model launches\n\nA new model launched today."
    ]
    assert fake_collection.added[0]["metadatas"] == [
        {"url": "https://example.test/a", "title": "Model launches", "source": "Test Feed"}
    ]


def test_embed_article_skips_already_indexed_url(monkeypatch):
    fake_collection = _FakeCollection()
    fake_collection._ids.add("https://example.test/dup")
    write_calls = []

    monkeypatch.setattr(rag, "_get_collection", lambda: fake_collection)
    monkeypatch.setattr(
        rag.knowledge_base, "write_article", lambda **kwargs: write_calls.append(kwargs)
    )

    rag.embed_article(
        url="https://example.test/dup",
        title="Already indexed",
        summary="Doesn't matter.",
        tags=[],
        source="Test Feed",
        published_at="2026-07-17T09:00:00+00:00",
    )

    assert write_calls == []
    assert fake_collection.added == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_rag.py -v`
Expected: FAIL — `embed_article() got an unexpected keyword argument 'summary'` (current signature is `(url, title, body, source)`)

- [ ] **Step 3: Write the implementation**

Replace `news_buddy/rag.py` in full:

```python
"""ChromaDB-backed vector store for semantic search over past articles.

Uses Google models/gemini-embedding-2 (same GOOGLE_API_KEY as the LLM).
The chroma_db/ directory is created alongside state.db on first use. Each
embedded article is first written as an OKF file by knowledge_base.py,
which becomes the text that gets embedded.
"""
from __future__ import annotations

import os
from pathlib import Path

import chromadb
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from news_buddy import knowledge_base

_CHROMA_PATH = Path(__file__).parent.parent / "chroma_db"
_COLLECTION_NAME = "articles"

_collection: chromadb.Collection | None = None
_doc_embedder: GoogleGenerativeAIEmbeddings | None = None
_query_embedder: GoogleGenerativeAIEmbeddings | None = None


def _api_key() -> str:
    key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GOOGLE_API_KEY is not set — required for RAG embeddings.")
    return key


def _get_doc_embedder() -> GoogleGenerativeAIEmbeddings:
    global _doc_embedder
    if _doc_embedder is None:
        _doc_embedder = GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-2",
            google_api_key=_api_key(),
            task_type="retrieval_document",
        )
    return _doc_embedder


def _get_query_embedder() -> GoogleGenerativeAIEmbeddings:
    global _query_embedder
    if _query_embedder is None:
        _query_embedder = GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-2",
            google_api_key=_api_key(),
            task_type="retrieval_query",
        )
    return _query_embedder


def _get_collection() -> chromadb.Collection:
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=str(_CHROMA_PATH))
        _collection = client.get_or_create_collection(
            _COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def embed_article(
    url: str,
    title: str,
    summary: str,
    tags: list[str],
    source: str,
    published_at: str,
) -> None:
    """Write the article's OKF file, then embed and store it. No-ops silently if already indexed."""
    collection = _get_collection()
    if collection.get(ids=[url])["ids"]:
        return
    knowledge_base.write_article(
        url=url,
        title=title,
        summary=summary,
        tags=tags,
        source=source,
        published_at=published_at,
    )
    text = f"{title}\n\n{summary}"
    vector = _get_doc_embedder().embed_query(text)
    collection.add(
        ids=[url],
        embeddings=[vector],
        documents=[text],
        metadatas=[{"url": url, "title": title, "source": source}],
    )


def semantic_search(query: str, n_results: int = 5) -> list[dict]:
    """Return the n most semantically similar past articles to query."""
    collection = _get_collection()
    total = collection.count()
    if total == 0:
        return []
    vector = _get_query_embedder().embed_query(query)
    results = collection.query(
        query_embeddings=[vector],
        n_results=min(n_results, total),
        include=["metadatas", "distances"],
    )
    return [
        {
            "title": meta["title"],
            "source": meta["source"],
            "url": meta["url"],
            "similarity": round(1 - dist, 3),
        }
        for meta, dist in zip(results["metadatas"][0], results["distances"][0])
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_rag.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add news_buddy/rag.py tests/test_rag.py
git commit -m "feat: embed articles from their OKF file instead of raw body"
```

---

### Task 3: `news_buddy/agent.py` — update the call site

**Files:**
- Modify: `news_buddy/agent.py:486-491`

**Interfaces:**
- Consumes: `rag.embed_article(url, title, summary, tags, source, published_at)` from Task 2.

- [ ] **Step 1: Update the call site**

In `news_buddy/agent.py`, the `_process` closure inside `summarize_articles_node` currently has (around line 480-493):

```python
            if not state["force"] and not state["test_run"]:
                _state.mark_seen(_DB, item)
                if _rag_enabled():
                    try:
                        from news_buddy import rag as _rag

                        _rag.embed_article(
                            url=item["url"],
                            title=item["title"],
                            body=body,
                            source=item["source"],
                        )
                    except Exception as e:
                        print(f"[warn] embed failed for {item['url']}: {e}", file=sys.stderr)
```

Change the `_rag.embed_article(...)` call to:

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

(`enriched_item` and `item` are already in scope at this point in `_process`; `body` is still used earlier in the function and is left alone.)

- [ ] **Step 2: Run the full test suite to confirm no regressions**

Run: `uv run pytest -q`
Expected: All tests pass (no test currently exercises this exact call site, so this step is a regression check, not new coverage — Task 2's `tests/test_rag.py` already covers `embed_article`'s new signature).

- [ ] **Step 3: Run lint**

Run: `uv run ruff check .`
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add news_buddy/agent.py
git commit -m "feat: pass summary/tags/published_at to embed_article"
```

---

### Task 4: Manual verification

**Files:** none (verification only)

- [ ] **Step 1: Run a real (non-test, non-force) digest locally with RAG enabled**

This requires `GOOGLE_API_KEY` set and a scratch `state.db`/`chroma_db` (a `--test-run` skips the `mark_seen`/embed path entirely per the `force`/`test_run` gate in `agent.py:480`, so this step needs a real run against throwaway local state — do not point this at the production `state.db`):

```bash
NEWS_BUDDY_RAG_ENABLED=true uv run python -m news_buddy run --verbose
```

- [ ] **Step 2: Confirm OKF files were written**

```bash
ls knowledge_base/articles/
cat knowledge_base/articles/*.md | head -20
```

Expected: one `.md` file per embedded article, each with `type: Article` frontmatter and a `## Summary` body matching what appeared in that day's digest.

- [ ] **Step 3: Confirm semantic search still works**

```bash
uv run python -m news_buddy.semantic_search_cli "<a topic from today's digest>"
```

Expected: results returned, unchanged in shape from before this change.

---

## Self-Review Notes

- **Spec coverage:** `knowledge_base.py` (Task 1) ✓, `rag.py` edit (Task 2) ✓, `agent.py` call site (Task 3) ✓, testing section (unit tests for `write_article` + updated `rag.py` tests + manual verification) ✓ (Task 4). Out-of-scope items from the spec (no `semantic_search` change, no git-tracking of `knowledge_base/`, no backfill script, no `openwiki/INSTRUCTIONS.md` update) are correctly absent from this plan.
- **Type consistency:** `write_article`'s parameter names/order match every call site (`rag.py` Task 2, both as the interface contract and the actual call). `embed_article`'s new signature matches its only caller (`agent.py` Task 3) exactly.
- **No placeholders:** every step has complete, runnable code — no "add tests for the above" or "handle errors" without code.
