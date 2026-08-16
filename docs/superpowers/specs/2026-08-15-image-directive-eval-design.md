# Image Directive Evaluation Harness — Design

**Date:** 2026-08-15
**Status:** Approved for planning
**Related:** #19 (negative prompt discarded), #20 (fix merged)

## Problem

Published article illustrations violate their own visual contract. Surveying
recent digests: `2026-08-12`, `2026-08-13`, and `2026-08-15` heroes contain
garbled pseudo-text, and `2026-08-13` also contains human figures, which
`prompts/image_style.md` explicitly forbids. `2026-08-10` and `2026-08-11` are
clean. Roughly half of recent hero images fail.

Two causes are suspected, and they are independent:

1. **Truncation.** `_request_prompt` concatenates the article prompt with the
   style directive and truncates the result to `MAX_IMAGE_PROMPT_CHARS` (800).
   The directive sits at the end, so it is what gets cut. When the model's
   `image_prompt` reaches its 280-character cap, **46% of the directive is
   discarded**, and the discarded tail is exactly the clause forbidding text and
   people. Whether the contract reaches the model at all depends on how verbose
   the summarizer was that day.

   | `image_prompt` length | Directive surviving |
   |---|---|
   | 0 | 390/390 |
   | 100 | 390/390 |
   | 180 | 311/390 (20% lost) |
   | 280 (cap) | 211/390 (46% lost) |

2. **Phrasing.** The directive states its constraints as negations ("No words,
   letters, numbers, people, logos…"). FLUX.2 is guidance-distilled and has no
   classifier-free-guidance path to push tokens away, so naming forbidden things
   may raise their likelihood. Black Forest Labs' prompting guide advises
   describing what you want instead.

An informal probe on 2 articles produced 6 images across all four combinations,
none clean. It was too small to conclude anything and was confounded: both
articles were about named executives, so the summarizer planned person-centric
imagery that no rendering directive would override.

**This harness exists to replace that guess with a measurement.**

## Goal

Decide whether to change `prompts/image_style.md`, fix the truncation, both, or
neither — on evidence, using the same discipline `scripts/eval_sub_model.py`
applied to model selection.

Non-goals: monitoring published image quality over time; changing the planner
prompt; changing production behaviour. This harness only produces a report.

## Decision rule (fixed before running)

The headline metric is **`clean_rate`**: the share of judged images with no
text, no person, and a cream background.

- A variant is adopted only if it beats `negated-truncated` (production) on
  `clean_rate` **in both strata**.
- A variant that wins overall but loses on the `person` stratum is reported as
  conditional, not adopted.
- **"No variant wins" is a valid outcome.** It would indicate the leverage is in
  the planner, not the renderer, and the report says so rather than
  manufacturing a recommendation.

Fixing this rule before the run mirrors the sub-model eval, where the incumbent
was kept because it won on a gate chosen in advance.

## Architecture

```
scripts/
├── eval_store.py            existing, reused unchanged
├── eval_image_scoring.py    NEW  pure scoring + aggregation, no network
├── eval_image_report.py     NEW  markdown rendering
└── eval_image.py            NEW  runner / CLI
scripts/eval_fixtures/
├── articles.json            existing, gitignored
├── manifest.json            existing, committed
├── topics.json              NEW  committed: url -> stratum
└── briefs.json              NEW  gitignored, regenerable
scripts/eval_artifacts/      NEW  gitignored: raw PNGs, judge output, labels
```

`eval_store.py` is reused as-is: it already provides manifest-verified fixtures
with bodies excluded from git. `eval_scoring.py` and `eval_report.py` are *not*
extended — their `ArticleResult` and `ModelAggregate` are shaped around summary
metrics, and adding image fields would leave both carrying values meaningless to
half their callers.

### Flow

1. Load fixtures via `eval_store.load_fixtures()` (manifest-verified).
2. Stratify from committed `topics.json`.
3. Generate one brief per article via `_summarize_one`, cached to `briefs.json`.
4. Render 4 cells per article, keeping **raw** provider bytes.
5. Score: deterministic palette, then vision judge.
6. Aggregate and render to `docs/evals/`.

### Two deliberate choices

**Raw bytes, not published WebP.** `_add_label_band` deliberately crops and
covers model-drawn captions. Scoring the post-crop image would measure the crop,
not the model.

**Briefs cached, generated once.** All four cells consume the identical brief,
isolating the directive as the only variable. Re-running the comparison must not
re-roll the summarizer.

## Variants

Full 2×2: `{negated, positive} × {truncated, preserved}`.

| Variant | Directive | Assembly |
|---|---|---|
| `negated-truncated` | live `image_style.md` | current `_request_prompt` |
| `negated-preserved` | live `image_style.md` | contract-first |
| `positive-truncated` | harness-defined | current `_request_prompt` |
| `positive-preserved` | harness-defined | contract-first |

**Contract-first assembly** reserves room for the directive and truncates the
*article* half instead:

```python
tail = f"\n\nVisual direction: {style}"
prompt = article_prompt[:max(0, MAX_IMAGE_PROMPT_CHARS - len(tail))] + tail
```

The `negated` directive is read live from `prompts/image_style.md` via the
existing `_read_marked_section`, never copy-pasted, so the baseline cell is
always exactly what production ships. Only `positive` is defined in the harness.

### The positive candidate

```
Warm cream paper background. Flat hand-drawn editorial spot illustration with
thick charcoal outlines and one muted brick-red or ochre accent. Exactly three
inanimate symbolic objects in a clean horizontal row, linked by bold directional
arrows. Every object is a simple mechanical or geometric form with smooth,
blank, unmarked surfaces. Generous empty space surrounds each object. The image
communicates purely through shape and arrangement.
```

Every constraint restated as a description: "inanimate" for no people; "blank,
unmarked surfaces" and "communicates purely through shape" for no text.

## Corpus

16 articles: **8 `mechanism`-topic, 8 `person`-topic**, tagged by hand once in
`topics.json`. 16 × 4 = **64 images**, one sample per cell.

Stratification is the core of the design. Today's evidence suggests article topic
dominates: a story about a named executive yields a person-centric brief that no
renderer directive overrides. Without strata, a variant could win purely by
drawing easier articles. Every rate is reported per stratum as well as overall.

`topics.json` contains only URLs and tags — no article bodies — so it is safe to
commit alongside `manifest.json`.

### The corpus lives in its own directory

`scripts/eval_image_fixtures/`, **not** the sub_model harness's
`scripts/eval_fixtures/`. Two reasons:

1. `--capture` overwrites both `articles.json` and the committed
   `manifest.json` of whatever directory it targets. `scripts/eval_fixtures/`
   holds the frozen record behind a published sub_model baseline report;
   recapturing there would destroy that provenance.
2. The two evaluations need corpora selected on different criteria. The
   sub_model corpus was captured for summarizer quality and happens to contain
   only 5 articles with a named individual as the headline's subject — not
   enough to fill a balanced `person` stratum. A first attempt at 8/8 from that
   pool had to pad with three corporate/deal stories, which the reviewers
   correctly judged too weak to support the comparison.

The image corpus is 60 articles captured 2026-08-16, from which 16 are tagged.
Selection rule applied: `person` requires a **human being at the story's
centre**, not merely quoted within it. Corporate funding, acquisition, and
product-launch stories are excluded from both strata, since they were the
source of the earlier ambiguity.

## Scoring

### Deterministic (Pillow + numpy, no network)

**One check:** `background_is_cream` — median colour of an 8px border ring,
Euclidean RGB distance to the cream token `#f3ecd8` (243, 236, 216), violation
above a threshold of **30**.

Measured on raw generations, this separates cleanly:

| Background | Distance to cream |
|---|---|
| White (violation) | 36.0 – 43.5 |
| Cream (compliant) | 6.4 – 23.0 |

**Fixtures must be raw generations, not published WebPs.** Measurement showed all
five recent published heroes score an identical distance of 1.0, because
`_add_label_band` composites every image onto cream paper before saving. A
published image can never fail this check. This is the same reason the harness
scores raw provider bytes throughout.

**`high_chroma_share` was specified and then dropped.** Measured across the same
raw images it does not discriminate: the two most palette-compliant images scored
highest (0.0498, 0.0504) while a white-background violation scored lowest
(0.0071). It measures how much ink is on the page, not whether the palette obeys
the contract. Recorded here so it is not re-proposed later.

### Judged (vision model, strict JSON)

```json
{"has_text": bool, "has_person": bool, "object_group_count": int}
```

Three fields, each answerable from the image alone. `object_group_count` tests
the "exactly three groups" rule.

**Judge model: `gemini-3.5-flash`, verified against the account before
pinning.** Probed on two known images: it correctly returned `has_text: true`
for a text-heavy generation and correctly flagged the publisher's own composited
legend as text on a published WebP — which independently confirms that raw bytes,
not published images, are the right scoring input. Exposed as `--judge-model`.

### Calibration

Before conclusions are trusted, `--label` samples ~20 of the 64 raw images and
emits a contact sheet plus an empty labels template. The user labels `has_text`
and `has_person` by eye. `--report` computes judge agreement: overall accuracy
plus per-class false-positive and false-negative rates.

**The agreement rate appears in the report header.** Below **90% agreement on
either `has_text` or `has_person`**, the report marks its conclusions provisional
and states that the variant comparison should not be acted on until the judge is
improved. This follows the precedent of `classify_failure`, which documents
itself as "heuristic, not exact" rather than implying precision it lacks.

### Data shapes

```python
@dataclass
class ImageResult:
    article_url: str
    stratum: str                    # "mechanism" | "person"
    variant: str
    ok: bool                        # generation succeeded
    error: str
    content_filtered: bool
    background_is_cream: bool
    background_distance: float
    has_text: bool | None           # None = judge failed
    has_person: bool | None
    object_group_count: int | None
    judge_error: str

@dataclass
class VariantAggregate:
    variant: str
    generated: int                  # successful generations
    judged: int                     # rate denominator
    clean_rate: float               # headline
    text_rate: float
    person_rate: float
    palette_rate: float
    three_group_rate: float
    content_filtered: int
    by_stratum: dict[str, "VariantAggregate"]
```

## Error handling

Two failure modes, both handled so neither can flatter a variant:

- **Generation failure** (content filter, network) — recorded with `ok=False`,
  excluded from violation rates, and reported in its own `content_filtered`
  column. A variant must not win by failing to produce images. Today the same
  article was filtered under every condition, so this needs visibility.
- **Judge failure** — the field is `None`, excluded from that rate, never coerced
  to "clean".

**Rates divide by `judged`, not `generated`, and both counts appear in the
report.** This is the bug already found and corrected once in the sub-model
eval, where mean tokens were divided by all attempts including zero-token
failures, silently pulling the mean toward zero.

## CLI

```bash
python -m scripts.eval_image --brief     # once: cache one brief per article
python -m scripts.eval_image --run       # 64 generations, judged, raw PNGs saved
python -m scripts.eval_image --label     # contact sheet + labels template
python -m scripts.eval_image --report    # aggregate + agreement -> docs/evals/
```

Flags: `--limit` (articles), `--variants` (subset), `--judge-model`, `--rpm`,
`--output`.

## Safety

Same posture as `eval_sub_model.py`:

- Opt-in; **never run by CI**; makes real API calls.
- Fails fast if `NVIDIA_API_KEY` is unset rather than reporting every cell as
  unavailable.
- Touches no production state: no `state.db`, no Chroma, no `~/news/`.
- Artifacts write to gitignored `scripts/eval_artifacts/`, deliberately **not**
  the production image cache, so a run cannot poison `~/news/images/`.
- Does not modify `prompts/image_style.md`. Variants are assembled in memory.

## Cost

| Resource | Count |
|---|---|
| Summarizer calls | 16 (once, cached) |
| Image generations | 64 |
| Vision judge calls | 64 |

Runtime is dominated by generation; observed per-image latency was roughly 5–15
seconds including network, giving **~10–20 minutes end to end** under the
configured rate limit. Dollar cost depends on the account's NVIDIA plan and is
deliberately not estimated here.

## Testing

`eval_image_scoring.py` is pure and unit-tested without network:

- Aggregation over synthetic `ImageResult` lists, including the `judged` vs
  `generated` denominator and per-stratum splits.
- Palette checks against both solid-colour PIL images generated in-test (a
  cream square passes, a white square fails) and committed raw-generation
  fixtures spanning the measured 6.4–43.5 distance range.
- Judge-failure and generation-failure paths asserted to be excluded from rates
  rather than counted as clean.
- Contract-first assembly asserted to preserve the full directive at the
  280-character `image_prompt` cap, where current assembly loses 46%.

The judge client is mocked at its boundary. `eval_image.py` (network I/O) follows
the existing harness convention of thin, lightly-tested orchestration.

## Report output

Written to `docs/evals/YYYY-MM-DD-image-directive.md`. Header states the decision
rule and the judge agreement rate. Headline table:

| Variant | Clean (all) | Clean (mechanism) | Clean (person) | Text | Person | Palette | 3-group | Filtered | Judged n |
|---|---|---|---|---|---|---|---|---|---|

Followed by a per-variant failure breakdown and a sample of scored images with
their verdicts, mirroring `eval_report.py`'s structure.
