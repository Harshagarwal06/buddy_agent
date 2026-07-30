---
type: Operations
title: Notifications & Safe Operations
description: CLI side effects, dry/test/force run semantics, notification rules, schedules, and failure recovery.
tags: [operations, notifications, safety, github-actions]
---

# Notifications & Safe Operations

The graph returns a result before notification adapters run. This boundary in
[`news_buddy/__main__.py`](../news_buddy/__main__.py) keeps feed/model/output
failures visible to the CLI and lets run modes suppress external messages.

## Run-mode matrix

| Behavior | Normal run | `--test-run` | `--dry-run` | `--force` |
| --- | --- | --- | --- | --- |
| Fetch feeds and call models | yes | yes | no | yes |
| Cross-run URL filtering | yes | no | no | no |
| Write `state.db` / Chroma | yes, when enabled | no | no | yes, when enabled |
| Generate images | yes | off by default | no | yes |
| Write Markdown/HTML/JSON/archive | yes | yes | no | yes |
| Send Telegram/Slack/Buttondown | yes, by result rules | no | no | yes, by result rules |
| Deploy in the scheduled workflow | yes | no | no application output | yes when invoked in a deployable workflow run |

Use `python -m news_buddy run --test-run --verbose` for live end-to-end
verification without dedup/RAG/notification/deployment side effects. It still
writes publication files to the configured output directory. Use
`python -m news_buddy run --dry-run --verbose` when feed/model network calls and
file writes are also undesirable.

## Notification routing

Environment variables enable each adapter:

- Telegram: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`;
- Slack: `SLACK_WEBHOOK_URL`;
- Buttondown: `BUTTONDOWN_API_KEY`.

For a successful non-empty issue, the CLI can send all configured channels.
Telegram and Slack can send an error alert when the graph returns an error.
Buttondown sends only a successful, non-empty digest. Empty successful issues
stay quiet on every channel. Test and dry runs suppress all channels.

`--notify-at-utc HH:MM` delays only the post-graph notification phase until the
next occurrence of that UTC time. It is not a scheduler and does not delay
article processing.

## Scheduled execution

[`daily-digest.yml`](../.github/workflows/daily-digest.yml) uses a primary cron
and later backup crons because GitHub schedules can be delayed or skipped. The
workflow:

1. checks `gh-pages` for today's already-published HTML on scheduled runs;
2. restores cached SQLite/image state;
3. installs locked dependencies;
4. disables CI RAG and runs the CLI;
5. deploys only for a production-eligible run.

The preflight publish check must stay ahead of every scheduled backup. Without
it, a late retry could generate and notify a second issue for the same day.

## Failure handling

- Individual feed failures warn and allow other feeds to continue.
- Model calls retry; invalid or weak summaries follow the rubric/fail-closed
  rules documented in the model page.
- Required image failure prevents publication.
- RAG embedding failure warns and does not block publication.
- Empty issues produce local output but do not notify.
- A failed digest may send configured Telegram/Slack error alerts.

For notification incidents, verify the final GitHub Actions notification status
and adapter logs, not just the local adapter code. Do not use a normal
production run merely to test delivery unless subscriber-facing side effects
are explicitly intended.

## OpenWiki isolation

[`openwiki-update.yml`](../.github/workflows/openwiki-update.yml) is a separate
manual/weekly documentation job. It installs a pinned OpenWiki CLI, regenerates
only documentation, validates the Code Brain, and opens a draft PR for review.
It never invokes `python -m news_buddy`, checks out `gh-pages`, or calls a
notification adapter.

## Related pages

- [LangGraph pipeline and CLI](architecture/langgraph-pipeline.md)
- [Image generation](image-generation.md)
- [Testing and known gaps](testing-and-gaps.md)
