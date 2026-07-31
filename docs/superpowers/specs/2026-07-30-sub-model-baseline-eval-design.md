# Sub-Model Baseline Evaluation Harness — Design

**Date:** 2026-07-30
**Status:** Approved (design), pending implementation plan

## Goal

Measure how the digest's `sub_model` actually performs before deciding whether
to change it. The deliverable is an evaluation harness plus a baseline report
comparing the current model against a shortlist of candidates on identical
inputs, scored by the pipeline's own validators.

This work changes no runtime behavior and swaps no model. It produces the
evidence needed to make that decision later.

## Context

`llm.sub_model` is `meta/llama-3.1-8b-instruct` on NVIDIA NIM
([`config.yaml`](../../../config.yaml)). It is the only model the active graph
calls. For every selected article it must return a single JSON object holding
both a 70–110 word reader briefing and a complete editorial image brief
(`image_prompt`, `image_layout`, `image_labels`, `image_alt`), defined by
[`prompts/summarizer.md`](../../../prompts/summarizer.md).

Three properties of the existing implementation shape this design.

**Structured output failure is publication failure.** `_summarize_one` in
[`news_buddy/agent.py`](../../../news_buddy/agent.py) parses the response, and
on `JSONDecodeError` substitutes a fallback dict carrying no image fields.
`_article_brief_errors` then rejects it, `_summarize_one` raises, the worker
returns a low-importance fallback item, and with `images.require_all: true` the
image node stops publication. A model that writes good prose but unreliable
JSON breaks the digest.

**The output budget is tight.** `llm.max_tokens` is 512, and that must cover
the summary and the whole image brief. This rules out reasoning models
categorically: probing during the OpenWiki work showed
`nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` returning 4246 tokens against a
1200-token cap.

**The provider ignores `json_mode`.** `get_sub_model()` passes
`json_mode=True`, and `_build_google` and `_build_huggingface` honour it, but
`_build_nvidia` does not — it sends no `response_format`. On the active
provider, JSON adherence rests entirely on prompt instructions plus the
code-fence stripping in `_summarize_one`. This is noted as an observation, not
addressed here.

`main_model` is configured but unused by the graph and is out of scope.

## Non-goals

- Changing `llm.sub_model` or any other runtime configuration.
- Fixing the `json_mode` gap in `_build_nvidia`.
- Adding an LLM-as-judge. It adds cost, another model dependency, and its own
  bias, and judge disagreement is hard to adjudicate.
- Evaluating `main_model`, image generation models, or the RAG embedding model.

## Approach

Drive the real production code path rather than reimplementing it. The harness
calls `_summarize_one` directly and scores with `RubricMiddleware` and
`_article_brief_errors`. A reimplementation would duplicate prompt assembly and
parsing, and would silently drift from production — which would make the
measurement worthless for its only purpose.

The one obstacle is that `_summarize_one` opens by calling
`_extract.extract_body(item["url"])`, which requires network access and defeats
frozen inputs. The harness patches that module attribute to return the fixture
body.

This coupling to a private function is a deliberate, recorded trade. The
alternative — adding an optional `body` parameter to `_summarize_one` — is
cleaner and would make the function testable for the first time, but was ruled
out to keep this work free of runtime changes. If the patching proves fragile,
that seam is the fix.

## Components

### 1. Fixture store

Real article bodies are required, and this repository is public. Committing
4,000-character excerpts of third-party news articles raises a copyright
question this work should not answer, so the corpus is split:

The corpus is 25 articles. That is large enough for the rates to mean
something and small enough that a five-model session stays inside twenty
minutes at the configured throttle.

- `scripts/eval_fixtures/articles.json` — titles, URLs, metadata, and extracted
  bodies. **Gitignored.** Regenerable via `--capture`.
- `scripts/eval_fixtures/manifest.json` — **committed.** One record per article:
  url, title, source, SHA-256 of the body, capture timestamp.

Every model in a comparison session sees byte-identical inputs, which is the
property that matters. The manifest records exactly which articles were used
and lets a re-capture be verified against the original. Reproducibility is lost
if source links rot; that is accepted rather than republishing article text.

The harness refuses to run when a fixture body's hash does not match its
manifest entry.

### 2. Runner

For each candidate model: build a `sub_llm` through `get_sub_model()` with an
overridden `llm.sub_model`, patch `_extract.extract_body`, and call
`_summarize_one` once per fixture article.

Runs execute under production settings — `max_tokens: 512`,
`temperature: 0.2`, the real prompts. A larger model still has to fit summary
and brief inside 512 tokens; that constraint is part of what is being measured.

Articles are processed sequentially, not through the five-worker pool, so
latency figures are per-call and the requests-per-minute throttle does not
confound them.

### 3. Retry measurement

The strict-retry logic lives in `summarize_articles_node`, not in
`_summarize_one`, so the harness has no production function to reuse for it.
Rather than copy the node's control flow — the same drift risk that ruled out
reimplementation — the harness measures two populations:

1. **First attempt:** `_summarize_one(...)` over all fixtures.
2. **Strict recovery:** `_summarize_one(..., strict=True)` over only those
   articles whose first attempt failed the rubric.

These are the same two calls production makes, expressed as measured
populations instead of duplicated orchestration.

### 4. Scorer

The real `RubricMiddleware` and `_article_brief_errors`. No new judging logic.

### 5. Reporter

Markdown written to `docs/evals/YYYY-MM-DD-sub-model-baseline.md`.

## Data flow

```
--capture:  gh-pages index.json -> dated JSON records -> article URLs
            -> extract_body() -> articles.json (local)
                              -> manifest.json (committed)

--run:      fixtures x models
            -> _summarize_one (real path, patched body source)
            -> RubricMiddleware + _article_brief_errors
            -> per-article records -> aggregate -> markdown report
```

## Metrics

Per model:

| Metric | Purpose |
| --- | --- |
| Brief validity rate | Headline number: an invalid brief blocks publication |
| Failure breakdown by field | Which of `image_prompt`, `image_layout`, `image_labels`, short labels, article-specific labels, `image_alt` fail |
| First-attempt rubric pass rate | How often a summary passes without a retry |
| Strict recovery rate | Whether the retry actually rescues failures |
| Output tokens, and cap hits | Any response at the 512 ceiling is truncating |
| Latency p50 / p95 | Feeds the digest's runtime budget |
| Summary word count vs 70–110 | Direct prompt-adherence check |

The report also prints each model's summary and brief for three fixed articles,
so the numbers can be checked against what the prose actually reads like.

### Known imprecision

`_summarize_one` collapses "unparseable JSON" and "valid JSON with a bad image
brief" into one `ValueError`. A JSON failure yields the fallback dict, which
fails brief validation on all four image fields; a genuine brief problem
usually fails a subset. The harness reports the field-level breakdown and
treats all-four-missing as the JSON-failure signature.

This is a heuristic. Distinguishing the two exactly requires a runtime seam,
which this work excludes. The report must label the figure as inferred.

## Candidate models

Baseline: `meta/llama-3.1-8b-instruct`.

Candidates, all confirmed present in the account's catalog:
`nvidia/nemotron-3-super-120b-a12b`, `poolside/laguna-xs-2.1`,
`mistralai/mistral-medium-3.5-128b`, `google/gemma-4-31b-it`.

Excluded on evidence already gathered: any `-reasoning` model, which exceeds the
512-token budget by construction; `z-ai/glm-5.2` and
`meta/llama-3.3-70b-instruct`, both of which timed out under direct probing.

## Error handling

- A per-article exception is recorded and the run continues. A model that fails
  every article produces a zero row, not a crash.
- A model that returns 404 or another API-level error is marked unavailable and
  skipped, with the reason shown in the report.
- A missing `NVIDIA_API_KEY` fails immediately, matching the existing message
  style in `_NvidiaChatModel`.
- A per-call timeout is taken from `llm.timeout`, which the `llm` block does not
  currently set, so the effective value is the 60-second default in
  `_NvidiaChatModel`. A timeout is recorded as a failure, not an abort.
- A fixture whose body hash does not match the manifest aborts the run before
  any model call.
- `--limit` and `--rpm` flags bound a session: 25 articles across 5 models at
  8 requests per minute is roughly 20 minutes. The free tier means the cost is
  time, not money.

## Testing

Pure logic gets pytest coverage that runs in CI with no network access:

- Aggregation arithmetic over synthetic per-article records.
- Report formatting, including the zero-row and model-unavailable cases.
- The all-four-fields JSON-failure classifier, including a subset-failure case
  that must not be classified as a JSON failure.
- Fixture and manifest hash verification, including the mismatch abort.

The network path is opt-in and never runs in CI. Existing suites
(`uv run pytest`, `uv run ruff check .`) must stay green.

## Decision criteria

Fixed before results are seen, so a favoured model cannot be rationalised
afterwards:

1. **Must:** brief validity rate at least equal to baseline, and zero
   token-cap hits.
2. **Then:** highest first-attempt rubric pass rate.
3. **Guardrail:** p95 latency within the digest's runtime budget.
4. **Tie-break:** the sample output read.

A candidate that fails criterion 1 is rejected regardless of how well it reads.

## Risks

- **Patching a private function.** `_summarize_one`'s internals may be
  reorganised, breaking the harness. Mitigated by the harness failing loudly
  rather than silently measuring the wrong thing; the fix is the optional
  `body` seam.
- **Fixture staleness.** Bodies are local-only, so a fresh clone must
  re-capture, and results may not reproduce exactly across machines or time.
  The manifest makes the divergence visible.
- **Rubric is a proxy.** It checks length, vague phrases, and thin openers; a
  model could pass it while writing poor briefings. Mitigated by including
  sample outputs for human review.
- **Small corpus.** 25 articles gives coarse rates. Differences under roughly
  10 percentage points should not be treated as decisive.
