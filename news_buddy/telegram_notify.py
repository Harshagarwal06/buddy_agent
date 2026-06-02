"""Send the news digest and error alerts to Telegram."""

from __future__ import annotations

import re
import httpx

API = "https://api.telegram.org/bot{token}/{method}"
MAX_CHARS = 4096


def _md_to_html(text: str) -> str:
    """Convert the digest Markdown to Telegram-safe HTML."""
    lines = []
    for line in text.splitlines():
        # ### [Title](url) → <b><a href="url">Title</a></b>
        line = re.sub(
            r"^### \[(.+?)\]\((.+?)\)$",
            r'<b><a href="\2">\1</a></b>',
            line,
        )
        # ## Section → <b>Section</b>
        line = re.sub(r"^## (.+)$", r"<b>\1</b>", line)
        # # Title → <b><u>Title</u></b>
        line = re.sub(r"^# (.+)$", r"<b><u>\1</u></b>", line)
        # *italic* → <i>italic</i>
        line = re.sub(r"\*(.+?)\*", r"<i>\1</i>", line)
        lines.append(line)
    return "\n".join(lines)


def _chunk(text: str, max_len: int = MAX_CHARS) -> list[str]:
    """Split text into chunks that fit within Telegram's message limit."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # split at last newline before the limit
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


def _post(token: str, method: str, **kwargs) -> bool:
    url = API.format(token=token, method=method)
    try:
        resp = httpx.post(url, json=kwargs, timeout=10)
        data = resp.json()
        if not data.get("ok"):
            print(f"[telegram] API error: {data.get('description')}")
            return False
        return True
    except Exception as e:
        print(f"[telegram] Request failed: {e}")
        return False


def send_digest(
    token: str,
    chat_id: str,
    digest_markdown: str,
    date_str: str,
    item_count: int,
) -> bool:
    """Send the full digest to Telegram, chunked if needed."""
    html = _md_to_html(digest_markdown)
    chunks = _chunk(html)

    # Prepend a header to the first chunk
    header = f"🗞️ <b>News Buddy — {date_str}</b>\n{item_count} articles summarised\n\n"
    chunks[0] = header + chunks[0]

    # Add page indicator if multi-chunk
    total = len(chunks)
    ok = True
    for i, chunk in enumerate(chunks, 1):
        if total > 1:
            chunk += f"\n\n<i>Part {i} of {total}</i>"
        ok = _post(token, "sendMessage",
                   chat_id=chat_id,
                   text=chunk,
                   parse_mode="HTML",
                   disable_web_page_preview=True) and ok
    return ok


def send_error_alert(token: str, chat_id: str, error: str, date_str: str) -> bool:
    """Send a failure notification to Telegram."""
    msg = (
        f"❌ <b>News Buddy failed — {date_str}</b>\n\n"
        f"<code>{error[:800]}</code>\n\n"
        f"Check Ollama is running: <code>ollama serve</code>"
    )
    return _post(token, "sendMessage",
                 chat_id=chat_id,
                 text=msg,
                 parse_mode="HTML")
