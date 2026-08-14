# Contributing

Thanks for helping improve News Buddy.

## Development setup

```bash
git clone https://github.com/Harshagarwal06/buddy_agent.git
cd buddy_agent
uv sync --frozen --dev
uv run ruff check .
uv run pytest -q
```

The MCP server has an independent environment and test suite:

```bash
uv --directory news_buddy_mcp sync --frozen --dev
uv --directory news_buddy_mcp run ruff check .
uv --directory news_buddy_mcp run pytest -q
```

## Pull requests

- Keep changes focused and add regression tests for behavior changes.
- Update `README.md` and source-derived documentation when behavior,
  configuration, providers, or deployment changes.
- Use `python -m news_buddy run --dry-run --verbose` for side-effect-free checks.
- Use `python -m news_buddy run --test-run --verbose` for safe live validation.
- Never use a normal production run merely to test notifications.

Report security issues according to `SECURITY.md`, not in a public issue.
