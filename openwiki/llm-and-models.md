---
type: Reference
title: LLM & Model Providers
description: Provider-swappable LLM layer, `sub_model` usage, `main_model` status, rubric scoring, and strict retry.
tags: [llm, providers, summaries, rubric]
---

# LLM & Model Providers

All model construction is centralized in
[`news_buddy/llm.py`](../news_buddy/llm.py). The active graph calls only
`get_sub_model(config)`. `get_main_model()` exists, but no graph node calls it.

## Providers

`llm.provider` in [`config.yaml`](../config.yaml) selects one implementation:

- `nvidia`: a small `httpx` adapter over NVIDIA's OpenAI-compatible
  `/v1/chat/completions` endpoint, authenticated by `NVIDIA_API_KEY`.
- `google`: `ChatGoogleGenerativeAI`, authenticated by `GOOGLE_API_KEY`, with a
  shared in-memory rate limiter and JSON MIME mode for the sub-model.
- `huggingface` / `hf`: a local adapter around
  `huggingface_hub.InferenceClient`, authenticated by `HF_TOKEN` or
  `HUGGINGFACEHUB_API_TOKEN`.
- `ollama`: `ChatOllama` after verifying that the configured local server
  exposes the requested model.

There is no `LLMManager`, `generate_text()`, or model-generated embedding method
in this module. Article embeddings are a separate Google-specific concern in
[`news_buddy/rag.py`](../news_buddy/rag.py).

## Summary and image-plan contract

`_summarize_one()` in
[`news_buddy/agent.py`](../news_buddy/agent.py) reads the summarizer prompt and
the marked planner section of the image style guide. It sends JSON containing
the article title, URL, and a truncated extracted body. The response contract,
defined in [`prompts/summarizer.md`](../prompts/summarizer.md), includes:

- `summary`: a self-contained three-sentence briefing.
- `tags`: one to three values from the allowed editorial taxonomy.
- `importance`: integer 1–5.
- `image_prompt`: three concrete symbols and their article-specific relation.
- `image_layout`: one supported layout name.
- `image_labels`: exactly three short article-specific labels.
- `image_alt`: concise accessible description.

`_article_brief_errors()` validates the image fields before the item is accepted.
The AI filter does not use `sub_model`; it is deterministic keyword/source
logic.

## Retry layers

`_invoke_with_retry()` uses Tenacity for up to three attempts with exponential
backoff. Provider clients may also have their own retry or rate-limiting
behavior.

After a structurally valid response, the pure-Python
[`RubricMiddleware`](../news_buddy/rubric.py) scores specificity,
completeness, context, and tag quality. It does not call an LLM and does not
produce a 0–100 score. A failed rubric can reduce importance and, when
`rubric.retry_on_failure` is true, triggers one extra `_summarize_one(...,
strict=True)` call. The retry replaces the first result only if the new summary
passes.

If the main attempt raises, the worker returns a title/RSS fallback item with
importance 2. That fallback lacks a valid image brief; with production
`images.require_article_brief: true`, the image node rejects it and stops
publication. This is intentional fail-closed behavior.

## Usage accounting

Adapters normalize provider token metadata into input/output counts. The graph
sums those counts for successful initial and strict-retry calls. The CLI prints
a simple blended cost estimate; it is not provider billing reconciliation.

## Related pages

- [Feeds and article selection](processing/feed-and-article.md)
- [Image generation](image-generation.md)
- [Persistence and search](persistence.md)
