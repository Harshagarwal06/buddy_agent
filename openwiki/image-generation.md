---
type: Architecture
title: Article Image Generation
description: How article-grounded image briefs become cached WebP illustrations or SVG fallbacks, and when image failures block publication.
tags: [images, nvidia, caching, publishing]
---

# Article Image Generation

Image planning and rendering are separate stages. The summarizer first produces
an article-specific brief; the image node later validates and renders it using
[`news_buddy/image_generator.py`](../news_buddy/image_generator.py).

## Input contract

The summarizer must provide `image_prompt`, `image_layout`, exactly three
`image_labels`, and `image_alt`. `_article_brief_errors()` validates that
contract. Supported layouts are `pipeline`, `branching`, `comparison`,
`before_after`, `bottleneck`, and `layers`.

The model-facing visual direction is read from the marked section of
[`prompts/image_style.md`](../prompts/image_style.md). The generator combines
that style with the article brief. For the NVIDIA provider, the negative prompt
is not sent (the model expects only a positive description); for other providers
that support it, the negative prompt is used. News Buddy adds a deterministic
publisher-rendered label band afterward.

## Providers and output

`ImageSettings.from_config()` loads provider, model, dimensions, quality,
timeouts, retry limits, worker count, and failure policy from the `images`
section of [`config.yaml`](../config.yaml).

- The `nvidia` provider uses NVIDIA's hosted Visual GenAI endpoint and
  `NVIDIA_API_KEY`.
- Other configured provider names use
  `huggingface_hub.InferenceClient` and a Hugging Face token.
- Successful provider bytes are decoded, validated with Pillow, fitted to the
  configured canvas, given the label band, and saved as WebP.
- The returned article record receives `image_url`, `image_alt`, dimensions,
  and generation metadata used by the HTML renderer.

## Cache identity

The cache filename is derived from the article URL, prompt, provider/model
settings, and style version. A matching image is reused, so repeated rendering
does not spend image quota when the article and visual contract are unchanged.
Changing `images.style_version` intentionally invalidates old visual choices.

## Failure policy

Provider calls retry according to the image settings. A content-filtered prompt
can be retried with a safer article-shaped concept. When all provider attempts
fail, the generator can create a local SVG placeholder.

The graph distinguishes having a fallback asset from accepting an incomplete
production issue:

- `images.require_article_brief: true` rejects summaries without a valid
  article brief.
- `images.require_all: true` reports image failures to the graph and prevents
  the digest from being published.
- Dry runs never generate images.
- Test runs skip generation unless `images.generate_in_test_run` is explicitly
  enabled.
- When `images.enabled` is false, articles continue without generated images.

The current configuration enables required-article-brief but not require-all
behavior, so normal publication fails only on missing article briefs, not on
image failures.

## Related pages

- [LLM and model providers](llm-and-models.md)
- [Archive and deployment](archive-and-deployment.md)
- [Notifications and operations](notifications-and-operations.md)
