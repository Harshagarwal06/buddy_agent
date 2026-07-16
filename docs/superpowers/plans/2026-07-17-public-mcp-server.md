# Public News Buddy MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a hosted, read-only MCP server that lets any Claude client search and fetch past News Buddy digests from the public gh-pages archive.

**Architecture:** The daily pipeline gains a small new output — a per-day JSON index and a manifest — written next to the existing Markdown/HTML and deployed to `gh-pages` unchanged otherwise. A separate, independently-deployed Python package (`news_buddy_mcp/`) runs a stateless FastMCP server that fetches that JSON over HTTP (with an in-memory cache) and exposes three read-only tools: `search_articles`, `get_digest`, `list_digests`. A one-off backfill script populates history from already-published HTML pages.

**Tech Stack:** Python 3.11+, `fastmcp` (streamable HTTP transport), `httpx`, `uv` for dependency management, Docker for the server's deployment image, GitHub Actions for CI and the existing daily workflow.

**Design doc:** `docs/superpowers/specs/2026-07-17-public-mcp-server-design.md`

## Global Constraints

- Python `>=3.11` everywhere (matches root `pyproject.toml` and `ci.yml`).
- `news_buddy_mcp/` is its own `uv` project (own `pyproject.toml`, own `uv.lock`) — it must not be added to the root project's dependencies.
- No semantic/RAG search, no write tools (`run_digest` or similar), no authentication — v1 is read-only and unauthenticated, per the design doc's explicit exclusions.
- Server config is exactly one environment variable: `NEWS_BUDDY_ARCHIVE_URL`.
- Index/manifest files use atomic write-then-`replace()`, matching the existing pattern in `news_buddy/agent.py`'s `_write_digest` and `news_buddy/archive_writer.py`'s `write_archive`.
- Article record shape (used everywhere — index files, tool responses): `{title, url, source, published_at, summary, tags, importance}`. `published_at` is `YYYY-MM-DD` (date only, no time), matching what's actually rendered in the HTML.
- Dates are `YYYY-MM-DD` strings throughout; date range/manifest ordering compares them as strings (safe because that format sorts lexically = chronologically).
- `limit` parameters are clamped server-side: `search_articles` 1–100 (default 20), `list_digests` 1–100 (default 30).

---

### Task 1: `news_buddy/index_writer.py` — index and manifest writers

**Files:**
- Create: `news_buddy/index_writer.py`
- Test: `tests/test_index_writer.py`

**Interfaces:**
- Produces: `write_index(output_dir: Path, date_str: str, enriched_items: list[dict]) -> Path` — writes `output_dir/{date_str}.json`.
- Produces: `write_manifest(output_dir: Path) -> Path` — writes `output_dir/index.json` as `{"dates": [...]}`, newest first.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_index_writer.py
import json

from news_buddy.index_writer import write_index, write_manifest


def test_write_index_creates_json_with_expected_fields(tmp_path):
    items = [
        {
            "title": "Model launches",
            "url": "https://example.test/a",
            "source": "Test Feed",
            "published_at": "2026-07-17",
            "summary": "A new model launched today.",
            "tags": ["ai", "product"],
            "importance": 4,
        }
    ]

    path = write_index(tmp_path, "2026-07-17", items)

    assert path == tmp_path / "2026-07-17.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == items


def test_write_index_defaults_missing_fields(tmp_path):
    path = write_index(tmp_path, "2026-07-17", [{"url": "https://example.test/b"}])

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == [
        {
            "title": "",
            "url": "https://example.test/b",
            "source": "",
            "published_at": "",
            "summary": "",
            "tags": [],
            "importance": 3,
        }
    ]


def test_write_manifest_lists_dates_newest_first(tmp_path):
    write_index(tmp_path, "2026-07-15", [])
    write_index(tmp_path, "2026-07-17", [])
    write_index(tmp_path, "2026-07-16", [])

    path = write_manifest(tmp_path)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"dates": ["2026-07-17", "2026-07-16", "2026-07-15"]}


def test_write_manifest_ignores_non_date_json_files(tmp_path):
    write_index(tmp_path, "2026-07-17", [])
    (tmp_path / "index.json").write_text("{}", encoding="utf-8")
    (tmp_path / "unrelated.json").write_text("{}", encoding="utf-8")

    path = write_manifest(tmp_path)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"dates": ["2026-07-17"]}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_index_writer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'news_buddy.index_writer'`

- [ ] **Step 3: Write the implementation**

```python
# news_buddy/index_writer.py
"""Builds the public search index published alongside the HTML archive."""

from __future__ import annotations

import json
import re
from pathlib import Path

_DATE_JSON_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")


def _to_record(item: dict) -> dict:
    return {
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "source": item.get("source", ""),
        "published_at": item.get("published_at", ""),
        "summary": item.get("summary", ""),
        "tags": item.get("tags") or [],
        "importance": item.get("importance", 3),
    }


def write_index(output_dir: Path, date_str: str, enriched_items: list[dict]) -> Path:
    """Write output_dir/{date_str}.json with one record per article. Atomic write."""
    output_dir.mkdir(parents=True, exist_ok=True)
    records = [_to_record(item) for item in enriched_items]
    target = output_dir / f"{date_str}.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)
    return target


def write_manifest(output_dir: Path) -> Path:
    """Scan output_dir for YYYY-MM-DD.json files and write index.json (newest first)."""
    dated_files = sorted(
        (p.stem for p in output_dir.glob("*.json") if _DATE_JSON_PATTERN.match(p.name)),
        reverse=True,
    )
    target = output_dir / "index.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps({"dates": dated_files}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)
    return target
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_index_writer.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add news_buddy/index_writer.py tests/test_index_writer.py
git commit -m "Add index/manifest writer for the public digest archive"
```

---

### Task 2: Wire the index writer into `write_html_node`

**Files:**
- Modify: `news_buddy/agent.py:527-561` (`write_html_node`)
- Test: `tests/test_write_html_node_index.py`

**Interfaces:**
- Consumes: `write_index(output_dir, date_str, enriched_items) -> Path`, `write_manifest(output_dir) -> Path` from Task 1.
- Produces: no new public interface — `write_html_node` now also writes `{date}.json` (when `enriched_items` is non-empty) and always refreshes `index.json`.

A subtlety in the existing graph: `write_html_node` runs after **both** branches of the pipeline (`write_digest` → `write_html` and `write_empty` → `write_html`, per `news_buddy/agent.py:596-600`). On an empty-digest day, `state["enriched_items"]` stays `[]` (it's only ever populated by `summarize_articles_node`, which is skipped). So the guard for "no index file on empty-digest days" (per the design doc) is simply: only call `write_index` when `enriched_items` is non-empty. `write_manifest` is safe to call unconditionally — it just rescans whatever dated files already exist on disk.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_write_html_node_index.py
import json

from news_buddy.agent import write_html_node


def _base_state(tmp_path, enriched_items):
    return {
        "dry_run": False,
        "date_str": "2026-07-17",
        "config": {"output_dir": str(tmp_path)},
        "enriched_items": enriched_items,
        "verbose": False,
    }


def test_write_html_node_also_writes_search_index(tmp_path):
    state = _base_state(tmp_path, [
        {
            "title": "Model launches",
            "url": "https://example.test/a",
            "source": "Test Feed",
            "published_at": "2026-07-17T09:00:00Z",
            "summary": "A new model launched today.",
            "tags": ["ai"],
            "importance": 5,
        }
    ])

    write_html_node(state)

    index_path = tmp_path / "2026-07-17.json"
    manifest_path = tmp_path / "index.json"
    assert index_path.exists()
    records = json.loads(index_path.read_text(encoding="utf-8"))
    assert records[0]["title"] == "Model launches"
    assert records[0]["importance"] == 5

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest == {"dates": ["2026-07-17"]}


def test_write_html_node_skips_index_file_for_empty_digest(tmp_path):
    state = _base_state(tmp_path, [])

    write_html_node(state)

    assert not (tmp_path / "2026-07-17.json").exists()
    manifest = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert manifest == {"dates": []}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_write_html_node_index.py -v`
Expected: FAIL — no `2026-07-17.json` / `index.json` written (only `.html` files exist)

- [ ] **Step 3: Edit `write_html_node`**

In `news_buddy/agent.py`, the current function (lines 527-561) reads:

```python
def write_html_node(state: DigestState) -> dict:
    """Generate a styled HTML digest page alongside the Markdown file."""
    if state["dry_run"]:
        _log(state, "[dry-run] write_html — skipping")
        return {"html_path": "/tmp/dry-run-digest.html"}

    from news_buddy.html_writer import write_html
    from news_buddy.archive_writer import write_archive
    import re as _re

    output_dir = Path(state["config"].get("output_dir", "~/news")).expanduser()
    date_str = state["date_str"]

    # Discover neighbouring dates for prev/next navigation
    pattern = _re.compile(r"^\d{4}-\d{2}-\d{2}\.html$")
    existing = sorted([p.stem for p in output_dir.glob("*.html") if pattern.match(p.name)])
    try:
        idx = existing.index(date_str)
        prev_date = existing[idx - 1] if idx > 0 else None
        next_date = existing[idx + 1] if idx < len(existing) - 1 else None
    except ValueError:
        # today's file not yet written — it'll be the newest
        prev_date = existing[-1] if existing else None
        next_date = None

    path = write_html(output_dir, date_str, state.get("enriched_items", []),
                      prev_date=prev_date, next_date=next_date)
    _log(state, f"HTML digest written → {path}")

    # Regenerate the archive index to include today
    archive_path = write_archive(output_dir)
    _log(state, f"Archive index updated → {archive_path}")

    return {"html_path": str(path)}
```

Replace it with:

```python
def write_html_node(state: DigestState) -> dict:
    """Generate a styled HTML digest page alongside the Markdown file."""
    if state["dry_run"]:
        _log(state, "[dry-run] write_html — skipping")
        return {"html_path": "/tmp/dry-run-digest.html"}

    from news_buddy.html_writer import write_html
    from news_buddy.archive_writer import write_archive
    from news_buddy.index_writer import write_index, write_manifest
    import re as _re

    output_dir = Path(state["config"].get("output_dir", "~/news")).expanduser()
    date_str = state["date_str"]

    # Discover neighbouring dates for prev/next navigation
    pattern = _re.compile(r"^\d{4}-\d{2}-\d{2}\.html$")
    existing = sorted([p.stem for p in output_dir.glob("*.html") if pattern.match(p.name)])
    try:
        idx = existing.index(date_str)
        prev_date = existing[idx - 1] if idx > 0 else None
        next_date = existing[idx + 1] if idx < len(existing) - 1 else None
    except ValueError:
        # today's file not yet written — it'll be the newest
        prev_date = existing[-1] if existing else None
        next_date = None

    path = write_html(output_dir, date_str, state.get("enriched_items", []),
                      prev_date=prev_date, next_date=next_date)
    _log(state, f"HTML digest written → {path}")

    # Public search index: skip the per-day file on empty-digest days (nothing
    # to search), but always refresh the manifest against whatever's on disk.
    enriched_items = state.get("enriched_items", [])
    if enriched_items:
        write_index(output_dir, date_str, enriched_items)
    write_manifest(output_dir)
    _log(state, "Search index/manifest updated")

    # Regenerate the archive index to include today
    archive_path = write_archive(output_dir)
    _log(state, f"Archive index updated → {archive_path}")

    return {"html_path": str(path)}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_write_html_node_index.py -v`
Expected: 2 passed

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `uv run pytest -q`
Expected: all tests pass (no existing test asserts on `write_html_node`'s exact side effects beyond HTML, so no conflicts expected)

- [ ] **Step 6: Commit**

```bash
git add news_buddy/agent.py tests/test_write_html_node_index.py
git commit -m "Write public search index/manifest alongside each daily HTML digest"
```

---

### Task 3: Deploy the index/manifest files in the daily workflow

**Files:**
- Modify: `.github/workflows/daily-digest.yml` (the "Deploy digest to GitHub Pages" step)

**Interfaces:**
- Consumes: `news_buddy.index_writer.write_manifest` from Task 1 (invoked inline via `uv run python -c ...`, same pattern the step already uses for `news_buddy.archive_writer`).

The deploy step currently only copies `${DATE}.html` into the `gh-pages` staging directory before regenerating the HTML archive index. It needs to also copy today's JSON index (if one was written — empty-digest days won't have one) and regenerate the JSON manifest in the staging directory, the same way it already regenerates `index.html`.

- [ ] **Step 1: Edit the deploy step**

In `.github/workflows/daily-digest.yml`, find:

```yaml
          cp "${NEWS_DIR}/${DATE}.html" "${DEPLOY_DIR}/${DATE}.html"
          uv run python -m news_buddy.archive_writer "$DEPLOY_DIR"
```

Replace with:

```yaml
          cp "${NEWS_DIR}/${DATE}.html" "${DEPLOY_DIR}/${DATE}.html"
          if [ -f "${NEWS_DIR}/${DATE}.json" ]; then
            cp "${NEWS_DIR}/${DATE}.json" "${DEPLOY_DIR}/${DATE}.json"
          fi
          uv run python -c "from pathlib import Path; from news_buddy.index_writer import write_manifest; write_manifest(Path('${DEPLOY_DIR}'))"
          uv run python -m news_buddy.archive_writer "$DEPLOY_DIR"
```

- [ ] **Step 2: Validate the YAML still parses**

Run: `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/daily-digest.yml')); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/daily-digest.yml
git commit -m "Deploy the public search index/manifest alongside the HTML digest"
```

**Note (not automatable — flagging for the user):** The only way to fully exercise this step is a real scheduled or `workflow_dispatch` (with `test_run: false`) run, since `test_run: true` skips the deploy step entirely and the non-test path pushes to the public `gh-pages` branch. Don't trigger a non-test run as part of executing this plan — that's a real publish action the user should decide on and run themselves (see Task 5's deployment checklist, which covers verifying the live output).

---

### Task 4: Backfill script for historical digests

**Files:**
- Create: `scripts/__init__.py` (empty — makes the script importable from tests)
- Create: `scripts/backfill_index.py`
- Test: `tests/test_backfill_index.py`

**Interfaces:**
- Consumes: `news_buddy.html_writer._article_card` (only in the test, to generate realistic fixture markup), `news_buddy.index_writer.write_index` / `write_manifest` from Task 1.
- Produces: `parse_archive_dates(index_html: str) -> list[str]`, `parse_digest_html(html: str) -> list[dict]`, `backfill(base_url: str, output_dir: Path) -> None`.

The parser targets the exact markup `news_buddy/html_writer.py` produces today: each article is
`<article class="article-card ..." data-tags="tag1,tag2">...</article>`, with a `card-title` link, a `card-meta` div (`source <span class="dot">·</span> YYYY-MM-DD`), a `card-summary` paragraph (single-quoted `class` attribute — note the asymmetry with the rest of the markup), and an `aria-label="Importance N of 5"` on the stars span.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_backfill_index.py
from news_buddy.html_writer import _article_card
from scripts.backfill_index import parse_archive_dates, parse_digest_html


def test_parse_archive_dates_extracts_day_links():
    html = (
        '<a href="2026-07-17.html" class="day-row">...</a>'
        '<a href="2026-07-16.html" class="day-row">...</a>'
    )
    assert parse_archive_dates(html) == ["2026-07-17", "2026-07-16"]


def test_parse_digest_html_extracts_full_record_from_real_markup():
    item = {
        "title": "Model launches",
        "url": "https://example.test/a",
        "source": "Test Feed",
        "published_at": "2026-07-17T09:00:00Z",
        "summary": "A new model launched today.",
        "tags": ["ai", "product"],
        "importance": 4,
    }
    html = f"<html><body>{_article_card(item)}</body></html>"

    records = parse_digest_html(html)

    assert records == [
        {
            "title": "Model launches",
            "url": "https://example.test/a",
            "source": "Test Feed",
            "published_at": "2026-07-17",
            "summary": "A new model launched today.",
            "tags": ["ai", "product"],
            "importance": 4,
        }
    ]


def test_parse_digest_html_handles_missing_summary_and_clamps_importance():
    item = {
        "title": "Minor update",
        "url": "https://example.test/b",
        "source": "Test Feed",
        "published_at": "2026-07-16T09:00:00Z",
        "summary": "",
        "tags": [],
        "importance": 0,  # _article_card clamps this to 1 via _stars()
    }
    html = f"<html><body>{_article_card(item)}</body></html>"

    records = parse_digest_html(html)

    assert records[0]["importance"] == 1
    assert records[0]["summary"] == ""
    assert records[0]["tags"] == []


def test_parse_digest_html_returns_empty_list_for_page_with_no_articles():
    assert parse_digest_html("<html><body>No new articles today.</body></html>") == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_backfill_index.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.backfill_index'`

- [ ] **Step 3: Write `scripts/__init__.py`**

```python
```

(empty file)

- [ ] **Step 4: Write the implementation**

```python
# scripts/backfill_index.py
#!/usr/bin/env python3
"""
One-off backfill: build the public search index from already-published
gh-pages HTML digests.

Usage:
    python scripts/backfill_index.py <gh-pages-base-url> <output-dir>

Discovers historical dates from the archive's index.html, fetches each
YYYY-MM-DD.html, parses out article records, and writes YYYY-MM-DD.json +
index.json into <output-dir>. Run once; the caller is responsible for
committing the output into the gh-pages branch (see the plan's deployment
task for the exact git commands).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import httpx

from news_buddy.index_writer import write_index, write_manifest

_DAY_LINK = re.compile(r'href="(\d{4}-\d{2}-\d{2})\.html"')
_ARTICLE = re.compile(
    r'<article class="article-card[^"]*" data-tags="([^"]*)">(.*?)</article>',
    re.S,
)
_TITLE = re.compile(r'<a href="([^"]+)"[^>]*class="card-title">([^<]*)</a>')
_META_SOURCE = re.compile(r'<div class="card-meta">([^<]*)')
_META_DATE = re.compile(r'<span class="dot">·</span>\s*(\d{4}-\d{2}-\d{2})')
_SUMMARY = re.compile(r"<p class='card-summary'>(.*?)</p>", re.S)
_IMPORTANCE = re.compile(r'aria-label="Importance (\d) of 5"')


def parse_archive_dates(index_html: str) -> list[str]:
    """Extract YYYY-MM-DD dates linked from the archive's index.html, in document order."""
    return _DAY_LINK.findall(index_html)


def parse_digest_html(html: str) -> list[dict]:
    """Parse article records out of one day's rendered digest HTML."""
    records: list[dict] = []
    for tags_csv, block in _ARTICLE.findall(html):
        title_m = _TITLE.search(block)
        if not title_m:
            continue
        url, title = title_m.group(1), title_m.group(2)

        source_m = _META_SOURCE.search(block)
        source = source_m.group(1).strip() if source_m else ""

        date_m = _META_DATE.search(block)
        published_at = date_m.group(1) if date_m else ""

        summary_m = _SUMMARY.search(block)
        summary = summary_m.group(1).strip() if summary_m else ""

        importance_m = _IMPORTANCE.search(block)
        importance = int(importance_m.group(1)) if importance_m else 3

        records.append({
            "title": title,
            "url": url,
            "source": source,
            "published_at": published_at,
            "summary": summary,
            "tags": [t for t in tags_csv.split(",") if t],
            "importance": importance,
        })
    return records


def backfill(base_url: str, output_dir: Path) -> None:
    base_url = base_url.rstrip("/")
    with httpx.Client(timeout=30) as client:
        index_resp = client.get(f"{base_url}/index.html")
        index_resp.raise_for_status()
        dates = parse_archive_dates(index_resp.text)
        print(f"Found {len(dates)} archived digests", file=sys.stderr)

        for date_str in dates:
            resp = client.get(f"{base_url}/{date_str}.html")
            resp.raise_for_status()
            records = parse_digest_html(resp.text)
            write_index(output_dir, date_str, records)
            print(f"  {date_str}: {len(records)} articles", file=sys.stderr)

    write_manifest(output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="Published gh-pages base URL, e.g. https://user.github.io/repo")
    parser.add_argument("output_dir", help="Local directory to write JSON files into")
    args = parser.parse_args()
    backfill(args.base_url, Path(args.output_dir))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_backfill_index.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add scripts/__init__.py scripts/backfill_index.py tests/test_backfill_index.py
git commit -m "Add one-off backfill script for the public search index"
```

**Manual step (not automatable — requires the user's own gh-pages push, run once):**

```bash
uv run python scripts/backfill_index.py https://<user>.github.io/<repo> /tmp/nb-backfill

cd /tmp/nb-backfill-checkout   # a fresh clone of the gh-pages branch
cp /tmp/nb-backfill/*.json .
git add *.json
git commit -m "Backfill public search index for historical digests"
git push origin gh-pages
```

Ask the user to confirm the real archive URL and run this themselves (or explicitly authorize it) — it pushes directly to the public `gh-pages` branch.

---

### Task 5: `news_buddy_mcp` package scaffold + archive index client

**Files:**
- Create: `news_buddy_mcp/pyproject.toml`
- Create: `news_buddy_mcp/src/news_buddy_mcp/__init__.py`
- Create: `news_buddy_mcp/src/news_buddy_mcp/index_client.py`
- Create: `news_buddy_mcp/tests/test_index_client.py`

**Interfaces:**
- Produces: `ArchiveIndexClient(base_url: str, ttl_seconds: int = 3600, client: httpx.Client | None = None)` with methods `.manifest() -> tuple[list[str], bool]` and `.day(date_str: str) -> tuple[list[dict] | None, bool]`. Both return `(data, stale)`; `stale=True` means the fetch failed and a cached copy was served instead. `.day()` returns `(None, False)` for a date that plainly doesn't exist (a 404) but re-raises any other error when there's no cache to fall back on.

- [ ] **Step 1: Scaffold the project files**

```toml
# news_buddy_mcp/pyproject.toml
[project]
name = "news-buddy-mcp"
version = "0.1.0"
description = "Public read-only MCP server over the News Buddy digest archive"
requires-python = ">=3.11"
dependencies = [
    "fastmcp>=2.3",
    "httpx",
]

[dependency-groups]
dev = [
    "pytest",
    "ruff",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/news_buddy_mcp"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

```python
# news_buddy_mcp/src/news_buddy_mcp/__init__.py
"""News Buddy MCP server: read-only tools over the public digest archive."""
```

Run: `cd news_buddy_mcp && uv lock`
Expected: creates `news_buddy_mcp/uv.lock`

- [ ] **Step 2: Write the failing tests**

```python
# news_buddy_mcp/tests/test_index_client.py
import httpx
import pytest

from news_buddy_mcp.index_client import ArchiveIndexClient


def _client_with_responses(responses: dict[str, httpx.Response]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.lstrip("/")
        if path in responses:
            return responses[path]
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_manifest_returns_dates_from_index_json():
    client = _client_with_responses({
        "index.json": httpx.Response(200, json={"dates": ["2026-07-17", "2026-07-16"]}),
    })
    archive = ArchiveIndexClient("https://example.test", client=client)

    dates, stale = archive.manifest()

    assert dates == ["2026-07-17", "2026-07-16"]
    assert stale is False


def test_manifest_serves_stale_cache_on_fetch_failure():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={"dates": ["2026-07-17"]})
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    archive = ArchiveIndexClient("https://example.test", ttl_seconds=0, client=client)

    first_dates, first_stale = archive.manifest()
    second_dates, second_stale = archive.manifest()

    assert first_dates == ["2026-07-17"]
    assert first_stale is False
    assert second_dates == ["2026-07-17"]
    assert second_stale is True


def test_manifest_raises_when_no_cache_and_fetch_fails():
    client = _client_with_responses({})  # everything 404s

    archive = ArchiveIndexClient("https://example.test", client=client)

    with pytest.raises(httpx.HTTPStatusError):
        archive.manifest()


def test_day_returns_none_for_missing_date():
    client = _client_with_responses({
        "index.json": httpx.Response(200, json={"dates": []}),
    })
    archive = ArchiveIndexClient("https://example.test", client=client)

    records, stale = archive.day("2026-01-01")

    assert records is None
    assert stale is False


def test_day_returns_records_for_existing_date():
    client = _client_with_responses({
        "2026-07-17.json": httpx.Response(200, json=[{"title": "X"}]),
    })
    archive = ArchiveIndexClient("https://example.test", client=client)

    records, stale = archive.day("2026-07-17")

    assert records == [{"title": "X"}]
    assert stale is False
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd news_buddy_mcp && uv sync --frozen --dev && uv run pytest -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'news_buddy_mcp.index_client'`

- [ ] **Step 4: Write the implementation**

```python
# news_buddy_mcp/src/news_buddy_mcp/index_client.py
"""Fetches and caches the public digest archive index from gh-pages."""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

_DEFAULT_TTL_SECONDS = 3600


@dataclass
class _CacheEntry:
    data: object
    fetched_at: float


class ArchiveIndexClient:
    """Reads index.json and per-day JSON files from the published archive.

    Caches responses in memory for ttl_seconds. On fetch failure, serves the
    last good cached copy (marking it stale) rather than raising, unless
    there's no cache yet, in which case the original error propagates.
    """

    def __init__(
        self,
        base_url: str,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._ttl = ttl_seconds
        self._client = client or httpx.Client(timeout=15)
        self._cache: dict[str, _CacheEntry] = {}

    def _get_json(self, path: str) -> tuple[object, bool]:
        now = time.monotonic()
        cached = self._cache.get(path)
        if cached and now - cached.fetched_at < self._ttl:
            return cached.data, False

        try:
            resp = self._client.get(f"{self._base_url}/{path}")
            resp.raise_for_status()
            data = resp.json()
            self._cache[path] = _CacheEntry(data=data, fetched_at=now)
            return data, False
        except (httpx.HTTPError, ValueError):
            if cached:
                return cached.data, True
            raise

    def manifest(self) -> tuple[list[str], bool]:
        data, stale = self._get_json("index.json")
        return data.get("dates", []), stale

    def day(self, date_str: str) -> tuple[list[dict] | None, bool]:
        try:
            return self._get_json(f"{date_str}.json")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None, False
            raise
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd news_buddy_mcp && uv run pytest -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add news_buddy_mcp/
git commit -m "Scaffold news_buddy_mcp package with archive index client"
```

---

### Task 6: MCP tool handlers (`search_articles`, `get_digest`, `list_digests`)

**Files:**
- Create: `news_buddy_mcp/src/news_buddy_mcp/server.py`
- Create: `news_buddy_mcp/tests/test_server.py`

**Interfaces:**
- Consumes: `ArchiveIndexClient` from Task 5 (`.manifest()`, `.day()`).
- Produces: `create_server(archive: ArchiveIndexClient) -> FastMCP` (registers the three tools), plus the underlying pure functions `_search_articles`, `_get_digest`, `_list_digests` used directly in tests, and `main()` as the process entry point.

The tool logic is written as plain functions taking an `ArchiveIndexClient` (or test double) as their first argument, then wrapped as FastMCP tools inside `create_server`. This keeps the tests free of any FastMCP or network dependency.

- [ ] **Step 1: Write the failing tests**

```python
# news_buddy_mcp/tests/test_server.py
from news_buddy_mcp.server import _get_digest, _list_digests, _search_articles


class _FakeArchive:
    def __init__(self, manifest_dates, days, manifest_stale=False, day_stale=False, fail_manifest=False):
        self._dates = manifest_dates
        self._days = days
        self._manifest_stale = manifest_stale
        self._day_stale = day_stale
        self._fail_manifest = fail_manifest

    def manifest(self):
        if self._fail_manifest:
            raise RuntimeError("manifest fetch failed")
        return self._dates, self._manifest_stale

    def day(self, date_str):
        if date_str not in self._days:
            return None, False
        return self._days[date_str], self._day_stale


_DAY_A = [
    {"title": "Model launches", "url": "https://example.test/a", "source": "Test Feed",
     "published_at": "2026-07-17", "summary": "A new model launched.", "tags": ["ai"], "importance": 5},
    {"title": "Weather update", "url": "https://example.test/b", "source": "Other Feed",
     "published_at": "2026-07-17", "summary": "Sunny today.", "tags": ["world"], "importance": 2},
]


def test_search_articles_matches_title_and_summary_case_insensitively():
    archive = _FakeArchive(["2026-07-17"], {"2026-07-17": _DAY_A})

    result = _search_articles(archive, "model launches", None, None, None, 20)

    assert result["count"] == 1
    assert result["results"][0]["url"] == "https://example.test/a"


def test_search_articles_filters_by_source():
    archive = _FakeArchive(["2026-07-17"], {"2026-07-17": _DAY_A})

    result = _search_articles(archive, "", "Other Feed", None, None, 20)

    assert result["count"] == 1
    assert result["results"][0]["url"] == "https://example.test/b"


def test_search_articles_filters_by_date_range():
    days = {"2026-07-16": _DAY_A, "2026-07-17": _DAY_A}
    archive = _FakeArchive(["2026-07-17", "2026-07-16"], days)

    result = _search_articles(archive, "", None, "2026-07-17", "2026-07-17", 20)

    assert result["count"] == 2
    assert all(r["date"] == "2026-07-17" for r in result["results"])


def test_search_articles_returns_error_when_manifest_fetch_fails():
    archive = _FakeArchive([], {}, fail_manifest=True)

    result = _search_articles(archive, "model", None, None, None, 20)

    assert "error" in result


def test_get_digest_returns_articles_for_known_date():
    archive = _FakeArchive(["2026-07-17"], {"2026-07-17": _DAY_A})

    result = _get_digest(archive, "2026-07-17")

    assert result["count"] == 2
    assert result["articles"] == _DAY_A


def test_get_digest_returns_explicit_error_for_unknown_date():
    archive = _FakeArchive(["2026-07-17"], {"2026-07-17": _DAY_A})

    result = _get_digest(archive, "1999-01-01")

    assert result == {"error": "no digest for 1999-01-01"}


def test_list_digests_returns_counts_per_date():
    archive = _FakeArchive(["2026-07-17", "2026-07-16"], {"2026-07-17": _DAY_A, "2026-07-16": []})

    result = _list_digests(archive, 30)

    assert result["digests"] == [
        {"date": "2026-07-17", "article_count": 2},
        {"date": "2026-07-16", "article_count": 0},
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd news_buddy_mcp && uv run pytest tests/test_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'news_buddy_mcp.server'`

- [ ] **Step 3: Write the implementation**

```python
# news_buddy_mcp/src/news_buddy_mcp/server.py
"""FastMCP server exposing read-only tools over the public digest archive."""

from __future__ import annotations

import os

from fastmcp import FastMCP

from news_buddy_mcp.index_client import ArchiveIndexClient


def _matches(record: dict, words: list[str]) -> bool:
    haystack = f"{record.get('title', '')} {record.get('summary', '')}".lower()
    return all(w in haystack for w in words)


def _search_articles(
    archive: ArchiveIndexClient,
    query: str,
    source: str | None,
    from_date: str | None,
    to_date: str | None,
    limit: int,
) -> dict:
    limit = max(1, min(limit, 100))
    words = [w.lower() for w in query.strip().split() if w]

    try:
        dates, stale = archive.manifest()
    except Exception as exc:
        return {"error": f"could not load archive manifest: {exc}"}

    dates = [d for d in dates if (not from_date or d >= from_date) and (not to_date or d <= to_date)]

    matches: list[dict] = []
    for date_str in dates:
        try:
            records, _ = archive.day(date_str)
        except Exception:
            continue
        if not records:
            continue
        for record in records:
            if source and source.lower() not in record.get("source", "").lower():
                continue
            if words and not _matches(record, words):
                continue
            matches.append({**record, "date": date_str})

    matches.sort(key=lambda r: r.get("importance", 3), reverse=True)
    truncated = len(matches) > limit
    return {
        "query": query,
        "count": min(len(matches), limit),
        "total_matches": len(matches),
        "truncated": truncated,
        "stale": stale,
        "results": matches[:limit],
    }


def _get_digest(archive: ArchiveIndexClient, date: str) -> dict:
    try:
        records, stale = archive.day(date)
    except Exception as exc:
        return {"error": f"could not load digest for {date}: {exc}"}

    if records is None:
        return {"error": f"no digest for {date}"}

    return {"date": date, "stale": stale, "count": len(records), "articles": records}


def _list_digests(archive: ArchiveIndexClient, limit: int) -> dict:
    limit = max(1, min(limit, 100))
    try:
        dates, stale = archive.manifest()
    except Exception as exc:
        return {"error": f"could not load archive manifest: {exc}"}

    entries = []
    for date_str in dates[:limit]:
        try:
            records, _ = archive.day(date_str)
        except Exception:
            records = None
        entries.append({"date": date_str, "article_count": len(records) if records else 0})

    return {"stale": stale, "count": len(entries), "digests": entries}


def create_server(archive: ArchiveIndexClient) -> FastMCP:
    mcp = FastMCP("News Buddy Archive")

    @mcp.tool()
    def search_articles(
        query: str,
        source: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 20,
    ) -> dict:
        """Keyword-search past digest articles by title and summary text.

        query: space-separated words, all must match (case-insensitive).
        source: optional source feed name filter (case-insensitive substring).
        from_date/to_date: optional YYYY-MM-DD bounds, inclusive.
        limit: max results to return (1-100).
        """
        return _search_articles(archive, query, source, from_date, to_date, limit)

    @mcp.tool()
    def get_digest(date: str) -> dict:
        """Return every article from the digest published on the given date (YYYY-MM-DD)."""
        return _get_digest(archive, date)

    @mcp.tool()
    def list_digests(limit: int = 30) -> dict:
        """List the most recent available digest dates with article counts."""
        return _list_digests(archive, limit)

    return mcp


def main() -> None:
    archive_url = os.environ["NEWS_BUDDY_ARCHIVE_URL"]
    port = int(os.environ.get("PORT", "8000"))
    server = create_server(ArchiveIndexClient(archive_url))
    server.run(transport="http", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd news_buddy_mcp && uv run pytest tests/test_server.py -v`
Expected: 7 passed

- [ ] **Step 5: Run the whole `news_buddy_mcp` test suite**

Run: `cd news_buddy_mcp && uv run pytest -v`
Expected: 12 passed (5 from Task 5 + 7 from this task)

- [ ] **Step 6: Commit**

```bash
git add news_buddy_mcp/
git commit -m "Add search_articles, get_digest, list_digests MCP tools"
```

---

### Task 7: Dockerfile, CI job, and root pytest scoping

**Files:**
- Create: `news_buddy_mcp/Dockerfile`
- Modify: `.github/workflows/ci.yml` (add a second job)
- Modify: `pyproject.toml` (root — scope pytest to `tests/`)

**Interfaces:** none new — this task only adds deployment/CI plumbing around Tasks 5-6.

Root `pytest -q` currently has no `testpaths` configured, so it would try to discover and import tests under `news_buddy_mcp/tests/` too — which needs `fastmcp`/`httpx` installed under *its own* `uv` environment, not the root one. Scoping root pytest to `tests/` keeps the two projects' test runs independent, matching how `news_buddy_mcp` is a separate `uv` project per the design doc.

- [ ] **Step 1: Scope root pytest to `tests/`**

In `pyproject.toml` (repo root), add after the `[tool.hatch.build.targets.wheel]` section:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Verify root test discovery is unaffected**

Run: `uv run pytest -q`
Expected: same pass count as before this task (only `tests/` is collected; `news_buddy_mcp/tests/` is not touched)

- [ ] **Step 3: Write the Dockerfile**

```dockerfile
# news_buddy_mcp/Dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
COPY src ./src

RUN uv sync --frozen --no-dev

ENV PORT=8000
EXPOSE 8000

CMD ["uv", "run", "python", "-m", "news_buddy_mcp.server"]
```

- [ ] **Step 4: Add a CI job for `news_buddy_mcp`**

In `.github/workflows/ci.yml`, add a second job alongside the existing `test` job:

```yaml
  mcp-server:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    defaults:
      run:
        working-directory: news_buddy_mcp
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Set up uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Install locked dependencies
        run: uv sync --frozen --dev

      - name: Lint
        run: uv run ruff check .

      - name: Test
        run: uv run pytest -q
```

- [ ] **Step 5: Validate both YAML files parse**

Run: `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('OK')"`
Expected: `OK`

- [ ] **Step 6: Lint both projects locally**

Run: `uv run ruff check .`
Expected: passes (root project)

Run: `cd news_buddy_mcp && uv run ruff check .`
Expected: passes

- [ ] **Step 7: Commit**

```bash
git add news_buddy_mcp/Dockerfile .github/workflows/ci.yml pyproject.toml
git commit -m "Add Docker image and CI job for news_buddy_mcp"
```

---

### Task 8: Deploy and connect (manual — requires the user's action)

This task has no automated tests; it's a checklist of real-world actions that create an account, push to a public branch, and stand up a public endpoint. Per the project's safety rules, these require the user's explicit action or confirmation rather than autonomous execution:

- [ ] Confirm the real gh-pages base URL (e.g. `https://<user>.github.io/<repo>`) — this is the value `NEWS_BUDDY_ARCHIVE_URL` will be set to.
- [ ] Create a Render account (or confirm FastMCP Cloud's current free tier is a better fit — check at implementation time) and create a new Web Service pointing at `news_buddy_mcp/Dockerfile` in this repo.
- [ ] Set the `NEWS_BUDDY_ARCHIVE_URL` environment variable on the hosted service to the URL confirmed above.
- [ ] Deploy and note the resulting public HTTPS URL.
- [ ] Run the Task 4 backfill script against the real archive and push the results to `gh-pages` (see Task 4's manual step) — ask the user to run this or explicitly authorize it, since it's a real push to a public branch.
- [ ] Trigger the daily workflow once via `workflow_dispatch` with `test_run: false` (ask the user to do this, or get explicit confirmation first — it deploys to the public `gh-pages` branch) to confirm Task 3's deploy-step changes work against the real pipeline output.
- [ ] Add the hosted MCP URL as a connector in a real Claude Desktop or Claude Code session and manually verify:
  - `list_digests` returns real recent dates.
  - `get_digest` for a real date returns real articles; for a made-up date (e.g. `1999-01-01`) returns `{"error": "no digest for 1999-01-01"}`.
  - `search_articles` with a real keyword returns matching results; with a nonsense keyword returns `count: 0`.

No commit is expected from this task — it's operational, not code.

---

## Self-Review Notes

- **Spec coverage:** index/manifest writer (Task 1), pipeline wiring incl. the empty-digest guard (Task 2), deploy step (Task 3), backfill script and one-time run (Task 4), `ArchiveIndexClient` with stale-cache behavior (Task 5), all three MCP tools with the exact error-handling behavior from the design doc (Task 6), Dockerfile/CI/deployment (Tasks 7-8). No spec section is unaddressed.
- **Placeholder scan:** no TBDs; every step has real code, real commands, and real expected output.
- **Type consistency:** `ArchiveIndexClient.manifest()`/`.day()` return `(data, stale)` tuples consistently between Task 5's implementation, Task 6's tool handlers, and both tasks' tests. Article record shape (`title/url/source/published_at/summary/tags/importance`) is identical across `index_writer._to_record`, the backfill parser's output, and the fake archive fixtures in `test_server.py`.
