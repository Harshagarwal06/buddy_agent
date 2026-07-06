"""Full-text article extraction via trafilatura."""

from __future__ import annotations

import re

import httpx
import trafilatura
from lxml import html

MAX_CHARS = 4000
MIN_FALLBACK_CHARS = 250
USER_AGENT = "news-buddy/0.1 (+https://github.com/harshagarwal06/buddy_agent)"


def extract_body(url: str) -> str:
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
            if text:
                return text[:MAX_CHARS]
    except Exception:
        pass

    return _fallback_extract(url)


def _fallback_extract(url: str) -> str:
    try:
        resp = httpx.get(
            url,
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        doc = html.fromstring(resp.content)
        for node in doc.xpath("//script|//style|//noscript|//nav|//footer|//aside"):
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)

        text = _paragraph_text(doc.xpath("//article//p | //main//p"))
        if len(text) < MIN_FALLBACK_CHARS:
            text = _paragraph_text(doc.xpath("//p"))
        return text[:MAX_CHARS] if len(text) >= MIN_FALLBACK_CHARS else ""
    except Exception:
        return ""


def _paragraph_text(nodes) -> str:
    parts: list[str] = []
    for node in nodes:
        text = " ".join(node.itertext())
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) >= 40:
            parts.append(text)
    return "\n\n".join(parts)
