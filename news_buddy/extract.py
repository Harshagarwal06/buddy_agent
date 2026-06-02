"""Full-text article extraction via trafilatura."""

from __future__ import annotations

import trafilatura

MAX_CHARS = 4000


def extract_body(url: str) -> str:
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
        if not text:
            return ""
        return text[:MAX_CHARS]
    except Exception:
        return ""
