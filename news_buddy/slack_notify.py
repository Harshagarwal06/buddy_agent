"""Send the news digest and error alerts to Slack via Incoming Webhook."""

from __future__ import annotations

import re
import httpx

MAX_BLOCKS = 50  # Slack hard limit per message


def _md_to_mrkdwn(text: str) -> str:
    """Convert digest Markdown to Slack mrkdwn."""
    lines = []
    for line in text.splitlines():
        # ### [Title](url) → *<url|Title>*
        line = re.sub(
            r"^### \[(.+?)\]\((.+?)\)$",
            r"*<\2|\1>*",
            line,
        )
        # ## Section → *Section*
        line = re.sub(r"^## (.+)$", r"*\1*", line)
        # # Title → *Title*
        line = re.sub(r"^# (.+)$", r"*\1*", line)
        # *italic* → _italic_ (only when not already converted to bold above)
        line = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"_\1_", line)
        lines.append(line)
    return "\n".join(lines)


def _post(webhook_url: str, payload: dict) -> bool:
    try:
        resp = httpx.post(webhook_url, json=payload, timeout=10)
        if resp.status_code != 200:
            print(f"[slack] HTTP {resp.status_code}: {resp.text[:200]}")
            return False
        return True
    except Exception as e:
        print(f"[slack] Request failed: {e}")
        return False


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text[:3000]}}


def _divider() -> dict:
    return {"type": "divider"}


def send_digest(
    webhook_url: str,
    digest_markdown: str,
    date_str: str,
    item_count: int,
    duration_secs: float = 0.0,
    total_tokens: int = 0,
    est_cost_usd: float = 0.0,
) -> bool:
    """Send the full digest to Slack as Block Kit blocks, batched if needed."""
    mins, secs = divmod(int(duration_secs), 60)
    duration_str = f"{mins}m {secs}s" if mins else f"{secs}s"

    header_blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🗞️ News Buddy — {date_str}"},
        },
        _section(
            f"📰 *{item_count} articles*  •  ⏱ {duration_str}"
            f"  •  🪙 {total_tokens:,} tokens  •  💰 ${est_cost_usd:.4f}"
        ),
        _divider(),
    ]

    # Convert markdown and split into per-article section blocks
    body_mrkdwn = _md_to_mrkdwn(digest_markdown)
    body_blocks: list[dict] = []
    for para in body_mrkdwn.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        body_blocks.append(_section(para))
        body_blocks.append(_divider())

    # Batch into messages of ≤ MAX_BLOCKS each
    all_blocks = header_blocks + body_blocks
    batches: list[list[dict]] = []
    for i in range(0, len(all_blocks), MAX_BLOCKS):
        batches.append(all_blocks[i : i + MAX_BLOCKS])

    ok = True
    for i, batch in enumerate(batches, 1):
        if len(batches) > 1:
            batch.append(_section(f"_Part {i} of {len(batches)}_"))
        ok = _post(webhook_url, {"blocks": batch}) and ok
    return ok


def send_error_alert(webhook_url: str, error: str, date_str: str) -> bool:
    """Send a failure notification to Slack."""
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"❌ News Buddy failed — {date_str}"},
        },
        _section(f"```{error[:800]}```"),
        _section("Check that `GOOGLE_API_KEY` is set and feeds are reachable."),
    ]
    return _post(webhook_url, {"blocks": blocks})
