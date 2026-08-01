# Repairing an unusable image plan before giving up on the image

Date: 2026-08-01

Follows `2026-08-01-resilient-image-briefs-design.md`, which made a bad image
brief cost an article its image instead of killing the digest. This adds the
retry that doc deferred, so fewer articles go imageless in the first place.

## Why a retry is worth building

`prompts/summarizer.md` has stated the label rules since 2026-07-29 — "each 1-3
words and no more than 18 characters", and the six allowed layouts by name. The
model was told, and produced invalid plans anyway.

That rules out the obvious retry design. Restating the constraint gives the model
nothing it did not already have. The repair call earns its cost only by being
specific: it shows the values that were rejected and names what the validator
objected to in each one.

## Design

### Placement

The repair runs in `summarize_articles_node`, not inside `_summarize_one`.

`scripts/eval_sub_model.py` calls `_summarize_one` directly to score brief
validity. Putting a retry inside it would give every eval run a free second
attempt, and the baseline metric would silently stop measuring single-shot model
capability. `_summarize_one` stays single-shot; the pipeline gets the retry.

### Prompt composition

Field definitions live in `prompts/summarizer.md` and are the single source of
truth. Restating them in a repair prompt would drift the moment either file is
edited, so the four `image_*` bullets are wrapped in `<!-- image-fields:start -->`
/ `<!-- image-fields:end -->` and pulled with the existing `_prompt_section()`
helper — the same mechanism already used for the visual contract in
`image_style.md`. `_prompt_section` raises if a marker goes missing, so drift
fails loudly rather than silently.

`prompts/image_repair.md` holds only the repair framing. Field rules and the
visual contract are composed in from the existing files at call time.

### The call

The payload carries the title, the already-accepted summary, the rejected image
fields verbatim, and a plain-English problem list. `_BRIEF_ERROR_HELP` in
`image_generator.py` maps each validator code to its explanation and sits beside
`_article_brief_errors`, so a new code and its explanation stay together.

The model returns only the four image fields. They are merged over the existing
item, re-validated through the same `_article_brief_errors`, and on success the
article keeps its image. If the repaired plan is still invalid, or the call
throws, the imageless path from the previous design takes over unchanged.

The accepted summary is never regenerated. Now that summaries survive a bad
brief, re-running the full summarizer would risk replacing a good summary with a
worse one and spend output tokens to do it.

### Bounds

One repair attempt per article, gated on `images.brief_retry` (default true),
mirroring `rubric.retry_on_failure`. Independent of the rubric retry, so an
article with both a thin summary and a bad plan can use both — worst case three
model calls for one article. With eight articles and the `requests_per_minute: 8`
throttle that is comfortably inside the 45-minute workflow timeout.

Repair tokens are added to the run total so cost reporting stays accurate.

## Testing

- Repair returns a publishable plan; summary and tags carry through untouched.
- The payload contains the rejected values and a specific explanation per code.
- The system prompt really does contain the rules extracted from
  `summarizer.md`, which fails if the markers are moved or removed.
- A still-invalid repair raises `IncompleteImageBrief` with the remaining errors.
- Unparseable JSON from the repair call is treated as a failed repair.
- Node level: the repair fires and keeps the image; `brief_retry: false` makes no
  second call; a throwing repair still publishes the article imageless.
- Verified by mutation: breaking the merge fails five of these tests.

## Limits

This cannot fix an article the model simply cannot plan an image for — an
abstract or thin source with no concrete mechanism to draw. Those still publish
imageless, which is the correct outcome. The retry targets the case where the
model had the rules, slipped, and can correct itself when told exactly how.
