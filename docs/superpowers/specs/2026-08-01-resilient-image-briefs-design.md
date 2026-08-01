# Resilient image briefs: one bad article must not kill the digest

Date: 2026-08-01

## Problem

On 2026-08-01 three consecutive scheduled digests failed. Three articles out of
eight came back with an unusable editorial image brief, and the run aborted with:

```
RuntimeError: article image briefs are incomplete; refusing generic images
```

The immediate trigger (an over-long `image_labels` entry treated as fatal) was
fixed in #10. The mechanism that turned three bad briefs into a total outage was
not.

Three separate all-or-nothing gates sit on the path to publication:

1. `_summarize_one` raises on any brief error, discarding the summary with it.
2. The handler in `summarize_node` then substitutes a fallback item with no
   `image_*` fields at all.
3. `generate_article_images` sees the empty brief and raises for the whole run
   under `images.require_article_brief`; `require_all` raises separately for any
   generation failure.

Because gate 1 destroys the brief that gate 3 demands, a single malformed label
deterministically fails the entire digest.

## Principle

Separate *"is this brief usable?"* — a per-article question — from *"should we
publish at all?"* — a run-level question. Conflating them is the root of the
fragility.

## Design

### 1. Signal without destroying

`_summarize_one` raises a typed `IncompleteImageBrief(ValueError)` carrying both
the error list and the fully parsed item.

The exception's message stays byte-identical to today's
(`"summarizer returned an incomplete article image brief: <errors>"`). This is a
hard constraint, not a nicety: `scripts/eval_sub_model.py` catches the exception
and string-parses that message to score brief validity, which is the headline
metric of the sub-model baseline eval. Changing the wording silently zeroes that
metric.

The handler in `summarize_node` catches `IncompleteImageBrief` specifically,
keeps the model's real summary and tags from `exc.item`, clears the image
fields, and continues. Unrelated exceptions keep their existing RSS-blurb
fallback.

### 2. Per-item gate

Under `images.require_article_brief`, `generate_article_images` no longer raises
when any item has a bad brief. It skips image generation for those items and
leaves `image_url` unset. `html_writer` already renders such articles through
its existing `no-image` class, so no rendering change is needed.

The "never publish a generic or ungrounded image" intent is fully preserved: the
article ships with *no* image rather than a fabricated one.

### 3. Systemic failures still raise

If *every* item has an invalid brief, `generate_article_images` still raises.
That is the real regression signal — a broken prompt or a model change — and it
is exactly the case that occurred today. Partial failures degrade; total failure
alarms.

### 4. Skipped is not failed

`require_all` raises on `failures`, the count of image generations that were
attempted and failed. Articles deliberately skipped for a bad brief must not
increment that counter, or `require_all: true` re-raises and reintroduces the
outage through a different path. Skipped and failed are tracked as distinct
quantities.

## Testing

- Existing gate tests (`test_required_article_brief_rejects_generic_fallback`,
  `test_required_article_brief_rejects_generic_label_triad`) pass a single item,
  so "every item invalid" holds and they keep asserting the strict behavior
  unchanged.
- Mixed batch: one bad brief among three publishes two images and does not raise;
  the bad item carries no `image_url`.
- All-invalid batch still raises.
- `require_all: true` does not raise when the only imageless articles were
  skipped for bad briefs.
- The handler preserves the model's summary and tags when the brief is bad.

## Outcome

Applied to today's failure: three bad briefs out of eight yield five illustrated
articles, three imageless ones, and a digest that ships.

## Explicitly out of scope

Retrying the image brief with a stricter prompt. It would recover most transient
misses, but it costs an extra model call per failure and adds a retry path to
maintain. Worth revisiting if imageless articles become common in practice.
