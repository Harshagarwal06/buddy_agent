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
            headers={
                "Authorization": f"Token {api_key}",
                "X-Buttondown-Live-Dangerously": "true",
            },
            timeout=15,
        )
        if resp.status_code != 201:
            print(f"[buttondown] HTTP {resp.status_code}: {resp.text[:200]}")
            return False
        return True
    except Exception as e:
        print(f"[buttondown] Request failed: {e}")
        return False
