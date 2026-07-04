# Buttondown Email Digest — Design

**Date:** 2026-07-04
**Status:** Approved (design), pending implementation plan

## Goal

Email the daily news digest to a real subscriber list every day at 6:00 AM IST,
with signup happening on the existing GitHub Pages website. Buttondown handles
the subscriber list, double opt-in, unsubscribe links, and delivery.

## Context

The pipeline already runs daily in GitHub Actions
(`.github/workflows/daily-digest.yml`): it curates the digest, writes
`~/news/YYYY-MM-DD.html`, deploys it to the `gh-pages` branch, and sends
Slack/Telegram notifications. This design adds one more notification channel
(email via Buttondown) and a signup form on the archive page. No new backend,
no custom subscriber database.

Gmail (MCP or API) was considered and rejected: bulk sending from a personal
Gmail account hurts deliverability, has daily send limits, and lacks the
unsubscribe handling required for a genuine subscriber list.

## Components

### 1. `news_buddy/buttondown_notify.py` (new)

Follows the exact pattern of `slack_notify.py` / `telegram_notify.py`:

- `send_digest(api_key: str, digest_markdown: str, date_str: str, item_count: int) -> bool`
  - `POST https://api.buttondown.com/v1/emails` with header
    `Authorization: Token {api_key}`.
  - Body: `{"subject": "🗞️ News Buddy — {date_str}", "body": <digest markdown>, "status": "about_to_send"}`.
    Buttondown renders Markdown natively, so the digest markdown is sent as-is
    (no HTML conversion needed).
  - Returns `True` on HTTP 201, logs and returns `False` otherwise (same
    non-raising error style as `slack_notify._post`).
- No `send_error_alert` — failure alerts stay on Slack/Telegram; subscribers
  should never receive error emails.
- Uses `httpx` (already a dependency), timeout 15s.

### 2. `news_buddy/__main__.py` (edit)

Add a third notification block after Slack, mirroring its structure:

- Read `BUTTONDOWN_API_KEY` from env; skip silently when unset or `--dry-run`.
- Only send on success (`result["error"]` falsy) — never email subscribers
  about failures.
- Include Buttondown send status in the terminal summary line alongside
  Telegram/Slack.

### 3. `news_buddy/archive_writer.py` (edit)

Embed Buttondown's hosted signup form in the archive `index.html`, above the
footer: a small `<form action="https://buttondown.com/api/emails/embed-subscribe/{username}">`
snippet with an email input and subscribe button, styled to match the existing
page (including dark mode). The Buttondown username comes from a module-level
constant set during setup.

### 4. `.github/workflows/daily-digest.yml` (edit)

- Change cron from `"30 2 * * *"` to `"30 0 * * *"` (00:30 UTC = 06:00 IST)
  and update the comment. GitHub cron can lag 5–15 minutes; acceptable.
- Pass `BUTTONDOWN_API_KEY: ${{ secrets.BUTTONDOWN_API_KEY }}` to the
  "Run the daily curation job" step.

### 5. Manual setup (documented, not code)

- Create a Buttondown account, note the username, generate an API key.
- Add `BUTTONDOWN_API_KEY` as a GitHub Actions repository secret.
- Free tier covers up to 100 subscribers; $9/month beyond that.

## Data flow

```
06:00 IST cron → run_pipeline() → digest markdown
    → save to ~/news/ → deploy HTML to gh-pages (website, with signup form)
    → slack/telegram notify (existing)
    → buttondown_notify.send_digest() → Buttondown → all subscribers
```

Subscriber flow: visitor on the archive page → Buttondown embed form →
Buttondown confirmation email (double opt-in) → subscribed. Unsubscribe links
are appended by Buttondown automatically.

## Error handling

- Buttondown API failure: log to stdout, return `False`, do not fail the run —
  same policy as Slack/Telegram (the digest and website still publish).
- Missing/empty `BUTTONDOWN_API_KEY`: channel is skipped silently, reported as
  "not configured" in the terminal summary.

## Testing

- Unit test `buttondown_notify.send_digest` with a mocked `httpx.post`
  (success 201, failure 4xx/5xx, network exception).
- Manual verification: `workflow_dispatch` a run with the secret set and a
  single test subscriber (your own address); confirm the email arrives and the
  markdown renders correctly.
- Confirm signup form renders on the deployed archive page in light and dark
  mode and successfully subscribes a test address.

## Out of scope (YAGNI)

- Gmail MCP / Gmail API sending.
- Custom subscriber storage or signup backend.
- Per-subscriber personalization, digest previews, or send-time zones.
- RSS-to-email automation (rejected alternative: needs feed generation anyway
  and gives up control over timing/formatting).
