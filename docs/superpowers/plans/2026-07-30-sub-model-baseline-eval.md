# Sub-Model Baseline Evaluation Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an opt-in harness that measures how the digest's `sub_model` actually performs, so a model change can be decided on evidence rather than intuition.

**Architecture:** A standalone script, `scripts/eval_sub_model.py`, with two modes. `--capture` snapshots ~25 real articles from the published archive into a gitignored fixture file plus a committed hash manifest. `--run` drives the real production path — `_summarize_one` with a patched body source — across several candidate models, scores results with the pipeline's own `RubricMiddleware` and `_article_brief_errors`, and writes a markdown report. Pure logic lives in importable modules with real pytest coverage; only the runner touches the network.

**Tech Stack:** Python 3.11, `uv`, pytest, `httpx` (already a dependency), NVIDIA NIM via the existing `news_buddy.llm` adapter. No new third-party packages.

## Global Constraints

- No runtime behavior change. `news_buddy/`, `news_buddy_mcp/`, `config.yaml`, and `prompts/` must not be modified by any task.
- The harness runs under production settings: `max_tokens: 512`, `temperature: 0.2`, the real prompts from `prompts/summarizer.md`.
- Article bodies are never committed. `scripts/eval_fixtures/articles.json` is gitignored; `scripts/eval_fixtures/manifest.json` is committed.
- Corpus size is 25 articles.
- Network-touching code is opt-in and never runs in CI. Every pytest test added here must pass with no network access.
- Baseline model: `meta/llama-3.1-8b-instruct`. Candidates: `nvidia/nemotron-3-super-120b-a12b`, `poolside/laguna-xs-2.1`, `mistralai/mistral-medium-3.5-128b`, `google/gemma-4-31b-it`.
- Existing suites stay green: `uv run pytest` and `uv run ruff check .`.
- Published archive base URL: `https://harshagarwal06.github.io/buddy_agent/`.

## File Structure

| File | Responsibility |
| --- | --- |
| `scripts/eval_fixtures/__init__.py` | Package marker so fixture code is importable by tests. |
| `scripts/eval_fixtures/manifest.json` | Committed. One record per fixture article: url, title, source, body SHA-256, captured_at. |
| `scripts/eval_fixtures/articles.json` | Gitignored. Same articles plus `body`. |
| `scripts/eval_store.py` | Fixture load/save, SHA-256 hashing, manifest verification. No network. |
| `scripts/eval_scoring.py` | Per-article record construction, failure classification, aggregation. No network. |
| `scripts/eval_report.py` | Markdown rendering of aggregates and samples. No network. |
| `scripts/eval_sub_model.py` | CLI: `--capture` and `--run`. The only file that touches the network. |
| `tests/test_eval_store.py` | Hash verification, mismatch abort, round-trip. |
| `tests/test_eval_scoring.py` | Classification and aggregation arithmetic. |
| `tests/test_eval_report.py` | Report formatting, zero-row and unavailable-model cases. |

Splitting store / scoring / report from the CLI is what makes real test coverage possible: three of the four modules are pure functions over plain dicts, so CI exercises all the logic while the network stays out of it.

---

### Task 1: Fixture store and manifest verification

**Files:**
- Create: `scripts/eval_fixtures/__init__.py`
- Create: `scripts/eval_store.py`
- Create: `tests/test_eval_store.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `body_sha256(body: str) -> str`
  - `Article` (TypedDict): `url: str`, `title: str`, `source: str`, `published_at: str`, `body: str`
  - `save_fixtures(dir: Path, articles: list[dict]) -> tuple[Path, Path]` — writes `articles.json` and `manifest.json`, returns both paths
  - `load_fixtures(dir: Path) -> list[dict]` — loads and verifies; raises `FixtureError` on mismatch
  - `FixtureError(RuntimeError)`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eval_store.py`:

```python
import json

import pytest

from scripts.eval_store import (
    FixtureError,
    body_sha256,
    load_fixtures,
    save_fixtures,
)


def _article(url: str = "https://example.com/a", body: str = "body text") -> dict:
    return {
        "url": url,
        "title": "A Title",
        "source": "Example",
        "published_at": "2026-07-30",
        "body": body,
    }


def test_body_sha256_is_stable_and_content_dependent():
    assert body_sha256("abc") == body_sha256("abc")
    assert body_sha256("abc") != body_sha256("abd")


def test_save_writes_bodies_only_to_articles_file(tmp_path):
    articles_path, manifest_path = save_fixtures(tmp_path, [_article()])

    articles = json.loads(articles_path.read_text())
    manifest = json.loads(manifest_path.read_text())

    assert articles[0]["body"] == "body text"
    assert "body" not in manifest["articles"][0]
    assert manifest["articles"][0]["body_sha256"] == body_sha256("body text")
    assert manifest["articles"][0]["url"] == "https://example.com/a"


def test_round_trip_returns_articles(tmp_path):
    save_fixtures(tmp_path, [_article()])
    assert load_fixtures(tmp_path) == [_article()]


def test_load_rejects_body_that_does_not_match_manifest(tmp_path):
    articles_path, _ = save_fixtures(tmp_path, [_article()])
    tampered = json.loads(articles_path.read_text())
    tampered[0]["body"] = "different text"
    articles_path.write_text(json.dumps(tampered))

    with pytest.raises(FixtureError, match="does not match"):
        load_fixtures(tmp_path)


def test_load_rejects_article_missing_from_manifest(tmp_path):
    articles_path, _ = save_fixtures(tmp_path, [_article()])
    extra = json.loads(articles_path.read_text())
    extra.append(_article(url="https://example.com/b"))
    articles_path.write_text(json.dumps(extra))

    with pytest.raises(FixtureError, match="not in the manifest"):
        load_fixtures(tmp_path)


def test_load_reports_missing_articles_file(tmp_path):
    save_fixtures(tmp_path, [_article()])
    (tmp_path / "articles.json").unlink()

    with pytest.raises(FixtureError, match="--capture"):
        load_fixtures(tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_eval_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.eval_store'`

- [ ] **Step 3: Write the implementation**

Create `scripts/eval_fixtures/__init__.py` as an empty file.

Create `scripts/eval_store.py`:

```python
"""Frozen article fixtures for sub_model evaluation.

Bodies are third-party article text and are never committed. `articles.json`
is gitignored; `manifest.json` records a SHA-256 per body so a re-capture can
be checked against the original.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ARTICLES_FILE = "articles.json"
MANIFEST_FILE = "manifest.json"

_FIELDS = ("url", "title", "source", "published_at", "body")


class FixtureError(RuntimeError):
    """Raised when fixtures are missing or disagree with the manifest."""


def body_sha256(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def save_fixtures(directory: Path, articles: list[dict]) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    rows = [{field: article.get(field, "") for field in _FIELDS} for article in articles]

    manifest = {
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "articles": [
            {
                "url": row["url"],
                "title": row["title"],
                "source": row["source"],
                "published_at": row["published_at"],
                "body_sha256": body_sha256(row["body"]),
            }
            for row in rows
        ],
    }

    articles_path = directory / ARTICLES_FILE
    manifest_path = directory / MANIFEST_FILE
    articles_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return articles_path, manifest_path


def load_fixtures(directory: Path) -> list[dict]:
    articles_path = directory / ARTICLES_FILE
    manifest_path = directory / MANIFEST_FILE

    if not manifest_path.exists():
        raise FixtureError(f"{manifest_path} is missing; it should be committed.")
    if not articles_path.exists():
        raise FixtureError(
            f"{articles_path} is missing. Article bodies are not committed — "
            "regenerate them with: python -m scripts.eval_sub_model --capture"
        )

    rows = json.loads(articles_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {entry["url"]: entry["body_sha256"] for entry in manifest["articles"]}

    for row in rows:
        url = row.get("url", "")
        if url not in expected:
            raise FixtureError(f"fixture {url!r} is not in the manifest; re-capture.")
        actual = body_sha256(row.get("body", ""))
        if actual != expected[url]:
            raise FixtureError(
                f"fixture body for {url!r} does not match the manifest "
                f"(expected {expected[url][:12]}, got {actual[:12]}); re-capture."
            )
    return rows
```

Append to `.gitignore`:

```
# Evaluation fixtures: third-party article bodies, regenerable via --capture
scripts/eval_fixtures/articles.json
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_eval_store.py -v`
Expected: PASS, 6 passed

- [ ] **Step 5: Confirm the gitignore rule works**

Run: `git check-ignore -v scripts/eval_fixtures/articles.json`
Expected: a line naming `.gitignore` and the new pattern. If it prints nothing, the rule is wrong — fix before committing.

- [ ] **Step 6: Commit**

```bash
git add scripts/eval_store.py scripts/eval_fixtures/__init__.py tests/test_eval_store.py .gitignore
git commit -m "feat: add evaluation fixture store with manifest verification"
```

---

### Task 2: Per-article records, failure classification, aggregation

**Files:**
- Create: `scripts/eval_scoring.py`
- Create: `tests/test_eval_scoring.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `ArticleResult` (dataclass): `url: str`, `title: str`, `ok: bool`, `summary: str`, `rubric_passed: bool`, `brief_errors: list[str]`, `json_failure: bool`, `total_tokens: int`, `latency_s: float`, `word_count: int`, `error: str`
  - `classify_failure(brief_errors: list[str]) -> bool` — True when the pattern is the JSON-failure signature
  - `success_result(...) -> ArticleResult` and `failure_result(...) -> ArticleResult`
  - `ModelAggregate` (dataclass): `model`, `available`, `unavailable_reason`, `article_count`, `brief_valid_rate`, `first_pass_rate`, `strict_recovery_rate`, `json_failure_count`, `field_failures: dict[str, int]`, `p50_latency`, `p95_latency`, `mean_total_tokens`, `word_count_in_range_rate`
  - `aggregate(model: str, results: list[ArticleResult], strict_results: list[ArticleResult]) -> ModelAggregate`
  - `unavailable(model: str, reason: str) -> ModelAggregate`

**Correction to the spec.** The spec lists "output tokens and cap hits" as a metric and makes "zero token-cap hits" a decision criterion. That is not measurable here: `_summarize_one` returns `input_tokens + output_tokens` as a single sum, so there is no output-token figure to compare against the 512 output cap — the total is routinely above 512 because the prompt alone exceeds it, and every article would falsely register a cap hit.

Truncation is still detected, just indirectly: a response cut off at the cap is invalid JSON, which surfaces as a JSON failure. So the plan reports mean **total** tokens, drops `cap_hits`, and the decision criterion becomes **zero JSON failures**. Measuring output tokens directly would need a runtime seam, which this work excludes.

The four image-brief field names come from `_article_brief_errors` in `news_buddy/image_generator.py`: `image_prompt`, `image_layout`, `image_labels`, `image_alt`. That function can also emit `short image_labels` and `article-specific image_labels`, which are brief-quality failures, not JSON failures.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eval_scoring.py`:

```python
from scripts.eval_scoring import (
    aggregate,
    classify_failure,
    failure_result,
    success_result,
    unavailable,
)

_JSON_SIGNATURE = ["image_prompt", "image_layout", "image_labels", "image_alt"]


def _ok(url="u", tokens=900, latency=1.0, passed=True, words=90):
    return success_result(
        url=url, title="T", summary="s" * 10, rubric_passed=passed,
        total_tokens=tokens, latency_s=latency, word_count=words,
    )


def test_all_four_fields_missing_is_the_json_signature():
    assert classify_failure(_JSON_SIGNATURE) is True


def test_subset_failure_is_not_a_json_failure():
    assert classify_failure(["image_layout"]) is False
    assert classify_failure(["image_prompt", "image_alt"]) is False


def test_label_quality_failure_is_not_a_json_failure():
    assert classify_failure(["short image_labels"]) is False
    assert classify_failure(["article-specific image_labels"]) is False


def test_empty_errors_is_not_a_failure():
    assert classify_failure([]) is False


def test_failure_result_records_errors_and_flags_json():
    result = failure_result(
        url="u", title="T", brief_errors=_JSON_SIGNATURE,
        error="bad brief", latency_s=2.0,
    )
    assert result.ok is False
    assert result.json_failure is True
    assert result.rubric_passed is False


def test_aggregate_computes_rates():
    results = [_ok(passed=True), _ok(passed=False), failure_result(
        url="c", title="T", brief_errors=["image_layout"], error="e", latency_s=1.0
    )]
    agg = aggregate("m", results, strict_results=[])

    assert agg.article_count == 3
    assert round(agg.brief_valid_rate, 3) == round(2 / 3, 3)
    assert round(agg.first_pass_rate, 3) == round(1 / 3, 3)
    assert agg.field_failures == {"image_layout": 1}
    assert agg.json_failure_count == 0


def test_aggregate_counts_inferred_json_failures():
    results = [
        failure_result(url="a", title="T", brief_errors=_JSON_SIGNATURE, error="e", latency_s=1.0),
        failure_result(url="b", title="T", brief_errors=["image_alt"], error="e", latency_s=1.0),
    ]
    agg = aggregate("m", results, [])
    assert agg.json_failure_count == 1


def test_aggregate_reports_mean_total_tokens():
    agg = aggregate("m", [_ok(tokens=800), _ok(tokens=1000)], [])
    assert agg.mean_total_tokens == 900.0


def test_strict_recovery_rate_is_share_of_retried_that_pass():
    strict = [_ok(url="a", passed=True), _ok(url="b", passed=False)]
    agg = aggregate("m", [_ok(passed=False)], strict)
    assert agg.strict_recovery_rate == 0.5


def test_strict_recovery_rate_is_none_when_nothing_retried():
    agg = aggregate("m", [_ok(passed=True)], [])
    assert agg.strict_recovery_rate is None


def test_percentiles_on_single_result_do_not_crash():
    agg = aggregate("m", [_ok(latency=2.5)], [])
    assert agg.p50_latency == 2.5
    assert agg.p95_latency == 2.5


def test_aggregate_of_no_results_is_all_zero_not_a_crash():
    agg = aggregate("m", [], [])
    assert agg.article_count == 0
    assert agg.brief_valid_rate == 0.0
    assert agg.p50_latency == 0.0


def test_unavailable_model_carries_reason():
    agg = unavailable("m", "HTTP 404")
    assert agg.available is False
    assert agg.unavailable_reason == "HTTP 404"
    assert agg.article_count == 0


def test_word_count_in_range_uses_the_prompt_target():
    agg = aggregate("m", [_ok(words=90), _ok(words=40)], [])
    assert agg.word_count_in_range_rate == 0.5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_eval_scoring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.eval_scoring'`

- [ ] **Step 3: Write the implementation**

Create `scripts/eval_scoring.py`:

```python
"""Scoring and aggregation for sub_model evaluation. Pure functions, no network."""

from __future__ import annotations

from dataclasses import dataclass, field

# prompts/summarizer.md asks for a 70-110 word briefing.
WORD_TARGET = (70, 110)

# _article_brief_errors emits one entry per missing image field. When JSON
# parsing fails, _summarize_one substitutes a fallback dict with no image
# fields at all, so every one of these appears together.
_JSON_FAILURE_SIGNATURE = frozenset(
    {"image_prompt", "image_layout", "image_labels", "image_alt"}
)


@dataclass
class ArticleResult:
    url: str
    title: str
    ok: bool
    summary: str = ""
    rubric_passed: bool = False
    brief_errors: list[str] = field(default_factory=list)
    json_failure: bool = False
    # _summarize_one returns input + output tokens as one sum; there is no
    # separate output figure, so cap hits cannot be measured. Truncation shows
    # up as a JSON failure instead.
    total_tokens: int = 0
    latency_s: float = 0.0
    word_count: int = 0
    error: str = ""


@dataclass
class ModelAggregate:
    model: str
    available: bool = True
    unavailable_reason: str = ""
    article_count: int = 0
    brief_valid_rate: float = 0.0
    first_pass_rate: float = 0.0
    strict_recovery_rate: float | None = None
    json_failure_count: int = 0
    field_failures: dict[str, int] = field(default_factory=dict)
    p50_latency: float = 0.0
    p95_latency: float = 0.0
    mean_total_tokens: float = 0.0
    word_count_in_range_rate: float = 0.0


def classify_failure(brief_errors: list[str]) -> bool:
    """True when the failure pattern indicates unparseable JSON.

    Heuristic, not exact: _summarize_one collapses a JSON parse failure and a
    genuinely bad brief into the same ValueError. All four image fields missing
    at once is the fallback-dict signature.
    """
    return _JSON_FAILURE_SIGNATURE.issubset(set(brief_errors))


def success_result(
    *, url: str, title: str, summary: str, rubric_passed: bool,
    total_tokens: int, latency_s: float, word_count: int,
) -> ArticleResult:
    return ArticleResult(
        url=url, title=title, ok=True, summary=summary,
        rubric_passed=rubric_passed, total_tokens=total_tokens,
        latency_s=latency_s, word_count=word_count,
    )


def failure_result(
    *, url: str, title: str, brief_errors: list[str], error: str, latency_s: float,
) -> ArticleResult:
    return ArticleResult(
        url=url, title=title, ok=False, brief_errors=list(brief_errors),
        json_failure=classify_failure(brief_errors), error=error,
        latency_s=latency_s,
    )


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def aggregate(
    model: str,
    results: list[ArticleResult],
    strict_results: list[ArticleResult],
) -> ModelAggregate:
    count = len(results)
    if count == 0:
        return ModelAggregate(model=model, article_count=0)

    field_failures: dict[str, int] = {}
    for result in results:
        for name in result.brief_errors:
            field_failures[name] = field_failures.get(name, 0) + 1

    latencies = [r.latency_s for r in results]
    low, high = WORD_TARGET
    in_range = sum(1 for r in results if r.ok and low <= r.word_count <= high)

    strict_rate = None
    if strict_results:
        strict_rate = sum(1 for r in strict_results if r.rubric_passed) / len(strict_results)

    return ModelAggregate(
        model=model,
        article_count=count,
        brief_valid_rate=sum(1 for r in results if r.ok) / count,
        first_pass_rate=sum(1 for r in results if r.ok and r.rubric_passed) / count,
        strict_recovery_rate=strict_rate,
        json_failure_count=sum(1 for r in results if r.json_failure),
        field_failures=field_failures,
        p50_latency=_percentile(latencies, 0.50),
        p95_latency=_percentile(latencies, 0.95),
        mean_total_tokens=sum(r.total_tokens for r in results) / count,
        word_count_in_range_rate=in_range / count,
    )


def unavailable(model: str, reason: str) -> ModelAggregate:
    return ModelAggregate(model=model, available=False, unavailable_reason=reason)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_eval_scoring.py -v`
Expected: PASS, 13 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/eval_scoring.py tests/test_eval_scoring.py
git commit -m "feat: add sub_model evaluation scoring and aggregation"
```

---

### Task 3: Markdown report rendering

**Files:**
- Create: `scripts/eval_report.py`
- Create: `tests/test_eval_report.py`

**Interfaces:**
- Consumes: `ModelAggregate`, `ArticleResult` from `scripts/eval_scoring`.
- Produces:
  - `render_report(aggregates: list[ModelAggregate], samples: dict[str, list[ArticleResult]], captured_at: str, baseline_model: str) -> str`

`samples` maps a model id to the `ArticleResult`s chosen for side-by-side display.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eval_report.py`:

```python
from scripts.eval_report import render_report
from scripts.eval_scoring import ModelAggregate, success_result, unavailable


def _agg(model="m", **kwargs):
    defaults = dict(
        article_count=25, brief_valid_rate=0.96, first_pass_rate=0.72,
        strict_recovery_rate=0.5, json_failure_count=1,
        field_failures={"image_layout": 1},
        p50_latency=1.2, p95_latency=3.4, mean_total_tokens=1310.0,
        word_count_in_range_rate=0.88,
    )
    defaults.update(kwargs)
    return ModelAggregate(model=model, **defaults)


def test_report_has_a_row_per_model():
    text = render_report([_agg("a"), _agg("b")], {}, "2026-07-30", "a")
    assert "| a " in text
    assert "| b " in text


def test_baseline_model_is_marked():
    text = render_report([_agg("a"), _agg("b")], {}, "2026-07-30", "a")
    assert "baseline" in text.lower()


def test_unavailable_model_shows_reason_not_zeros():
    text = render_report([_agg("a"), unavailable("b", "HTTP 404")], {}, "2026-07-30", "a")
    assert "HTTP 404" in text
    assert "unavailable" in text.lower()


def test_zero_article_model_renders_without_crashing():
    text = render_report([ModelAggregate(model="empty")], {}, "2026-07-30", "empty")
    assert "empty" in text


def test_json_failure_count_is_labelled_as_inferred():
    text = render_report([_agg()], {}, "2026-07-30", "m")
    assert "inferred" in text.lower()


def test_json_failures_are_described_as_possible_truncation():
    text = render_report([_agg(json_failure_count=3)], {}, "2026-07-30", "m")
    assert "truncat" in text.lower()


def test_samples_render_summaries_per_model():
    sample = success_result(
        url="u", title="Sample Title", summary="A specific briefing.",
        rubric_passed=True, total_tokens=800, latency_s=1.0, word_count=90,
    )
    text = render_report([_agg("a")], {"a": [sample]}, "2026-07-30", "a")
    assert "Sample Title" in text
    assert "A specific briefing." in text


def test_strict_recovery_none_renders_as_dash():
    text = render_report([_agg(strict_recovery_rate=None)], {}, "2026-07-30", "m")
    assert "n/a" in text.lower() or "—" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_eval_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.eval_report'`

- [ ] **Step 3: Write the implementation**

Create `scripts/eval_report.py`:

```python
"""Markdown rendering for the sub_model evaluation report. No network."""

from __future__ import annotations

from scripts.eval_scoring import ArticleResult, ModelAggregate, WORD_TARGET


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _rate_or_dash(value: float | None) -> str:
    return "n/a" if value is None else _pct(value)


def _summary_table(aggregates: list[ModelAggregate], baseline_model: str) -> list[str]:
    lines = [
        "| Model | Brief valid | First-pass rubric | Strict recovery | JSON fail | p50 | p95 | Mean total tok | Words in range |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for agg in aggregates:
        label = agg.model + (" _(baseline)_" if agg.model == baseline_model else "")
        if not agg.available:
            lines.append(f"| {label} | unavailable — {agg.unavailable_reason} | | | | | | | |")
            continue
        lines.append(
            f"| {label} | {_pct(agg.brief_valid_rate)} | {_pct(agg.first_pass_rate)} "
            f"| {_rate_or_dash(agg.strict_recovery_rate)} | {agg.json_failure_count} "
            f"| {agg.p50_latency:.1f}s | {agg.p95_latency:.1f}s "
            f"| {agg.mean_total_tokens:.0f} | {_pct(agg.word_count_in_range_rate)} |"
        )
    return lines


def _failure_section(aggregates: list[ModelAggregate]) -> list[str]:
    lines = ["## Failure breakdown", ""]
    for agg in aggregates:
        if not agg.available:
            continue
        lines.append(f"**{agg.model}**")
        if not agg.field_failures:
            lines.append("- no brief failures")
        else:
            for name, count in sorted(agg.field_failures.items()):
                lines.append(f"- `{name}`: {count}")
        lines.append(
            f"- JSON parse failures (inferred from all four image fields "
            f"missing at once): {agg.json_failure_count}"
        )
        if agg.json_failure_count:
            lines.append(
                "  - a response truncated at the token cap is also invalid JSON, "
                "so these may be truncation rather than formatting failures"
            )
        lines.append("")
    return lines


def _samples_section(samples: dict[str, list[ArticleResult]]) -> list[str]:
    if not samples:
        return []
    lines = ["## Sample outputs", ""]
    for model, results in samples.items():
        lines.append(f"### {model}")
        lines.append("")
        for result in results:
            lines.append(f"**{result.title}**")
            lines.append("")
            lines.append(result.summary if result.ok else f"_failed: {result.error}_")
            lines.append("")
    return lines


def render_report(
    aggregates: list[ModelAggregate],
    samples: dict[str, list[ArticleResult]],
    captured_at: str,
    baseline_model: str,
) -> str:
    low, high = WORD_TARGET
    lines = [
        "# Sub-Model Baseline Evaluation",
        "",
        f"**Fixtures captured:** {captured_at}",
        f"**Word target:** {low}–{high} words per summary",
        "",
        "Scored with the pipeline's own `RubricMiddleware` and "
        "`_article_brief_errors`. Brief validity is the headline metric: an "
        "invalid brief blocks publication under `images.require_all`.",
        "",
        "## Results",
        "",
    ]
    lines += _summary_table(aggregates, baseline_model)
    lines += ["", *_failure_section(aggregates)]
    lines += _samples_section(samples)
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_eval_report.py -v`
Expected: PASS, 8 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/eval_report.py tests/test_eval_report.py
git commit -m "feat: add sub_model evaluation report rendering"
```

---

### Task 4: Capture mode

**Files:**
- Create: `scripts/eval_sub_model.py`
- Create: `scripts/eval_fixtures/manifest.json` (generated by running the mode)

**Interfaces:**
- Consumes: `save_fixtures` from `scripts.eval_store`; `news_buddy.extract.extract_body`.
- Produces:
  - `capture(base_url: str, limit: int, fixtures_dir: Path) -> int` — returns the number of articles captured
  - `main(argv: list[str] | None = None) -> int`

`extract_body(url: str) -> str` is defined in `news_buddy/extract.py` and caps output at 4,000 characters.

The published archive exposes `index.json` as `{"dates": ["2026-07-29", ...]}` (newest first) and each `YYYY-MM-DD.json` as a list of records carrying `title`, `url`, `source`, and `published_at` — see `news_buddy/index_writer.py`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_eval_store.py`:

```python
def test_capture_writes_fixtures_without_network(tmp_path, monkeypatch):
    from scripts import eval_sub_model

    monkeypatch.setattr(
        eval_sub_model, "_fetch_json",
        lambda url: (
            {"dates": ["2026-07-29"]} if url.endswith("index.json")
            else [{
                "title": "T", "url": "https://example.com/a",
                "source": "Example", "published_at": "2026-07-29",
            }]
        ),
    )
    monkeypatch.setattr(eval_sub_model, "_extract_body", lambda url: "captured body")

    count = eval_sub_model.capture("https://example.com/", limit=1, fixtures_dir=tmp_path)

    assert count == 1
    assert load_fixtures(tmp_path)[0]["body"] == "captured body"


def test_capture_skips_articles_with_empty_bodies(tmp_path, monkeypatch):
    from scripts import eval_sub_model

    monkeypatch.setattr(
        eval_sub_model, "_fetch_json",
        lambda url: (
            {"dates": ["2026-07-29"]} if url.endswith("index.json")
            else [
                {"title": "A", "url": "https://example.com/a", "source": "E", "published_at": "2026-07-29"},
                {"title": "B", "url": "https://example.com/b", "source": "E", "published_at": "2026-07-29"},
            ]
        ),
    )
    monkeypatch.setattr(
        eval_sub_model, "_extract_body",
        lambda url: "" if url.endswith("/a") else "real body",
    )

    count = eval_sub_model.capture("https://example.com/", limit=5, fixtures_dir=tmp_path)

    assert count == 1
    assert load_fixtures(tmp_path)[0]["url"] == "https://example.com/b"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_eval_store.py -k capture -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.eval_sub_model'`

- [ ] **Step 3: Write the implementation**

Create `scripts/eval_sub_model.py`:

```python
"""Measure sub_model performance on frozen article fixtures.

Opt-in: this script makes real model calls and is never run by CI.

    python -m scripts.eval_sub_model --capture
    python -m scripts.eval_sub_model --run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

from scripts.eval_store import save_fixtures

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "scripts" / "eval_fixtures"
ARCHIVE_BASE = "https://harshagarwal06.github.io/buddy_agent/"
DEFAULT_CORPUS = 25


def _fetch_json(url: str):
    response = httpx.get(url, timeout=30.0, follow_redirects=True)
    response.raise_for_status()
    return response.json()


def _extract_body(url: str) -> str:
    from news_buddy.extract import extract_body

    return extract_body(url) or ""


def capture(base_url: str, limit: int, fixtures_dir: Path) -> int:
    base = base_url.rstrip("/") + "/"
    manifest = _fetch_json(base + "index.json")

    articles: list[dict] = []
    for date in manifest.get("dates", []):
        if len(articles) >= limit:
            break
        for record in _fetch_json(f"{base}{date}.json"):
            if len(articles) >= limit:
                break
            url = record.get("url", "")
            if not url:
                continue
            body = _extract_body(url)
            if not body.strip():
                print(f"  skipped (no body): {url}", file=sys.stderr)
                continue
            articles.append({
                "url": url,
                "title": record.get("title", ""),
                "source": record.get("source", ""),
                "published_at": record.get("published_at", ""),
                "body": body,
            })
            print(f"  captured: {record.get('title', '')[:60]}", file=sys.stderr)

    save_fixtures(fixtures_dir, articles)
    return len(articles)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true", help="Snapshot fixtures from the published archive")
    parser.add_argument("--limit", type=int, default=DEFAULT_CORPUS, help="Number of articles")
    parser.add_argument("--archive-base", default=ARCHIVE_BASE)
    args = parser.parse_args(argv)

    if args.capture:
        count = capture(args.archive_base, args.limit, FIXTURES_DIR)
        print(f"Captured {count} articles to {FIXTURES_DIR}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_eval_store.py -v`
Expected: PASS, 8 passed

- [ ] **Step 5: Capture the real corpus**

Run: `uv run python -m scripts.eval_sub_model --capture`
Expected: progress lines then `Captured 25 articles to .../scripts/eval_fixtures`

If fewer than 25 are captured, the archive holds fewer usable articles; that is acceptable. Record the actual number in the report later.

- [ ] **Step 6: Verify the split is correct**

Run: `git status --porcelain scripts/eval_fixtures/`
Expected: `manifest.json` shows as untracked; `articles.json` does **not** appear. If `articles.json` appears, the gitignore rule from Task 1 is broken — stop and fix it.

- [ ] **Step 7: Commit**

```bash
git add scripts/eval_sub_model.py scripts/eval_fixtures/manifest.json tests/test_eval_store.py
git commit -m "feat: add fixture capture mode for sub_model evaluation"
```

---

### Task 5: Run mode and report generation

**Files:**
- Modify: `scripts/eval_sub_model.py`
- Create: `tests/test_eval_runner.py`
- Create: `docs/evals/` (holds the generated report)

**Interfaces:**
- Consumes: `load_fixtures`; `aggregate`, `unavailable`, `success_result`, `failure_result`; `render_report`.
- Produces:
  - `evaluate_model(model: str, articles: list[dict], config: dict) -> tuple[ModelAggregate, list[ArticleResult]]`
  - `run(models: list[str], fixtures_dir: Path, output: Path, baseline: str) -> int`

Production interfaces this task depends on, all already existing:

- `news_buddy.llm.get_sub_model(config: dict)` builds from `config["llm"]["sub_model"]`.
- `news_buddy.agent._summarize_one(sub_llm, item: dict, strict: bool = False) -> tuple[dict, int, str]`. It raises `ValueError` whose message ends with a comma-joined list of `_article_brief_errors` names. It calls `_extract.extract_body(item["url"])` first — the harness patches `news_buddy.agent._extract.extract_body`.
- `news_buddy.rubric.RubricMiddleware(min_length, min_words, importance_penalty).score(enriched) -> dict` adds `enriched["rubric"]["passed"]`.
- Config is loaded the same way the CLI does it; read `config.yaml` with `yaml.safe_load`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eval_runner.py`:

```python
import pytest

from scripts import eval_sub_model


def _config():
    return {
        "llm": {"sub_model": "base", "max_tokens": 512, "temperature": 0.2},
        "rubric": {"min_summary_length": 200, "min_summary_words": 65, "importance_penalty": 2},
    }


def _article(url="https://example.com/a"):
    return {"url": url, "title": "T", "source": "E", "published_at": "2026-07-29", "body": "body"}


def test_evaluate_model_scores_a_successful_summary(monkeypatch):
    monkeypatch.setattr(eval_sub_model, "_build_model", lambda config: object())
    monkeypatch.setattr(
        eval_sub_model, "_summarize", 
        lambda llm, item, strict=False: (
            {**item, "summary": "A named subject did a specific thing. " * 6,
             "tags": ["ai"], "importance": 4},
            700,
        ),
    )

    agg, results = eval_sub_model.evaluate_model("m", [_article()], _config())

    assert agg.article_count == 1
    assert agg.brief_valid_rate == 1.0
    assert results[0].ok is True


def test_evaluate_model_records_brief_failure_without_aborting(monkeypatch):
    def _boom(llm, item, strict=False):
        raise ValueError(
            "summarizer returned an incomplete article image brief: image_layout"
        )

    monkeypatch.setattr(eval_sub_model, "_build_model", lambda config: object())
    monkeypatch.setattr(eval_sub_model, "_summarize", _boom)

    agg, results = eval_sub_model.evaluate_model("m", [_article(), _article("u2")], _config())

    assert agg.article_count == 2
    assert agg.brief_valid_rate == 0.0
    assert agg.field_failures == {"image_layout": 2}
    assert results[0].json_failure is False


def test_evaluate_model_marks_unavailable_when_build_fails(monkeypatch):
    def _fail(config):
        raise RuntimeError("HTTP 404: model not found")

    monkeypatch.setattr(eval_sub_model, "_build_model", _fail)

    agg, results = eval_sub_model.evaluate_model("gone", [_article()], _config())

    assert agg.available is False
    assert "404" in agg.unavailable_reason
    assert results == []


def test_brief_errors_are_parsed_from_the_exception_message():
    parsed = eval_sub_model._parse_brief_errors(
        "summarizer returned an incomplete article image brief: "
        "image_prompt, image_layout, image_labels, image_alt"
    )
    assert parsed == ["image_prompt", "image_layout", "image_labels", "image_alt"]


def test_unrelated_exception_message_yields_no_brief_errors():
    assert eval_sub_model._parse_brief_errors("connection reset") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_eval_runner.py -v`
Expected: FAIL — `AttributeError: module 'scripts.eval_sub_model' has no attribute 'evaluate_model'`

- [ ] **Step 3: Write the implementation**

Add to `scripts/eval_sub_model.py`, after the existing imports:

```python
import time

import yaml

from scripts.eval_report import render_report
from scripts.eval_scoring import (
    ArticleResult,
    ModelAggregate,
    aggregate,
    failure_result,
    success_result,
    unavailable,
)
from scripts.eval_store import load_fixtures

BASELINE_MODEL = "meta/llama-3.1-8b-instruct"
CANDIDATE_MODELS = [
    BASELINE_MODEL,
    "nvidia/nemotron-3-super-120b-a12b",
    "poolside/laguna-xs-2.1",
    "mistralai/mistral-medium-3.5-128b",
    "google/gemma-4-31b-it",
]

_BRIEF_ERROR_PREFIX = "summarizer returned an incomplete article image brief:"


def _load_config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def _build_model(config: dict):
    from news_buddy.llm import get_sub_model

    return get_sub_model(config)


def _summarize(sub_llm, item: dict, strict: bool = False):
    from news_buddy.agent import _summarize_one

    enriched, tokens, _body = _summarize_one(sub_llm, item, strict=strict)
    return enriched, tokens


def _parse_brief_errors(message: str) -> list[str]:
    if _BRIEF_ERROR_PREFIX not in message:
        return []
    tail = message.split(_BRIEF_ERROR_PREFIX, 1)[1]
    return [part.strip() for part in tail.split(",") if part.strip()]


def _patch_body_source(articles: list[dict]):
    """Feed frozen bodies to _summarize_one instead of re-extracting over the network."""
    from news_buddy import agent as _agent

    bodies = {article["url"]: article["body"] for article in articles}
    original = _agent._extract.extract_body
    _agent._extract.extract_body = lambda url: bodies.get(url, "")
    return _agent, original


def _score_one(sub_llm, article: dict, rubric, strict: bool) -> ArticleResult:
    start = time.monotonic()
    try:
        enriched, tokens = _summarize(sub_llm, article, strict=strict)
    except Exception as exc:  # noqa: BLE001 - every failure mode is data here
        return failure_result(
            url=article["url"], title=article.get("title", ""),
            brief_errors=_parse_brief_errors(str(exc)),
            error=str(exc)[:200], latency_s=time.monotonic() - start,
        )

    elapsed = time.monotonic() - start
    scored = rubric.score(enriched)
    summary = scored.get("summary", "")
    return success_result(
        url=article["url"], title=article.get("title", ""), summary=summary,
        rubric_passed=bool(scored["rubric"]["passed"]),
        total_tokens=tokens, latency_s=elapsed,
        word_count=len(summary.split()),
    )


def evaluate_model(
    model: str, articles: list[dict], config: dict
) -> tuple[ModelAggregate, list[ArticleResult]]:
    from news_buddy.rubric import RubricMiddleware

    model_config = {**config, "llm": {**config["llm"], "sub_model": model}}
    try:
        sub_llm = _build_model(model_config)
    except Exception as exc:  # noqa: BLE001
        return unavailable(model, str(exc)[:120]), []

    rubric_config = config.get("rubric", {})
    rubric = RubricMiddleware(
        min_length=rubric_config.get("min_summary_length", 60),
        min_words=rubric_config.get("min_summary_words"),
        importance_penalty=rubric_config.get("importance_penalty", 2),
    )

    results = [_score_one(sub_llm, a, rubric, strict=False) for a in articles]

    retry_urls = {r.url for r in results if r.ok and not r.rubric_passed}
    strict_results = [
        _score_one(sub_llm, a, rubric, strict=True)
        for a in articles if a["url"] in retry_urls
    ]

    return aggregate(model, results, strict_results), results


def run(
    models: list[str], fixtures_dir: Path, output: Path, baseline: str,
    limit: int | None = None, rpm: int | None = None,
) -> int:
    import json
    import os

    # Fail fast rather than reporting every model as "unavailable — no key".
    if not os.getenv("NVIDIA_API_KEY", "").strip():
        raise SystemExit(
            "NVIDIA_API_KEY is not set. Create a key at "
            "https://build.nvidia.com/ and add it to .env."
        )

    articles = load_fixtures(fixtures_dir)
    if limit:
        articles = articles[:limit]
    config = _load_config()
    if rpm:
        config = {**config, "llm": {**config["llm"], "requests_per_minute": rpm}}
    captured_at = json.loads(
        (fixtures_dir / "manifest.json").read_text(encoding="utf-8")
    )["captured_at"]

    agent_module, original_extract = _patch_body_source(articles)
    try:
        aggregates, samples = [], {}
        for model in models:
            print(f"Evaluating {model} …", file=sys.stderr)
            agg, results = evaluate_model(model, articles, config)
            aggregates.append(agg)
            samples[model] = results[:3]
    finally:
        agent_module._extract.extract_body = original_extract

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_report(aggregates, samples, captured_at, baseline), encoding="utf-8"
    )
    print(f"Report written to {output}")
    return 0
```

Replace the body of `main` with:

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true", help="Snapshot fixtures from the published archive")
    parser.add_argument("--run", action="store_true", help="Evaluate models against captured fixtures")
    parser.add_argument("--limit", type=int, default=DEFAULT_CORPUS,
                        help="Articles to capture, or to evaluate when used with --run")
    parser.add_argument("--rpm", type=int, default=None,
                        help="Override llm.requests_per_minute for this session")
    parser.add_argument("--archive-base", default=ARCHIVE_BASE)
    parser.add_argument("--models", default=",".join(CANDIDATE_MODELS))
    parser.add_argument("--baseline", default=BASELINE_MODEL)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs" / "evals" / "2026-07-30-sub-model-baseline.md",
    )
    args = parser.parse_args(argv)

    if args.capture:
        count = capture(args.archive_base, args.limit, FIXTURES_DIR)
        print(f"Captured {count} articles to {FIXTURES_DIR}")
        return 0

    if args.run:
        models = [m.strip() for m in args.models.split(",") if m.strip()]
        return run(models, FIXTURES_DIR, args.output, args.baseline,
                   limit=args.limit, rpm=args.rpm)

    parser.print_help()
    return 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_eval_runner.py -v`
Expected: PASS, 5 passed

- [ ] **Step 5: Run the whole suite and the linter**

Run: `uv run pytest && uv run ruff check .`
Expected: all tests pass, `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add scripts/eval_sub_model.py tests/test_eval_runner.py
git commit -m "feat: add sub_model evaluation run mode and report generation"
```

---

### Task 6: Produce the baseline report

**Files:**
- Create: `docs/evals/2026-07-30-sub-model-baseline.md`

**Interfaces:**
- Consumes: the complete CLI from Task 5.
- Produces: the report artifact. No code.

- [ ] **Step 1: Smoke-test with one model and two articles**

Run: `uv run python -m scripts.eval_sub_model --run --models meta/llama-3.1-8b-instruct --limit 2 --output /tmp/eval-smoke.md`

Expected: `Evaluating meta/llama-3.1-8b-instruct …` then `Report written to /tmp/eval-smoke.md`.

If this fails with a `FixtureError`, run `--capture` first. If it fails inside `_summarize_one`, the patched body source is wrong — check that `_patch_body_source` is applied before any model call.

- [ ] **Step 2: Read the smoke report**

Run: `cat /tmp/eval-smoke.md`

Confirm: a results row with non-zero `Brief valid`, a failure breakdown section, and sample summaries that read like real briefings. If every article failed, stop — something is wrong with the harness, not the model.

- [ ] **Step 3: Run the full evaluation**

Run: `uv run python -m scripts.eval_sub_model --run`

Expected: five `Evaluating …` lines, then the report path. This takes roughly 20 minutes at the configured throttle. A model that reports `unavailable` is recorded, not fatal.

- [ ] **Step 4: Apply the decision criteria**

Read `docs/evals/2026-07-30-sub-model-baseline.md` and record the verdict at the bottom of the file under a `## Verdict` heading, applying the criteria fixed in the spec:

1. Reject any candidate whose brief validity rate is below baseline, or with a non-zero JSON failure count. (This replaces the spec's "zero token-cap hits" criterion — see the correction in Task 2. A truncated response is invalid JSON, so JSON failures cover the same risk with a figure that can actually be measured.)
2. Among survivors, prefer the highest first-attempt rubric pass rate.
3. Reject any whose p95 latency is outside the digest's runtime budget.
4. Break ties on the sample read.

State plainly if the outcome is "keep the current model" — that is a valid and useful result, not a failed experiment. Note the actual corpus size if fewer than 25 articles were captured, and remember that differences under roughly 10 percentage points are not decisive at this sample size.

- [ ] **Step 5: Commit**

```bash
git add docs/evals/2026-07-30-sub-model-baseline.md
git commit -m "docs: add sub_model baseline evaluation results"
```

- [ ] **Step 6: Confirm no runtime change leaked in**

Run: `git diff --stat main -- news_buddy news_buddy_mcp config.yaml prompts`
Expected: empty output. If anything appears, revert it — this work must not alter runtime behavior.
