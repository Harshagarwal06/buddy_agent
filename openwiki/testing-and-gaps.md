---
type: Reference
title: Testing, Validation & Known Gaps
description: Safe verification commands, test-suite boundaries, documentation checks, and work that is not implemented yet.
tags: [testing, validation, gaps]
---

# Testing, Validation & Known Gaps

Tests are split between the digest application and the separately packaged MCP
server.

## Validation commands

From the repository root:

```bash
uv sync --frozen --extra dev
uv run pytest
uv run ruff check .
uv run python scripts/validate_openwiki.py
uv run python -m news_buddy run --dry-run --verbose
uv run python -m news_buddy run --test-run --verbose
```

The first dry run is network- and write-free. The test run performs live feed
and model work and writes output files, but does not mutate URL state, write
RAG entries, generate images under the default configuration, deploy, or
notify.

The MCP package is checked from its own directory:

```bash
cd news_buddy_mcp
uv sync --frozen --extra dev
uv run pytest
uv run ruff check .
```

The CI workflow runs the main and MCP checks as separate jobs because they have
separate project metadata and lockfiles.

## Code Brain validation

[`scripts/validate_openwiki.py`](../scripts/validate_openwiki.py) checks that
the required pages exist, concept pages have OpenWiki frontmatter, local
Markdown links resolve, and a small set of known hallucinated implementation
identifiers has not returned. The OpenWiki update workflow runs this validator
before proposing a draft documentation PR.

Human review is still required. A syntactically valid wiki can be factually
wrong, especially around run-mode side effects, provider selection, persistence,
and the separate MCP boundary.

## Known gaps

These behaviors are intentionally described as future work, not current
capabilities:

- Deduplication is URL-based; there is no story-level clustering.
- Chroma is disabled and not persisted in the scheduled workflow.
- Actions-cached `state.db` can be lost when the cache is evicted.
- LangGraph uses an in-memory checkpointer rather than durable resumable state.
- The public MCP search is keyword matching, not semantic/vector search.
- Test coverage is narrower around feed parsing, dedup/backfill, rubric scoring,
  and some archive/notification failure paths than around the core happy path.
- `main_model` is configured but unused by the active graph.

## Change checklist

When architecture, run modes, providers, schedules, persistence, notification
rules, or deployment behavior changes:

1. change code/config/tests first;
2. update [`openwiki/INSTRUCTIONS.md`](INSTRUCTIONS.md) when generation guidance
   needs to change;
3. regenerate OpenWiki;
4. run the validator and both test suites;
5. review the documentation diff for claims that are not supported by source.

## Related pages

- [Code Brain index](index.md)
- [Notifications and operations](notifications-and-operations.md)
- [Persistence and search](persistence.md)
