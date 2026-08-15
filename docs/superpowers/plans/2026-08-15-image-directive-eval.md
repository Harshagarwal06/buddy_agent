# Image Directive Evaluation Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an opt-in harness that measures whether changing the image style directive's phrasing, its truncation behaviour, both, or neither reduces contract violations in generated article illustrations.

**Architecture:** Four new modules under `scripts/`, mirroring the existing `eval_sub_model.py` split: a network-boundary judge client, a pure scoring/aggregation module, a pure markdown renderer, and a thin CLI runner. The existing `eval_store.py` is reused unchanged for manifest-verified fixtures. Pure modules are fully unit-tested; the runner is thin orchestration.

**Tech Stack:** Python 3.11+, Pillow, numpy, `google-genai` (vision judge, `gemini-3.5-flash`), httpx via the existing `_NvidiaImageClient`, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-08-15-image-directive-eval-design.md`

## Global Constraints

- **Opt-in only.** This harness makes real, paid API calls. It must never run in CI. No test may make a network call.
- **No production state.** Never touch `state.db`, `chroma_db/`, `knowledge_base/`, or `~/news/`. Artifacts write only to `scripts/eval_artifacts/`.
- **Never modify `prompts/image_style.md`.** Variants are assembled in memory. The `negated` directive is read live via `image_generator._read_marked_section`.
- **Score raw provider bytes, never published WebPs.** `_add_label_band` composites onto cream paper and covers model-drawn captions; scoring published images measures the crop, not the model.
- **Rates divide by successfully-judged images, never by attempts.** Both counts appear in every report. A variant must not benefit from failing to generate or failing to be judged.
- Cream token: `(243, 236, 216)`. Background violation threshold: Euclidean RGB distance `> 30`.
- Judge model default: `gemini-3.5-flash`. Judge agreement below `0.90` on either class marks the report provisional.
- Line length follows existing repo style; `ruff check .` must pass.

---

### Task 1: Vision judge client

**Files:**
- Create: `scripts/eval_image_judge.py`
- Create: `tests/test_eval_image_judge.py`
- Modify: `pyproject.toml` (add `google-genai` to the `dev` group)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `class JudgeVerdict` with fields `has_text: bool | None`, `has_person: bool | None`, `object_group_count: int | None`, `error: str`
  - `DEFAULT_JUDGE_MODEL: str = "gemini-3.5-flash"`
  - `JUDGE_PROMPT: str`
  - `parse_verdict(text: str) -> JudgeVerdict`
  - `class ImageJudge` with `__init__(self, model: str = DEFAULT_JUDGE_MODEL, client=None)` and `judge(self, image_bytes: bytes, mime_type: str = "image/png") -> JudgeVerdict`

`google-genai` is currently only a transitive dependency of `langchain-google-genai`. Task 1 declares it explicitly so the harness does not depend on another package's dependency tree.

- [ ] **Step 1: Add the explicit dependency**

In `pyproject.toml`, inside `[dependency-groups]`, add `"google-genai",` to the `dev` list:

```toml
[dependency-groups]
dev = [
    "pytest",
    "ruff==0.15.22",
    "google-genai",
    "langchain-google-genai",
    "huggingface-hub",
    "langchain-ollama",
    "chromadb",
    "arize-phoenix-otel",
    "openinference-instrumentation-langchain",
]
```

Then run `uv lock` to update `uv.lock`.

- [ ] **Step 2: Write the failing parser tests**

Create `tests/test_eval_image_judge.py`:

```python
from scripts.eval_image_judge import JudgeVerdict, parse_verdict


def test_parse_verdict_reads_plain_json():
    verdict = parse_verdict('{"has_text": true, "has_person": false, "object_group_count": 3}')
    assert verdict.has_text is True
    assert verdict.has_person is False
    assert verdict.object_group_count == 3
    assert verdict.error == ""


def test_parse_verdict_tolerates_code_fences():
    raw = '```json\n{"has_text": false, "has_person": false, "object_group_count": 2}\n```'
    verdict = parse_verdict(raw)
    assert verdict.has_text is False
    assert verdict.object_group_count == 2


def test_parse_verdict_reports_invalid_json_as_error():
    verdict = parse_verdict("I am not JSON")
    assert verdict.has_text is None
    assert verdict.has_person is None
    assert verdict.error


def test_parse_verdict_rejects_missing_keys():
    """A partial verdict must not be silently treated as clean."""
    verdict = parse_verdict('{"has_text": true}')
    assert verdict.has_person is None
    assert verdict.error


def test_parse_verdict_rejects_non_boolean_flags():
    verdict = parse_verdict('{"has_text": "yes", "has_person": false, "object_group_count": 3}')
    assert verdict.has_text is None
    assert verdict.error
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_eval_image_judge.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.eval_image_judge'`

- [ ] **Step 4: Implement the module**

Create `scripts/eval_image_judge.py`:

```python
"""Vision judge for generated article illustrations.

Opt-in: makes real API calls and is never run by CI. The model was verified
against the account before being pinned; see the design spec.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

DEFAULT_JUDGE_MODEL = "gemini-3.5-flash"

JUDGE_PROMPT = (
    "You are grading an illustration against a style contract. "
    "Answer ONLY with raw JSON, no code fences, with exactly these keys:\n"
    '{"has_text": bool, "has_person": bool, "object_group_count": int}\n'
    "has_text: true if ANY letters, words, numbers, or text-like glyphs appear "
    "anywhere in the image, including garbled or nonsense lettering.\n"
    "has_person: true if any human figure, face, or body part appears.\n"
    "object_group_count: how many distinct symbolic object groups are shown."
)

_REQUIRED = ("has_text", "has_person", "object_group_count")


@dataclass
class JudgeVerdict:
    has_text: bool | None = None
    has_person: bool | None = None
    object_group_count: int | None = None
    error: str = ""


def parse_verdict(text: str) -> JudgeVerdict:
    """Parse a judge response. Any deviation yields an error verdict, never a clean one."""
    cleaned = str(text).strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(
            line for line in cleaned.splitlines() if not line.strip().startswith("```")
        ).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return JudgeVerdict(error=f"invalid JSON: {exc}")
    if not isinstance(data, dict):
        return JudgeVerdict(error="response was not a JSON object")

    missing = [key for key in _REQUIRED if key not in data]
    if missing:
        return JudgeVerdict(error=f"missing keys: {', '.join(missing)}")
    if not isinstance(data["has_text"], bool) or not isinstance(data["has_person"], bool):
        return JudgeVerdict(error="has_text and has_person must be booleans")
    if not isinstance(data["object_group_count"], int) or isinstance(
        data["object_group_count"], bool
    ):
        return JudgeVerdict(error="object_group_count must be an integer")

    return JudgeVerdict(
        has_text=data["has_text"],
        has_person=data["has_person"],
        object_group_count=data["object_group_count"],
    )


class ImageJudge:
    """Thin wrapper over the Gemini vision API. Never raises; returns error verdicts."""

    def __init__(self, model: str = DEFAULT_JUDGE_MODEL, client=None) -> None:
        self._model = model
        self._client = client

    def _ensure_client(self):
        if self._client is None:
            from google import genai

            api_key = os.getenv("GOOGLE_API_KEY", "").strip()
            if not api_key:
                raise RuntimeError(
                    "GOOGLE_API_KEY is not set; the image judge requires it."
                )
            self._client = genai.Client(api_key=api_key)
        return self._client

    def judge(self, image_bytes: bytes, mime_type: str = "image/png") -> JudgeVerdict:
        from google.genai import types

        try:
            client = self._ensure_client()
            response = client.models.generate_content(
                model=self._model,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    JUDGE_PROMPT,
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                ),
            )
        except Exception as exc:  # noqa: BLE001 - every failure mode is data here
            return JudgeVerdict(error=f"{type(exc).__name__}: {str(exc)[:160]}")
        return parse_verdict(response.text or "")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_eval_image_judge.py -q`
Expected: PASS, 5 passed

- [ ] **Step 6: Add a client-boundary test with a fake client**

Append to `tests/test_eval_image_judge.py`:

```python
from scripts.eval_image_judge import ImageJudge


class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, text, raises=None):
        self._text = text
        self._raises = raises
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append(model)
        if self._raises:
            raise self._raises
        return _FakeResponse(self._text)


class _FakeClient:
    def __init__(self, text, raises=None):
        self.models = _FakeModels(text, raises)


def test_judge_returns_parsed_verdict():
    client = _FakeClient('{"has_text": true, "has_person": true, "object_group_count": 1}')
    verdict = ImageJudge(client=client).judge(b"fake-bytes")
    assert verdict.has_text is True
    assert verdict.has_person is True
    assert client.models.calls == ["gemini-3.5-flash"]


def test_judge_converts_api_errors_into_error_verdicts():
    client = _FakeClient("", raises=RuntimeError("upstream exploded"))
    verdict = ImageJudge(client=client).judge(b"fake-bytes")
    assert verdict.has_text is None
    assert "upstream exploded" in verdict.error
```

- [ ] **Step 7: Run the full suite and lint**

Run: `uv run pytest -q && uv run ruff check .`
Expected: all tests pass, "All checks passed!"

- [ ] **Step 8: Commit**

```bash
git add scripts/eval_image_judge.py tests/test_eval_image_judge.py pyproject.toml uv.lock
git commit -m "feat: add the vision judge client for image evaluation"
```

---

### Task 2: Palette scoring and raw-generation fixtures

**Files:**
- Create: `scripts/eval_image_scoring.py`
- Create: `tests/test_eval_image_scoring.py`
- Create: `tests/fixtures/images/raw-white-bg.png`, `tests/fixtures/images/raw-cream-bg.png`, `tests/fixtures/images/raw-cream-edge.png`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `CREAM_RGB: tuple[int, int, int] = (243, 236, 216)`
  - `BACKGROUND_THRESHOLD: float = 30.0`
  - `background_distance(image_bytes: bytes) -> float`
  - `background_is_cream(image_bytes: bytes) -> bool`

The fixtures are raw provider output, not published WebPs. Published images always score a distance of ~1.0 because `_add_label_band` composites onto cream paper, so they cannot exercise the failure case.

- [ ] **Step 1: Create the fixture directory and downscale three raw generations**

The three source images are raw FLUX output already on disk from the exploratory run. Downscale to keep the repo light — the border-ring median is stable under downscaling.

```bash
mkdir -p tests/fixtures/images
uv run python - <<'PY'
from PIL import Image
import pathlib
SRC = pathlib.Path("/private/tmp/claude-501/-Users-harshagarwal-Desktop-bootcamp-buddy-agent/290b7fff-c568-48f6-b169-62a07a900069/scratchpad/ab")
OUT = pathlib.Path("tests/fixtures/images")
pairs = [
    ("01-current.png", "raw-white-bg.png"),      # measured distance 41.9 -> violation
    ("01-pos-intact.png", "raw-cream-bg.png"),   # measured distance  6.4 -> compliant
    ("02-pos-intact.png", "raw-cream-edge.png"), # measured distance 23.0 -> compliant, near threshold
]
for src, dst in pairs:
    im = Image.open(SRC / src).convert("RGB")
    im.thumbnail((320, 320), Image.Resampling.LANCZOS)
    im.save(OUT / dst, format="PNG", optimize=True)
    print(dst, im.size)
PY
```

If the scratchpad path no longer exists, regenerate equivalents by running any two variants through `_NvidiaImageClient` and keeping the raw bytes; the requirement is one white-background image above distance 30 and two cream-background images below it, one near 23.

- [ ] **Step 2: Write the failing palette tests**

Create `tests/test_eval_image_scoring.py`:

```python
import io
from pathlib import Path

from PIL import Image

from scripts.eval_image_scoring import (
    BACKGROUND_THRESHOLD,
    background_distance,
    background_is_cream,
)

FIXTURES = Path(__file__).parent / "fixtures" / "images"


def _solid_png(color):
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_cream_square_is_compliant():
    assert background_is_cream(_solid_png((243, 236, 216))) is True


def test_white_square_is_a_violation():
    assert background_is_cream(_solid_png((255, 255, 255))) is False


def test_white_background_fixture_exceeds_threshold():
    distance = background_distance((FIXTURES / "raw-white-bg.png").read_bytes())
    assert distance > BACKGROUND_THRESHOLD


def test_cream_background_fixture_is_within_threshold():
    distance = background_distance((FIXTURES / "raw-cream-bg.png").read_bytes())
    assert distance < BACKGROUND_THRESHOLD


def test_near_threshold_cream_fixture_still_passes():
    """Guards the 23.0-vs-30 margin: tightening the threshold must break a test."""
    distance = background_distance((FIXTURES / "raw-cream-edge.png").read_bytes())
    assert 15.0 < distance < BACKGROUND_THRESHOLD
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_eval_image_scoring.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.eval_image_scoring'`

- [ ] **Step 4: Implement the palette scoring**

Create `scripts/eval_image_scoring.py`:

```python
"""Scoring and aggregation for the image directive evaluation. No network."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

# The cream paper token from prompts/image_style.md and tokens.css.
CREAM_RGB = (243, 236, 216)

# Measured separation on raw generations: white backgrounds land at 36.0-43.5,
# cream backgrounds at 6.4-23.0. 30 splits them with margin on both sides.
BACKGROUND_THRESHOLD = 30.0

_RING_PX = 8


def background_distance(image_bytes: bytes) -> float:
    """Euclidean RGB distance from the border-ring median colour to cream."""
    with Image.open(io.BytesIO(image_bytes)) as opened:
        pixels = np.asarray(opened.convert("RGB")).astype(float)
    ring = np.concatenate(
        [
            pixels[:_RING_PX].reshape(-1, 3),
            pixels[-_RING_PX:].reshape(-1, 3),
            pixels[:, :_RING_PX].reshape(-1, 3),
            pixels[:, -_RING_PX:].reshape(-1, 3),
        ]
    )
    median = np.median(ring, axis=0)
    return float(np.sqrt(((median - np.array(CREAM_RGB, dtype=float)) ** 2).sum()))


def background_is_cream(image_bytes: bytes) -> bool:
    return background_distance(image_bytes) <= BACKGROUND_THRESHOLD
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_eval_image_scoring.py -q`
Expected: PASS, 5 passed

- [ ] **Step 6: Commit**

```bash
git add scripts/eval_image_scoring.py tests/test_eval_image_scoring.py tests/fixtures/images
git commit -m "feat: add deterministic palette scoring with raw-generation fixtures"
```

---

### Task 3: Result types and aggregation

**Files:**
- Modify: `scripts/eval_image_scoring.py` (append)
- Modify: `tests/test_eval_image_scoring.py` (append)

**Interfaces:**
- Consumes: `background_is_cream`, `background_distance` from Task 2.
- Produces:
  - `VARIANTS: tuple[str, ...] = ("negated-truncated", "negated-preserved", "positive-truncated", "positive-preserved")`
  - `BASELINE_VARIANT: str = "negated-truncated"`
  - `STRATA: tuple[str, ...] = ("mechanism", "person")`
  - `class ImageResult` — dataclass, fields listed below
  - `class VariantAggregate` — dataclass, fields listed below
  - `is_clean(result: ImageResult) -> bool | None`
  - `aggregate(variant: str, results: list[ImageResult]) -> VariantAggregate`

- [ ] **Step 1: Write the failing aggregation tests**

Append to `tests/test_eval_image_scoring.py`:

```python
from scripts.eval_image_scoring import ImageResult, aggregate, is_clean


def _result(**overrides):
    base = dict(
        article_url="https://example.test/a",
        stratum="mechanism",
        variant="positive-preserved",
        ok=True,
        error="",
        content_filtered=False,
        background_is_cream=True,
        background_distance=5.0,
        has_text=False,
        has_person=False,
        object_group_count=3,
        judge_error="",
    )
    base.update(overrides)
    return ImageResult(**base)


def test_is_clean_requires_no_text_no_person_and_cream():
    assert is_clean(_result()) is True
    assert is_clean(_result(has_text=True)) is False
    assert is_clean(_result(has_person=True)) is False
    assert is_clean(_result(background_is_cream=False)) is False


def test_is_clean_is_unknown_when_the_judge_failed():
    """A failed judge must never be scored as clean."""
    assert is_clean(_result(has_text=None, judge_error="boom")) is None


def test_rates_divide_by_judged_not_generated():
    results = [
        _result(),
        _result(has_text=True),
        _result(has_text=None, judge_error="boom"),
    ]
    agg = aggregate("positive-preserved", results)
    assert agg.generated == 3
    assert agg.judged == 2
    assert agg.clean_rate == 0.5


def test_generation_failures_are_excluded_and_counted():
    results = [
        _result(),
        _result(ok=False, error="content filtered", content_filtered=True,
                has_text=None, has_person=None),
    ]
    agg = aggregate("positive-preserved", results)
    assert agg.generated == 1
    assert agg.judged == 1
    assert agg.content_filtered == 1
    assert agg.clean_rate == 1.0


def test_aggregate_splits_by_stratum():
    results = [
        _result(stratum="mechanism"),
        _result(stratum="person", has_person=True),
    ]
    agg = aggregate("positive-preserved", results)
    assert agg.clean_rate == 0.5
    assert agg.by_stratum["mechanism"].clean_rate == 1.0
    assert agg.by_stratum["person"].clean_rate == 0.0


def test_empty_results_do_not_divide_by_zero():
    agg = aggregate("positive-preserved", [])
    assert agg.generated == 0
    assert agg.judged == 0
    assert agg.clean_rate == 0.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_eval_image_scoring.py -q`
Expected: FAIL with `ImportError: cannot import name 'ImageResult'`

- [ ] **Step 3: Implement the types and aggregation**

Append to `scripts/eval_image_scoring.py`:

```python
from dataclasses import dataclass, field

VARIANTS = (
    "negated-truncated",
    "negated-preserved",
    "positive-truncated",
    "positive-preserved",
)
BASELINE_VARIANT = "negated-truncated"
STRATA = ("mechanism", "person")


@dataclass
class ImageResult:
    article_url: str
    stratum: str
    variant: str
    ok: bool
    error: str = ""
    content_filtered: bool = False
    background_is_cream: bool = False
    background_distance: float = 0.0
    has_text: bool | None = None
    has_person: bool | None = None
    object_group_count: int | None = None
    judge_error: str = ""


@dataclass
class VariantAggregate:
    variant: str
    generated: int = 0
    judged: int = 0
    content_filtered: int = 0
    clean_rate: float = 0.0
    text_rate: float = 0.0
    person_rate: float = 0.0
    palette_rate: float = 0.0
    three_group_rate: float = 0.0
    by_stratum: dict[str, "VariantAggregate"] = field(default_factory=dict)


def is_clean(result: ImageResult) -> bool | None:
    """True when publishable, False when violating, None when unknowable.

    None is returned whenever the judge failed. Callers must exclude those
    rather than coercing them, so a broken judge cannot inflate clean_rate.
    """
    if result.has_text is None or result.has_person is None:
        return None
    return (
        not result.has_text
        and not result.has_person
        and result.background_is_cream
    )


def _rate(count: int, total: int) -> float:
    return count / total if total else 0.0


def _aggregate_flat(variant: str, results: list[ImageResult]) -> VariantAggregate:
    generated = [r for r in results if r.ok]
    judged = [r for r in generated if is_clean(r) is not None]
    total = len(judged)
    return VariantAggregate(
        variant=variant,
        generated=len(generated),
        judged=total,
        content_filtered=sum(1 for r in results if r.content_filtered),
        clean_rate=_rate(sum(1 for r in judged if is_clean(r)), total),
        text_rate=_rate(sum(1 for r in judged if r.has_text), total),
        person_rate=_rate(sum(1 for r in judged if r.has_person), total),
        palette_rate=_rate(
            sum(1 for r in judged if not r.background_is_cream), total
        ),
        three_group_rate=_rate(
            sum(1 for r in judged if r.object_group_count == 3), total
        ),
    )


def aggregate(variant: str, results: list[ImageResult]) -> VariantAggregate:
    combined = _aggregate_flat(variant, results)
    combined.by_stratum = {
        stratum: _aggregate_flat(variant, [r for r in results if r.stratum == stratum])
        for stratum in STRATA
        if any(r.stratum == stratum for r in results)
    }
    return combined
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_eval_image_scoring.py -q`
Expected: PASS, 11 passed

- [ ] **Step 5: Run the full suite and lint**

Run: `uv run pytest -q && uv run ruff check .`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add scripts/eval_image_scoring.py tests/test_eval_image_scoring.py
git commit -m "feat: add image result types and per-stratum aggregation"
```

---

### Task 4: Calibration and report rendering

**Files:**
- Create: `scripts/eval_image_report.py`
- Create: `tests/test_eval_image_report.py`
- Modify: `scripts/eval_image_scoring.py` (append calibration)
- Modify: `tests/test_eval_image_scoring.py` (append calibration tests)

**Interfaces:**
- Consumes: `VariantAggregate`, `ImageResult`, `BASELINE_VARIANT`, `STRATA` from Task 3.
- Produces:
  - `AGREEMENT_THRESHOLD: float = 0.90`
  - `class Agreement` with `text_accuracy: float`, `person_accuracy: float`, `labelled: int`, `trustworthy: bool`
  - `judge_agreement(results: list[ImageResult], labels: dict[str, dict]) -> Agreement`
  - `render_report(aggregates: list[VariantAggregate], agreement: Agreement, captured_at: str) -> str`

`labels` maps an artifact key (`f"{variant}::{article_url}"`) to `{"has_text": bool, "has_person": bool}`.

- [ ] **Step 1: Write the failing calibration tests**

Append to `tests/test_eval_image_scoring.py`:

```python
from scripts.eval_image_scoring import AGREEMENT_THRESHOLD, judge_agreement


def test_perfect_agreement_is_trustworthy():
    results = [_result(article_url="u1"), _result(article_url="u2", has_text=True)]
    labels = {
        "positive-preserved::u1": {"has_text": False, "has_person": False},
        "positive-preserved::u2": {"has_text": True, "has_person": False},
    }
    agreement = judge_agreement(results, labels)
    assert agreement.labelled == 2
    assert agreement.text_accuracy == 1.0
    assert agreement.trustworthy is True


def test_disagreement_below_threshold_is_not_trustworthy():
    results = [_result(article_url=f"u{i}", has_text=(i == 0)) for i in range(4)]
    labels = {
        f"positive-preserved::u{i}": {"has_text": False, "has_person": False}
        for i in range(4)
    }
    agreement = judge_agreement(results, labels)
    assert agreement.text_accuracy == 0.75
    assert agreement.trustworthy is False
    assert AGREEMENT_THRESHOLD == 0.90


def test_unlabelled_results_are_ignored():
    results = [_result(article_url="u1"), _result(article_url="unlabelled")]
    labels = {"positive-preserved::u1": {"has_text": False, "has_person": False}}
    assert judge_agreement(results, labels).labelled == 1


def test_no_labels_is_not_trustworthy():
    agreement = judge_agreement([_result()], {})
    assert agreement.labelled == 0
    assert agreement.trustworthy is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_eval_image_scoring.py -q`
Expected: FAIL with `ImportError: cannot import name 'AGREEMENT_THRESHOLD'`

- [ ] **Step 3: Implement calibration**

Append to `scripts/eval_image_scoring.py`:

```python
AGREEMENT_THRESHOLD = 0.90


@dataclass
class Agreement:
    labelled: int = 0
    text_accuracy: float = 0.0
    person_accuracy: float = 0.0
    trustworthy: bool = False


def label_key(variant: str, article_url: str) -> str:
    return f"{variant}::{article_url}"


def judge_agreement(
    results: list[ImageResult], labels: dict[str, dict]
) -> Agreement:
    """Compare judge verdicts against hand labels. No labels means not trustworthy."""
    text_hits = person_hits = labelled = 0
    for result in results:
        truth = labels.get(label_key(result.variant, result.article_url))
        if truth is None or result.has_text is None or result.has_person is None:
            continue
        labelled += 1
        text_hits += int(result.has_text == truth["has_text"])
        person_hits += int(result.has_person == truth["has_person"])

    if labelled == 0:
        return Agreement()
    text_accuracy = text_hits / labelled
    person_accuracy = person_hits / labelled
    return Agreement(
        labelled=labelled,
        text_accuracy=text_accuracy,
        person_accuracy=person_accuracy,
        trustworthy=(
            text_accuracy >= AGREEMENT_THRESHOLD
            and person_accuracy >= AGREEMENT_THRESHOLD
        ),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_eval_image_scoring.py -q`
Expected: PASS, 15 passed

- [ ] **Step 5: Write the failing report tests**

Create `tests/test_eval_image_report.py`:

```python
from scripts.eval_image_report import render_report
from scripts.eval_image_scoring import Agreement, VariantAggregate


def _agg(variant, clean=0.5, judged=16):
    return VariantAggregate(
        variant=variant, generated=judged, judged=judged, clean_rate=clean,
        text_rate=0.25, person_rate=0.125, palette_rate=0.0,
        three_group_rate=0.75, content_filtered=1,
        by_stratum={
            "mechanism": VariantAggregate(variant=variant, judged=8, clean_rate=clean),
            "person": VariantAggregate(variant=variant, judged=8, clean_rate=clean / 2),
        },
    )


def test_report_marks_the_baseline():
    report = render_report(
        [_agg("negated-truncated")], Agreement(labelled=20, text_accuracy=1.0,
        person_accuracy=1.0, trustworthy=True), "2026-08-15T00:00:00+00:00"
    )
    assert "_(production)_" in report


def test_report_states_the_decision_rule_before_the_numbers():
    report = render_report(
        [_agg("negated-truncated")], Agreement(labelled=20, text_accuracy=1.0,
        person_accuracy=1.0, trustworthy=True), "2026-08-15T00:00:00+00:00"
    )
    assert report.index("Decision rule") < report.index("## Results")


def test_untrustworthy_judge_marks_the_report_provisional():
    report = render_report(
        [_agg("negated-truncated")],
        Agreement(labelled=20, text_accuracy=0.6, person_accuracy=1.0,
                  trustworthy=False),
        "2026-08-15T00:00:00+00:00",
    )
    assert "PROVISIONAL" in report
    assert "should not be acted on" in report


def test_report_shows_both_judged_and_generated_counts():
    agg = _agg("negated-truncated")
    agg.generated = 16
    agg.judged = 14
    report = render_report(
        [agg],
        Agreement(labelled=20, text_accuracy=1.0, person_accuracy=1.0,
                  trustworthy=True),
        "2026-08-15T00:00:00+00:00",
    )
    assert "14/16" in report


def test_variant_names_with_pipes_do_not_break_the_table():
    agg = _agg("weird|name")
    report = render_report([agg], Agreement(), "2026-08-15T00:00:00+00:00")
    assert "weird\\|name" in report
```

- [ ] **Step 6: Run the tests to verify they fail**

Run: `uv run pytest tests/test_eval_image_report.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.eval_image_report'`

- [ ] **Step 7: Implement the renderer**

Create `scripts/eval_image_report.py`:

```python
"""Markdown rendering for the image directive evaluation. No network."""

from __future__ import annotations

from scripts.eval_image_scoring import (
    AGREEMENT_THRESHOLD,
    BASELINE_VARIANT,
    Agreement,
    VariantAggregate,
)


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _escape_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _stratum_rate(agg: VariantAggregate, stratum: str) -> str:
    child = agg.by_stratum.get(stratum)
    return "n/a" if child is None else _pct(child.clean_rate)


def _summary_table(aggregates: list[VariantAggregate]) -> list[str]:
    lines = [
        "| Variant | Clean (all) | Clean (mechanism) | Clean (person) | Text | "
        "Person | Palette | 3-group | Filtered | Judged/Generated |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for agg in aggregates:
        label = _escape_cell(agg.variant)
        if agg.variant == BASELINE_VARIANT:
            label += " _(production)_"
        lines.append(
            "| "
            + " | ".join(
                [
                    label,
                    _pct(agg.clean_rate),
                    _stratum_rate(agg, "mechanism"),
                    _stratum_rate(agg, "person"),
                    _pct(agg.text_rate),
                    _pct(agg.person_rate),
                    _pct(agg.palette_rate),
                    _pct(agg.three_group_rate),
                    str(agg.content_filtered),
                    f"{agg.judged}/{agg.generated}",
                ]
            )
            + " |"
        )
    return lines


def _agreement_section(agreement: Agreement) -> list[str]:
    if agreement.labelled == 0:
        return [
            "> **PROVISIONAL — the judge is uncalibrated.** No hand labels were "
            "supplied, so the verdicts below have no measured accuracy and "
            "should not be acted on. Run `--label`, fill in the template, and "
            "re-run `--report`.",
            "",
        ]
    lines = [
        f"**Judge agreement** ({agreement.labelled} hand-labelled images): "
        f"text {_pct(agreement.text_accuracy)}, "
        f"person {_pct(agreement.person_accuracy)}.",
        "",
    ]
    if not agreement.trustworthy:
        lines = [
            f"> **PROVISIONAL — judge agreement is below "
            f"{_pct(AGREEMENT_THRESHOLD)}.** These conclusions should not be "
            f"acted on until the judge is improved.",
            "",
        ] + lines
    return lines


def render_report(
    aggregates: list[VariantAggregate],
    agreement: Agreement,
    captured_at: str,
) -> str:
    lines = [
        "# Image Directive Evaluation",
        "",
        f"**Fixtures captured:** {captured_at}",
        "",
        *_agreement_section(agreement),
        "## Decision rule (fixed before the run)",
        "",
        "`clean_rate` is the share of judged images with no text, no person, and "
        "a cream background. A variant is adopted only if it beats "
        f"`{BASELINE_VARIANT}` on `clean_rate` **in both strata**. A variant "
        "that wins overall but loses on the `person` stratum is conditional, not "
        "adopted. \"No variant wins\" is a valid outcome and would indicate the "
        "leverage is in the planner, not the renderer.",
        "",
        "Rates divide by judged images, never by attempts. Generation failures "
        "and judge failures are excluded and reported separately so a variant "
        "cannot benefit from producing nothing.",
        "",
        "## Results",
        "",
    ]
    lines += _summary_table(aggregates)
    lines.append("")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest tests/test_eval_image_report.py -q`
Expected: PASS, 5 passed

- [ ] **Step 9: Run the full suite and lint, then commit**

Run: `uv run pytest -q && uv run ruff check .`

```bash
git add scripts/eval_image_report.py scripts/eval_image_scoring.py \
        tests/test_eval_image_report.py tests/test_eval_image_scoring.py
git commit -m "feat: add judge calibration and image evaluation report rendering"
```

---

### Task 5: Corpus stratification and brief caching

**Files:**
- Create: `scripts/eval_image.py`
- Create: `scripts/eval_fixtures/topics.json`
- Create: `tests/test_eval_image_runner.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `eval_store.load_fixtures`, `news_buddy.agent._summarize_one`, `news_buddy.llm.get_sub_model`.
- Produces:
  - `ROOT`, `FIXTURES_DIR`, `ARTIFACTS_DIR`, `TOPICS_FILE`, `BRIEFS_FILE` module constants
  - `load_topics(path: Path) -> dict[str, str]`
  - `cache_briefs(limit: int | None = None) -> int`
  - `load_briefs() -> dict[str, dict]`

- [ ] **Step 1: Ignore the regenerable artifacts**

Append to `.gitignore`:

```
# Image evaluation: regenerable artifacts and cached briefs
scripts/eval_artifacts/
scripts/eval_fixtures/briefs.json
```

- [ ] **Step 2: Build the stratification file**

Tag every fixture article as `mechanism` or `person`. A `person` article is one whose subject is a named individual or a company personified by one (executive announcements, personnel moves, personality profiles); a `mechanism` article is about a system, technique, product capability, or measurement.

```bash
uv run python - <<'PY'
import json, pathlib
articles = json.loads(pathlib.Path("scripts/eval_fixtures/articles.json").read_text())
for i, a in enumerate(articles):
    print(f"{i:3d}  {a['title'][:88]}")
PY
```

Write `scripts/eval_fixtures/topics.json` with exactly 8 of each, using the URLs printed above:

```json
{
  "mechanism": [
    "https://example.test/replace-with-real-url-1",
    "https://example.test/replace-with-real-url-2"
  ],
  "person": [
    "https://example.test/replace-with-real-url-9"
  ]
}
```

Requirement: exactly 8 URLs under each key, all present in `articles.json`. The file contains only URLs, no article text, so it is safe to commit.

- [ ] **Step 2b: Verify the stratification before relying on it**

Run this after Step 5 lands `load_topics` (it imports from the module):

```bash
uv run python -c "
import json, pathlib
from scripts.eval_image import load_topics
articles = {a['url'] for a in json.loads(
    pathlib.Path('scripts/eval_fixtures/articles.json').read_text())}
topics = load_topics()
counts = {}
for url, stratum in topics.items():
    counts[stratum] = counts.get(stratum, 0) + 1
missing = sorted(set(topics) - articles)
assert counts == {'mechanism': 8, 'person': 8}, f'expected 8/8, got {counts}'
assert not missing, f'urls not in articles.json: {missing}'
print('topics.json verified: 8 mechanism, 8 person, all present')
"
```

Expected: `topics.json verified: 8 mechanism, 8 person, all present`

- [ ] **Step 3: Write the failing loader tests**

Create `tests/test_eval_image_runner.py`:

```python
import json

import pytest

from scripts.eval_image import load_topics


def test_load_topics_maps_url_to_stratum(tmp_path):
    path = tmp_path / "topics.json"
    path.write_text(json.dumps({"mechanism": ["u1", "u2"], "person": ["u3"]}))
    topics = load_topics(path)
    assert topics == {"u1": "mechanism", "u2": "mechanism", "u3": "person"}


def test_load_topics_rejects_a_url_in_both_strata(tmp_path):
    path = tmp_path / "topics.json"
    path.write_text(json.dumps({"mechanism": ["u1"], "person": ["u1"]}))
    with pytest.raises(ValueError, match="both strata"):
        load_topics(path)


def test_load_topics_rejects_unknown_strata(tmp_path):
    path = tmp_path / "topics.json"
    path.write_text(json.dumps({"mechanism": ["u1"], "vibes": ["u2"]}))
    with pytest.raises(ValueError, match="unknown stratum"):
        load_topics(path)
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/test_eval_image_runner.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.eval_image'`

- [ ] **Step 5: Implement the loader and brief caching**

Create `scripts/eval_image.py`:

```python
"""Measure image contract violations across prompt directive variants.

Opt-in: this script makes real model and image API calls and is never run by
CI. It touches no production state and writes only to scripts/eval_artifacts/.

    python -m scripts.eval_image --brief
    python -m scripts.eval_image --run
    python -m scripts.eval_image --label
    python -m scripts.eval_image --report
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.eval_image_scoring import STRATA, VARIANTS

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "scripts" / "eval_fixtures"
ARTIFACTS_DIR = ROOT / "scripts" / "eval_artifacts"
TOPICS_FILE = FIXTURES_DIR / "topics.json"
BRIEFS_FILE = FIXTURES_DIR / "briefs.json"


def load_topics(path: Path = TOPICS_FILE) -> dict[str, str]:
    """Return {url: stratum}, rejecting overlaps and unknown strata."""
    data = json.loads(path.read_text(encoding="utf-8"))
    topics: dict[str, str] = {}
    for stratum, urls in data.items():
        if stratum not in STRATA:
            raise ValueError(f"unknown stratum {stratum!r} in {path}")
        for url in urls:
            if url in topics:
                raise ValueError(f"{url!r} appears in both strata in {path}")
            topics[url] = stratum
    return topics


def cache_briefs(limit: int | None = None) -> int:
    """Generate one brief per article, once, and cache it. Returns brief count."""
    import yaml

    from news_buddy import agent as agent_module
    from news_buddy.agent import _summarize_one
    from news_buddy.llm import get_sub_model
    from scripts.eval_store import load_fixtures

    articles = load_fixtures(FIXTURES_DIR)
    topics = load_topics()
    articles = [a for a in articles if a["url"] in topics]
    if limit:
        articles = articles[:limit]

    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    sub_llm = get_sub_model(config)

    bodies = {a["url"]: a["body"] for a in articles}
    original = agent_module._extract.extract_body
    agent_module._extract.extract_body = lambda url: bodies.get(url, "")
    briefs: dict[str, dict] = {}
    try:
        for article in articles:
            try:
                item, _tokens, _body = _summarize_one(sub_llm, article)
            except Exception as exc:  # noqa: BLE001 - a failed brief is data
                print(f"[warn] brief failed for {article['url']}: {exc}", file=sys.stderr)
                continue
            briefs[article["url"]] = {
                key: item.get(key)
                for key in ("title", "summary", "image_prompt", "image_layout",
                            "image_labels", "image_alt")
            }
            print(f"  brief: {article['title'][:60]}", file=sys.stderr)
    finally:
        agent_module._extract.extract_body = original

    BRIEFS_FILE.write_text(
        json.dumps(briefs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return len(briefs)


def load_briefs() -> dict[str, dict]:
    if not BRIEFS_FILE.exists():
        raise RuntimeError(
            f"{BRIEFS_FILE} is missing. Run: python -m scripts.eval_image --brief"
        )
    return json.loads(BRIEFS_FILE.read_text(encoding="utf-8"))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_eval_image_runner.py -q`
Expected: PASS, 3 passed

- [ ] **Step 7: Generate the briefs**

Run: `uv run python -m scripts.eval_image --brief`

This step is added in Task 7 when the CLI lands; until then invoke it directly:

```bash
uv run python -c "from scripts.eval_image import cache_briefs; print(cache_briefs())"
```

Expected: prints 16, and `scripts/eval_fixtures/briefs.json` exists with 16 entries.

- [ ] **Step 8: Commit**

```bash
git add scripts/eval_image.py scripts/eval_fixtures/topics.json \
        tests/test_eval_image_runner.py .gitignore
git commit -m "feat: add corpus stratification and cached brief generation"
```

---

### Task 6: Variant assembly and the 2×2 run

**Files:**
- Modify: `scripts/eval_image.py` (append)
- Modify: `tests/test_eval_image_runner.py` (append)

**Interfaces:**
- Consumes: `load_topics`, `load_briefs` from Task 5; `ImageResult`, `VARIANTS` from Task 3; `background_is_cream`, `background_distance` from Task 2; `ImageJudge` from Task 1.
- Produces:
  - `POSITIVE_DIRECTIVE: str`
  - `negated_directive() -> str`
  - `assemble_prompt(article_prompt: str, directive: str, preserve: bool) -> str`
  - `variant_prompt(item: dict, variant: str) -> str`
  - `run_variants(judge, client_factory, limit=None) -> list[ImageResult]`

- [ ] **Step 1: Write the failing assembly tests**

Append to `tests/test_eval_image_runner.py`:

```python
from news_buddy.image_generator import MAX_IMAGE_PROMPT_CHARS
from scripts.eval_image import assemble_prompt


def test_truncated_assembly_loses_the_directive_tail():
    """Reproduces the production defect: the contract is what gets cut."""
    article = "A" * 600
    directive = "D" * 390
    prompt = assemble_prompt(article, directive, preserve=False)
    assert len(prompt) == MAX_IMAGE_PROMPT_CHARS
    assert directive not in prompt


def test_preserved_assembly_keeps_the_whole_directive():
    article = "A" * 600
    directive = "D" * 390
    prompt = assemble_prompt(article, directive, preserve=True)
    assert len(prompt) <= MAX_IMAGE_PROMPT_CHARS
    assert directive in prompt


def test_preserved_assembly_trims_the_article_half_instead():
    article = "A" * 600
    directive = "D" * 390
    prompt = assemble_prompt(article, directive, preserve=True)
    assert prompt.count("A") < 600


def test_short_prompts_are_identical_under_both_assemblies():
    article = "A" * 50
    directive = "D" * 100
    assert assemble_prompt(article, directive, preserve=False) == assemble_prompt(
        article, directive, preserve=True
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_eval_image_runner.py -q`
Expected: FAIL with `ImportError: cannot import name 'assemble_prompt'`

- [ ] **Step 3: Implement assembly and the run loop**

Append to `scripts/eval_image.py`:

```python
POSITIVE_DIRECTIVE = (
    "Warm cream paper background. Flat hand-drawn editorial spot illustration "
    "with thick charcoal outlines and one muted brick-red or ochre accent. "
    "Exactly three inanimate symbolic objects in a clean horizontal row, "
    "linked by bold directional arrows. Every object is a simple mechanical or "
    "geometric form with smooth, blank, unmarked surfaces. Generous empty "
    "space surrounds each object. The image communicates purely through shape "
    "and arrangement."
)


def negated_directive() -> str:
    """Read the live production directive; never a copy."""
    from news_buddy.image_generator import (
        _STYLE_DIRECTIVE_MARKERS,
        _read_marked_section,
    )

    return _read_marked_section(
        ROOT / "prompts" / "image_style.md", _STYLE_DIRECTIVE_MARKERS
    )


def assemble_prompt(article_prompt: str, directive: str, preserve: bool) -> str:
    """Join the article half and the directive.

    preserve=False reproduces production: concatenate, then truncate the whole
    thing, which cuts the directive off the end.
    preserve=True reserves room for the directive and trims the article instead.
    """
    from news_buddy.image_generator import MAX_IMAGE_PROMPT_CHARS

    tail = f"\n\nVisual direction: {directive}"
    if not preserve:
        return (article_prompt + tail)[:MAX_IMAGE_PROMPT_CHARS]
    room = max(0, MAX_IMAGE_PROMPT_CHARS - len(tail))
    return article_prompt[:room] + tail


def variant_prompt(item: dict, variant: str) -> str:
    from news_buddy.image_generator import _visual_prompt

    phrasing, assembly = variant.split("-")
    directive = POSITIVE_DIRECTIVE if phrasing == "positive" else negated_directive()
    return assemble_prompt(
        _visual_prompt(item), directive, preserve=(assembly == "preserved")
    )
```

- [ ] **Step 4: Run the assembly tests to verify they pass**

Run: `uv run pytest tests/test_eval_image_runner.py -q`
Expected: PASS, 7 passed

- [ ] **Step 5: Implement the run loop**

Append to `scripts/eval_image.py`:

```python
def run_variants(judge, client_factory, limit: int | None = None) -> list[ImageResult]:
    """Render every variant for every article and score the raw bytes."""
    import dataclasses

    import yaml

    from news_buddy.image_generator import ImageContentFilteredError, ImageSettings
    from scripts.eval_image_scoring import (
        ImageResult,
        background_distance,
        background_is_cream,
    )

    topics = load_topics()
    briefs = load_briefs()
    urls = [u for u in briefs if u in topics]
    if limit:
        urls = urls[:limit]

    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    base = ImageSettings.from_config(config["images"])
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    results: list[ImageResult] = []
    for url in urls:
        item = briefs[url]
        for variant in VARIANTS:
            prompt = variant_prompt(item, variant)
            settings = dataclasses.replace(base, style="")
            client = client_factory(settings)
            try:
                raw = client.text_to_image(
                    prompt,
                    model=settings.model,
                    width=settings.width,
                    height=settings.height,
                    negative_prompt=settings.negative_prompt,
                )
            except ImageContentFilteredError as exc:
                results.append(ImageResult(url, topics[url], variant, ok=False,
                                           error=str(exc), content_filtered=True))
                continue
            except Exception as exc:  # noqa: BLE001 - a failed render is data
                results.append(ImageResult(url, topics[url], variant, ok=False,
                                           error=f"{type(exc).__name__}: {exc}"[:160]))
                continue

            stem = f"{variant}__{abs(hash(url)) % 10**8}"
            (ARTIFACTS_DIR / f"{stem}.png").write_bytes(raw)
            verdict = judge.judge(raw)
            results.append(
                ImageResult(
                    article_url=url,
                    stratum=topics[url],
                    variant=variant,
                    ok=True,
                    background_is_cream=background_is_cream(raw),
                    background_distance=background_distance(raw),
                    has_text=verdict.has_text,
                    has_person=verdict.has_person,
                    object_group_count=verdict.object_group_count,
                    judge_error=verdict.error,
                )
            )
            print(f"  {variant}: {url[:50]}", file=sys.stderr)

    (ARTIFACTS_DIR / "results.json").write_text(
        json.dumps([dataclasses.asdict(r) for r in results], indent=2),
        encoding="utf-8",
    )
    return results
```

Note: `variant_prompt` already embeds the directive, so `settings.style` is
blanked to prevent `_request_prompt` appending it a second time. The client is
called directly rather than through `generate_article_images`, so no WebP is
written and no label band is applied.

- [ ] **Step 6: Write a run-loop test with fakes**

Append to `tests/test_eval_image_runner.py`:

```python
import io

from PIL import Image

from scripts import eval_image
from scripts.eval_image_judge import JudgeVerdict


def _png(color=(243, 236, 216)):
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="PNG")
    return buf.getvalue()


class _FakeJudge:
    def judge(self, image_bytes, mime_type="image/png"):
        return JudgeVerdict(has_text=False, has_person=False, object_group_count=3)


class _FakeImageClient:
    def __init__(self, settings):
        self.settings = settings

    def text_to_image(self, prompt, *, model, width, height, negative_prompt):
        return _png()


def test_run_variants_produces_one_result_per_variant(monkeypatch, tmp_path):
    monkeypatch.setattr(eval_image, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(eval_image, "load_topics", lambda *a, **k: {"u1": "mechanism"})
    monkeypatch.setattr(
        eval_image, "load_briefs",
        lambda: {"u1": {"title": "T", "summary": "S", "image_prompt": "P",
                        "image_layout": "pipeline", "image_labels": ["A", "B", "C"],
                        "image_alt": "alt"}},
    )
    results = eval_image.run_variants(_FakeJudge(), _FakeImageClient)
    assert len(results) == 4
    assert {r.variant for r in results} == set(eval_image.VARIANTS)
    assert all(r.ok for r in results)
    assert all(r.background_is_cream for r in results)
```

- [ ] **Step 7: Run the tests and lint**

Run: `uv run pytest tests/test_eval_image_runner.py -q && uv run ruff check .`
Expected: PASS, 8 passed

- [ ] **Step 8: Commit**

```bash
git add scripts/eval_image.py tests/test_eval_image_runner.py
git commit -m "feat: add variant prompt assembly and the 2x2 image run"
```

---

### Task 7: Labelling, report wiring, and the CLI

**Files:**
- Modify: `scripts/eval_image.py` (append)
- Modify: `tests/test_eval_image_runner.py` (append)
- Modify: `README.md` (document the harness)

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces:
  - `write_label_template(results, sample_size=20) -> Path`
  - `load_labels() -> dict[str, dict]`
  - `build_report(output: Path) -> Path`
  - `main(argv: list[str] | None = None) -> int`

- [ ] **Step 1: Write the failing labelling tests**

Append to `tests/test_eval_image_runner.py`:

```python
import json as _json

from scripts.eval_image_scoring import ImageResult


def _res(url, variant="negated-truncated"):
    return ImageResult(article_url=url, stratum="mechanism", variant=variant,
                       ok=True, has_text=False, has_person=False,
                       object_group_count=3, background_is_cream=True)


def test_label_template_has_one_entry_per_sampled_image(monkeypatch, tmp_path):
    monkeypatch.setattr(eval_image, "ARTIFACTS_DIR", tmp_path)
    results = [_res(f"u{i}") for i in range(30)]
    path = eval_image.write_label_template(results, sample_size=5)
    data = _json.loads(path.read_text())
    assert len(data) == 5
    assert all(set(v) == {"has_text", "has_person"} for v in data.values())
    assert all(v["has_text"] is None for v in data.values())


def test_label_template_never_samples_more_than_available(monkeypatch, tmp_path):
    monkeypatch.setattr(eval_image, "ARTIFACTS_DIR", tmp_path)
    path = eval_image.write_label_template([_res("u1")], sample_size=20)
    assert len(_json.loads(path.read_text())) == 1


def test_load_labels_ignores_unfilled_entries(monkeypatch, tmp_path):
    monkeypatch.setattr(eval_image, "ARTIFACTS_DIR", tmp_path)
    (tmp_path / "labels.json").write_text(_json.dumps({
        "negated-truncated::u1": {"has_text": True, "has_person": False},
        "negated-truncated::u2": {"has_text": None, "has_person": None},
    }))
    labels = eval_image.load_labels()
    assert set(labels) == {"negated-truncated::u1"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_eval_image_runner.py -q`
Expected: FAIL with `AttributeError: module 'scripts.eval_image' has no attribute 'write_label_template'`

- [ ] **Step 3: Implement labelling and report wiring**

Append to `scripts/eval_image.py`:

```python
def write_label_template(results, sample_size: int = 20) -> Path:
    """Emit an empty labels file for hand calibration. Deterministic sample."""
    from scripts.eval_image_scoring import label_key

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    judged = [r for r in results if r.ok]
    sample = sorted(judged, key=lambda r: label_key(r.variant, r.article_url))
    sample = sample[:sample_size]
    template = {
        label_key(r.variant, r.article_url): {"has_text": None, "has_person": None}
        for r in sample
    }
    path = ARTIFACTS_DIR / "labels.json"
    path.write_text(json.dumps(template, indent=2), encoding="utf-8")
    return path


def load_labels() -> dict[str, dict]:
    """Read hand labels, ignoring entries still left as null."""
    path = ARTIFACTS_DIR / "labels.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        key: value
        for key, value in raw.items()
        if isinstance(value.get("has_text"), bool)
        and isinstance(value.get("has_person"), bool)
    }


def load_results() -> list:
    from scripts.eval_image_scoring import ImageResult

    path = ARTIFACTS_DIR / "results.json"
    if not path.exists():
        raise RuntimeError(
            f"{path} is missing. Run: python -m scripts.eval_image --run"
        )
    return [ImageResult(**row) for row in json.loads(path.read_text(encoding="utf-8"))]


def build_report(output: Path) -> Path:
    from datetime import datetime, timezone

    from scripts.eval_image_report import render_report
    from scripts.eval_image_scoring import VARIANTS, aggregate, judge_agreement

    results = load_results()
    aggregates = [
        aggregate(variant, [r for r in results if r.variant == variant])
        for variant in VARIANTS
    ]
    agreement = judge_agreement(results, load_labels())
    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_report(aggregates, agreement, captured_at), encoding="utf-8"
    )
    return output
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_eval_image_runner.py -q`
Expected: PASS, 11 passed

- [ ] **Step 5: Implement the CLI**

Append to `scripts/eval_image.py`:

```python
def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", action="store_true",
                        help="Generate and cache one brief per article")
    parser.add_argument("--run", action="store_true",
                        help="Render every variant and judge the raw images")
    parser.add_argument("--label", action="store_true",
                        help="Emit a labels template for judge calibration")
    parser.add_argument("--report", action="store_true",
                        help="Aggregate results and write the markdown report")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--judge-model", default=None)
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "docs" / "evals" / "2026-08-15-image-directive.md",
    )
    args = parser.parse_args(argv)

    if args.brief or args.run:
        if not os.getenv("NVIDIA_API_KEY", "").strip():
            raise SystemExit(
                "NVIDIA_API_KEY is not set. Create a key at "
                "https://build.nvidia.com/ and add it to .env."
            )
    if args.run and not os.getenv("GOOGLE_API_KEY", "").strip():
        raise SystemExit("GOOGLE_API_KEY is not set; the image judge requires it.")

    if args.brief:
        print(f"Cached {cache_briefs(args.limit)} briefs to {BRIEFS_FILE}")
        return 0

    if args.run:
        from news_buddy.image_generator import _NvidiaImageClient
        from scripts.eval_image_judge import DEFAULT_JUDGE_MODEL, ImageJudge

        token = os.getenv("NVIDIA_API_KEY", "").strip()
        judge = ImageJudge(model=args.judge_model or DEFAULT_JUDGE_MODEL)
        results = run_variants(
            judge, lambda settings: _NvidiaImageClient(settings, token), args.limit
        )
        print(f"Rendered and judged {len(results)} images into {ARTIFACTS_DIR}")
        return 0

    if args.label:
        path = write_label_template(load_results())
        print(f"Label template written to {path}. Fill in each true/false, "
              f"then run --report.")
        return 0

    if args.report:
        print(f"Report written to {build_report(args.output)}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Verify the CLI help works and no mode runs by accident**

Run: `uv run python -m scripts.eval_image`
Expected: prints help, exits 1, makes no network calls.

- [ ] **Step 7: Document the harness in the README**

In `README.md`, immediately after the `## Model Evaluation` section, add:

```markdown
## Image Directive Evaluation

`scripts/eval_image.py` measures whether changing the image style directive
reduces contract violations. It renders a 2×2 of `{negated, positive}` phrasing
× `{truncated, contract-preserved}` assembly over a 16-article corpus stratified
into mechanism and person topics, then scores the **raw** provider output with a
deterministic background check plus a calibrated vision judge.

Like the model eval it is opt-in and never run by CI, since it makes real image
and vision API calls:

```bash
python -m scripts.eval_image --brief    # once: cache one brief per article
python -m scripts.eval_image --run      # 64 renders, judged
python -m scripts.eval_image --label    # fill in the template by hand
python -m scripts.eval_image --report   # aggregate -> docs/evals/
```

The judge's agreement with your hand labels is printed in the report header;
below 90% the report marks its own conclusions provisional.
```

- [ ] **Step 8: Run the full suite and lint**

Run: `uv run pytest -q && uv run ruff check .`
Expected: all tests pass, "All checks passed!"

- [ ] **Step 9: Commit**

```bash
git add scripts/eval_image.py tests/test_eval_image_runner.py README.md
git commit -m "feat: add labelling, report wiring, and the image eval CLI"
```

---

## Execution notes

Tasks 1–4 are pure and offline; they can be implemented and reviewed without any
API key. Task 5 onward needs `NVIDIA_API_KEY` and `GOOGLE_API_KEY`.

The actual evaluation run is deliberately **not** part of this plan. Once the
harness is merged, running it is a separate act with a real cost (16 summarizer
calls, 64 image generations, 64 judge calls, roughly 10–20 minutes) and its own
output — a report committed to `docs/evals/`, plus a decision about
`prompts/image_style.md` taken against the rule fixed in the spec.
