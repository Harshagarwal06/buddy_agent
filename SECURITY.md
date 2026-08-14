# Security Policy

## Supported version

Security fixes are made on the latest `main` branch. Older commits and locally
modified deployments are not maintained as separate release lines.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository when it is
available. Please do not include credentials, subscriber data, webhook URLs,
or other secrets in a public issue.

Include the affected component, reproduction steps, impact, and any suggested
mitigation. The maintainer will acknowledge the report, investigate it, and
coordinate a fix before public disclosure when appropriate.

## Deployment boundaries

- Secrets belong in `.env` locally or GitHub Actions secrets in production.
- `state.db`, `chroma_db/`, and `knowledge_base/` are runtime data and must not
  be committed or served publicly.
- The public MCP server is read-only and consumes only the published JSON
  archive.
- The optional RAG integration uses Chroma's in-process `PersistentClient`.
  Do not expose a Chroma HTTP server from this environment. ChromaDB 1.5.9 has
  an unfixed pre-authentication server vulnerability in an API path News Buddy
  does not use: https://osv.dev/vulnerability/PYSEC-2026-311.
