# News Buddy OpenWiki Brief

Generate and maintain a codebase wiki for the current News Buddy
implementation. The wiki is for maintainers, contributors, and coding agents.
It must explain how the system actually behaves without presenting historical
plans as shipped functionality.

## Authority and scope

Use these sources as authority, in this order:

1. Runtime code and tests.
2. `config.yaml` and active GitHub Actions workflows.
3. `AGENTS.md` safety and operating rules.
4. `README.md` and `DIAGRAM.md` for human-facing context.
5. Historical files under `docs/superpowers/` only as design history.

Never describe the repository as an active `deepagents` curator. It started as
that experiment, but the current production implementation is a deterministic
LangGraph pipeline.

Cover both Python projects while keeping their deployment boundaries clear:

- `news_buddy/` is the daily digest application.
- `news_buddy_mcp/` is the public archive-search MCP server and is not part of
  the digest graph process.

## Required concepts

Create focused, cross-linked pages for:

- End-to-end LangGraph and CLI execution, including where notifications occur.
- Feed fetching, AI filtering, URL deduplication, widening lookback, and ICYMI.
- Model provider construction and the fact that `sub_model` is active while
  `main_model` is currently unused by the graph.
- Summary JSON, rubric scoring, strict retry, and article image briefs.
- Image generation, caching, required-brief behavior, and fallback rules.
- Markdown, HTML, JSON search records, archive generation, and `gh-pages`
  deployment.
- `state.db`, Chroma RAG, public archive search, and their different
  persistence models.
- Telegram, Slack, and Buttondown routing, including quiet empty/test runs.
- `--dry-run`, `--test-run`, `--force`, and production side-effect boundaries.
- Scheduled primary/backup runs, concurrency, the `gh-pages` preflight guard,
  cache limitations, and safe recovery.
- The main test suite and the separate `news_buddy_mcp` test suite.
- Known gaps and high-value next steps, clearly labeled as not implemented.

Use Mermaid only when it makes a relationship materially easier to understand.
Prefer small diagrams for runtime sequence, state/persistence boundaries, and
deployment topology.

## Accuracy and safety constraints

- Link important claims to the repository files that prove them.
- Do not infer behavior from filenames when the implementation can be read.
- Do not claim that `main_model` participates in the active graph.
- Do not claim that CI persists or grows Chroma; scheduled CI disables RAG.
- Do not imply that a test run deploys, notifies, marks URLs seen, writes RAG
  entries, or normally generates article images.
- Preserve the scheduled backup publish guard. It prevents duplicate sends.
- Keep notifications outside the graph in the documented runtime sequence.
- Treat OpenWiki pages as generated documentation, never as runtime inputs.
- Never include `.env`, credential values, OAuth data, `state.db`,
  `chroma_db/`, generated `~/news` contents, caches, or subscriber data.
- Do not modify production source, configuration, tests, or workflows while
  generating documentation.

## Documentation boundaries

`README.md` remains the public introduction and setup guide. `AGENTS.md`
remains the concise repository-wide rule set. This wiki should provide deeper
progressive disclosure instead of duplicating either file verbatim.

Maintain useful `index.md` navigation and `log.md` update history. When code and
existing documentation conflict, document the code and make the conflict
visible for human review.
