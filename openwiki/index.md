---
okf_version: "0.1"
title: News Buddy Code Brain
description: Source-grounded knowledge map for the News Buddy digest pipeline, operations, persistence, publishing, and public search service.
---

# News Buddy Code Brain

This directory is a navigable knowledge layer for maintainers and coding
agents. It explains how the repository behaves, but it is not an input to the
production application.

Start with the [quickstart](quickstart.md), then follow the topic pages:

- [LangGraph pipeline and CLI](architecture/langgraph-pipeline.md)
- [Feeds and article selection](processing/feed-and-article.md)
- [LLM and model providers](llm-and-models.md)
- [Image generation](image-generation.md)
- [Archive and deployment](archive-and-deployment.md)
- [Persistence and search](persistence.md)
- [Notifications and operations](notifications-and-operations.md)
- [Testing and known gaps](testing-and-gaps.md)

## Authority and maintenance

When documentation and implementation disagree, use this order:

1. source code, tests, `config.yaml`, and GitHub workflows;
2. [`AGENTS.md`](../AGENTS.md) for repository working rules;
3. [`README.md`](../README.md) for the public project introduction;
4. this generated-and-reviewed Code Brain;
5. historical material under [`docs/superpowers/`](../docs/superpowers/).

OpenWiki updates are proposed as reviewable draft pull requests by
[`openwiki-update.yml`](../.github/workflows/openwiki-update.yml). The workflow
does not run the digest, deploy a site, alter `state.db`, write Chroma data, or
send subscriber notifications.

The generation brief in [INSTRUCTIONS.md](INSTRUCTIONS.md) is intentionally
strict because the implementation contains several easy-to-confuse
boundaries: deterministic filtering versus LLM summarization, local Chroma
versus public JSON search, and graph execution versus post-graph side effects.
