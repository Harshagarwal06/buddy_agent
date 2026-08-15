# Buttondown Email Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Email the daily digest to a Buttondown subscriber list at 6:00 AM IST, with a signup form on the GitHub Pages archive site.

**Architecture:** A new `buttondown_notify.py` module mirrors the existing `slack_notify.py` pattern (plain function, httpx POST, non-raising error handling). `__main__.py` gains a third notification block gated on a `BUTTONDOWN_API_KEY` env var. `archive_writer.py` embeds Buttondown's hosted signup form when `BUTTONDOWN_USERNAME` is set. The GitHub Actions cron moves to 00:30 UTC (06:00 IST).

**Tech Stack:** Python 3.11, httpx (already a dependency), pytest (run via `uv run --with pytest`, not added to project deps), Buttondown REST API v1, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-07-04-buttondown-email-digest-design.md`

**Working directory:** the repository root

**Test command used throughout:** `uv run --with pytest pytest tests/ -v`

---

### Task 1: `buttondown_notify.py` module (TDD)

**Files:**
- Create: `tests/__init__.py` (empty file)
- Create: `tests/test_buttondown_notify.py`
- Create: `news_buddy/buttondown_notify.py`

- [ ] **Step 1: Write the failing tests**

Create empty `tests/__init__.py`, then create `tests/test_buttondown_notify.py`:

```python
"""Tests for news_buddy.buttondown_notify."""

import httpx

from news_buddy import buttondown_notify


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def test_send_digest_success(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _FakeResponse(201)

    monkeypatch.setattr(httpx, "post", fake_post)

    ok = buttondown_notify.send_digest(
        api_key="secret-key",
        digest_markdown="## Top Stories\n\n- something happened",
        date_str="2026-07-04",
        item_count=7,
    )

    assert ok is True
    assert captured["url"] == "https://api.buttondown.com/v1/emails"
    assert captured["headers"] == {"Authorization": "Token secret-key"}
    assert captured["json"]["subject"] == "🗞️ News Buddy — 2026-07-04 (7 stories)"
    assert captured["json"]["body"] == "## Top Stories\n\n- something happened"
    assert captured["json"]["status"] == "about_to_send"


def test_send_digest_http_error_returns_false(monkeypatch):
    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **kw: _FakeResponse(401, "bad token"),
    )
    ok = buttondown_notify.send_digest("bad", "body", "2026-07-04", 1)
    assert ok is False


def test_send_digest_network_error_returns_false(monkeypatch):
    def fake_post(*a, **kw):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx, "post", fake_post)
    ok = buttondown_notify.send_digest("key", "body", "2026-07-04", 1)
    assert ok is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest pytest tests/ -v`
Expected: FAIL / ERROR with `ImportError: cannot import name 'buttondown_notify'` (or `ModuleNotFoundError`).

- [ ] **Step 3: Write the implementation**

Create `news_buddy/buttondown_notify.py`:

```python
"""Send the news digest to Buttondown subscribers via the Buttondown API.

Buttondown handles the subscriber list, double opt-in, and unsubscribe links.
Buttondown renders Markdown natively, so the digest markdown is sent as-is.
"""

from __future__ import annotations

import httpx

API_URL = "https://api.buttondown.com/v1/emails"


def send_digest(
    api_key: str,
    digest_markdown: str,
    date_str: str,
    item_count: int,
) -> bool:
    """Create and immediately send today's digest as a Buttondown email.

    Returns True on success. Never raises — logs and returns False on any
    failure so the pipeline (and website deploy) still completes.
    """
    payload = {
        "subject": f"🗞️ News Buddy — {date_str} ({item_count} stories)",
        "body": digest_markdown,
        "status": "about_to_send",
    }
    try:
        resp = httpx.post(
            API_URL,
            json=payload,
            headers={"Authorization": f"Token {api_key}"},
            timeout=15,
        )
        if resp.status_code != 201:
            print(f"[buttondown] HTTP {resp.status_code}: {resp.text[:200]}")
            return False
        return True
    except Exception as e:
        print(f"[buttondown] Request failed: {e}")
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest pytest tests/ -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/__init__.py tests/test_buttondown_notify.py news_buddy/buttondown_notify.py
git commit -m "Add Buttondown email notify module"
```

---

### Task 2: Wire Buttondown into the CLI (`__main__.py`)

**Files:**
- Modify: `news_buddy/__main__.py` (Slack block ends at line 63; summary lines at 80-82)

- [ ] **Step 1: Add the Buttondown block after the Slack block**

In `news_buddy/__main__.py`, directly after the Slack notification block (after the line `slack_notify.send_digest(slack_url, result["digest"], date_str, ...)` and before the `# ── Terminal output ──` comment), insert:

```python
    # ── Buttondown email (subscriber list) ───────────────────────────────────
    bd_key = os.getenv("BUTTONDOWN_API_KEY", "").strip()
    use_bd = bool(bd_key) and not args.dry_run
    if use_bd and not result["error"]:
        from news_buddy import buttondown_notify
        buttondown_notify.send_digest(bd_key, result["digest"], date_str,
                                      result["item_count"])
```

Note: unlike Slack/Telegram there is deliberately NO error-alert call here — subscribers never receive failure emails (spec requirement).

- [ ] **Step 2: Add Buttondown to the terminal summary**

Find these lines in the success branch:

```python
        tg_status = "sent ✅" if use_tg else "not configured"
        slack_status = "sent ✅" if use_slack else "not configured"
        print(f"   Telegram: {tg_status}  |  Slack: {slack_status}")
```

Replace with:

```python
        tg_status = "sent ✅" if use_tg else "not configured"
        slack_status = "sent ✅" if use_slack else "not configured"
        bd_status = "sent ✅" if use_bd else "not configured"
        print(f"   Telegram: {tg_status}  |  Slack: {slack_status}  |  Email: {bd_status}")
```

- [ ] **Step 3: Verify the file still parses and tests still pass**

Run: `python3 -c "import ast; ast.parse(open('news_buddy/__main__.py').read()); print('OK')"`
Expected: `OK`

Run: `uv run --with pytest pytest tests/ -v`
Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add news_buddy/__main__.py
git commit -m "Send digest to Buttondown subscribers from CLI pipeline"
```

---

### Task 3: Signup form on the archive page (TDD)

**Files:**
- Create: `tests/test_archive_writer_signup.py`
- Modify: `news_buddy/archive_writer.py`

Background for the implementer: `archive_writer.write_archive(output_dir)` builds `index.html` from one big f-string (`html = f"""..."""`). Because it is an f-string, **all literal CSS/JS braces inside it are doubled (`{{ }}`)**. New CSS added to that f-string must also use doubled braces. The form HTML itself is built in a separate helper function so its braces are normal.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_archive_writer_signup.py`:

```python
"""Tests for the Buttondown signup form embed in the archive page."""

from pathlib import Path

from news_buddy.archive_writer import write_archive


def _make_digest(tmp_path: Path) -> None:
    (tmp_path / "2026-07-04.html").write_text(
        '<html><body>3 articles <span data-tag="ai"></span></body></html>',
        encoding="utf-8",
    )


def test_signup_form_rendered_when_username_set(tmp_path, monkeypatch):
    monkeypatch.setenv("BUTTONDOWN_USERNAME", "newsbuddy")
    _make_digest(tmp_path)

    index = write_archive(tmp_path)
    html = index.read_text(encoding="utf-8")

    assert "https://buttondown.com/api/emails/embed-subscribe/newsbuddy" in html
    assert 'name="email"' in html
    assert "signup-box" in html


def test_signup_form_omitted_when_username_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("BUTTONDOWN_USERNAME", raising=False)
    _make_digest(tmp_path)

    index = write_archive(tmp_path)
    html = index.read_text(encoding="utf-8")

    assert "embed-subscribe" not in html
    assert "signup-box" not in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest pytest tests/test_archive_writer_signup.py -v`
Expected: FAIL on the `assert ... in html` lines (write_archive succeeds but no form is emitted).

- [ ] **Step 3: Implement the signup form**

In `news_buddy/archive_writer.py`:

3a. Add `import os` to the imports block at the top (after `import json`):

```python
import json
import os
import re
```

3b. Add this helper function directly above `def write_archive(...)`:

```python
def _signup_form() -> str:
    """Buttondown signup embed; empty string when BUTTONDOWN_USERNAME is unset."""
    username = os.getenv("BUTTONDOWN_USERNAME", "").strip()
    if not username:
        return ""
    return f"""
  <div class="signup-box">
    <div class="signup-title">&#128231; Get this digest by email</div>
    <div class="signup-sub">One email every morning at 6am IST. Unsubscribe anytime.</div>
    <form class="signup-form"
          action="https://buttondown.com/api/emails/embed-subscribe/{username}"
          method="post" target="_blank">
      <input type="email" name="email" placeholder="you@example.com" required>
      <button type="submit">Subscribe</button>
    </form>
  </div>"""
```

3c. Inside the big `html = f"""..."""` string, add this CSS immediately BEFORE the `.site-footer {{` rule (note the doubled braces — this is inside an f-string):

```css
.signup-box {{
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; box-shadow: var(--shadow);
  padding: 20px 18px; margin-top: 24px; text-align: center;
}}
.signup-title {{ font-weight: 700; font-size: 0.95rem; margin-bottom: 4px; }}
.signup-sub {{ font-size: 0.78rem; color: var(--text-muted); margin-bottom: 12px; }}
.signup-form {{ display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; }}
.signup-form input[type=email] {{
  flex: 1 1 200px; max-width: 300px; padding: 8px 12px;
  border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg); color: var(--text); font-size: 0.85rem;
}}
.signup-form button {{
  background: var(--accent); color: #fff; border: none; border-radius: 8px;
  padding: 8px 18px; font-weight: 600; font-size: 0.85rem; cursor: pointer;
}}
.signup-form button:hover {{ opacity: .9; }}
```

(The form inherits dark mode automatically because it only uses the existing CSS variables `--surface`, `--border`, `--bg`, `--text`, `--text-muted`, `--accent`, which are redefined under `[data-theme="dark"]`.)

3d. In the body of the same f-string, insert `{_signup_form()}` between the day-list line and the footer, so this:

```html
  {'<div class="day-list">' + rows_html + '</div>' if dated_files else empty_msg}

  <div class="site-footer">
```

becomes:

```html
  {'<div class="day-list">' + rows_html + '</div>' if dated_files else empty_msg}
{_signup_form()}
  <div class="site-footer">
```

- [ ] **Step 4: Run the full test suite**

Run: `uv run --with pytest pytest tests/ -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_archive_writer_signup.py news_buddy/archive_writer.py
git commit -m "Embed Buttondown signup form on archive page"
```

---

### Task 4: Workflow — 6am IST cron + secrets

**Files:**
- Modify: `.github/workflows/daily-digest.yml`

- [ ] **Step 1: Move the cron to 06:00 IST**

Replace:

```yaml
  schedule:
    # 08:00 IST == 02:30 UTC (IST is UTC+5:30). GitHub cron uses UTC.
    - cron: "30 2 * * *"
```

with:

```yaml
  schedule:
    # 06:00 IST == 00:30 UTC (IST is UTC+5:30). GitHub cron uses UTC.
    - cron: "30 0 * * *"
```

- [ ] **Step 2: Pass the Buttondown secrets to the pipeline steps**

In the "Run the daily curation job" step, add one line to the `env:` block:

```yaml
          BUTTONDOWN_API_KEY: ${{ secrets.BUTTONDOWN_API_KEY }}
```

The "Deploy digest to GitHub Pages" step runs `python -m news_buddy.archive_writer`, which needs the username. Its existing `env:` block (currently only `DEPLOY_DIR`) becomes:

```yaml
        env:
          DEPLOY_DIR: ${{ runner.temp }}/gh-pages-deploy
          BUTTONDOWN_USERNAME: ${{ secrets.BUTTONDOWN_USERNAME }}
```

- [ ] **Step 3: Validate the YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/daily-digest.yml')); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/daily-digest.yml
git commit -m "Move daily run to 6am IST and pass Buttondown secrets"
```

---

### Task 5: One-time setup instructions

**Files:**
- Create: `docs/buttondown-setup.md`

- [ ] **Step 1: Write the setup doc**

Create `docs/buttondown-setup.md`:

```markdown
# Buttondown one-time setup

The daily email digest requires a Buttondown account (free up to 100
subscribers, $9/month beyond).

1. Create an account at https://buttondown.com and pick a username
   (e.g. `newsbuddy`). Note it — the signup form on the archive page
   posts to `https://buttondown.com/api/emails/embed-subscribe/<username>`.
2. In Buttondown: Settings → API → copy your API key.
3. In the GitHub repo (https://github.com/harshagarwal06/buddy_agent):
   Settings → Secrets and variables → Actions → New repository secret.
   Add two secrets:
   - `BUTTONDOWN_API_KEY` — the API key from step 2.
   - `BUTTONDOWN_USERNAME` — the username from step 1.
4. Test: subscribe your own address via the form on the archive page,
   confirm the opt-in email, then trigger the workflow manually
   (Actions tab → Daily News Digest → Run workflow) and confirm the
   digest email arrives and the Markdown renders correctly.

If the secrets are absent, the pipeline skips email silently and the
archive page omits the signup form — nothing breaks.
```

- [ ] **Step 2: Commit**

```bash
git add docs/buttondown-setup.md
git commit -m "Document Buttondown one-time setup"
```

---

## Final verification

- [ ] Run the full suite once more: `uv run --with pytest pytest tests/ -v` → 5 passed.
- [ ] `git log --oneline -5` shows the five task commits.
- [ ] Optional manual check (requires local setup): `BUTTONDOWN_USERNAME=test python3 -m news_buddy.archive_writer /tmp/archive-check` after copying a dated digest HTML there, then open the index.html and confirm the form renders in light and dark mode.
