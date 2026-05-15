"""RSS/Atom feed fetching and normalization."""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta, timezone

import feedparser
import httpx

USER_AGENT = "news-buddy/0.1 (+https://github.com/manishbabel/buddy_agent)"


def fetch_feed_items(
    url: str,
    source_name: str,
    lookback_hours: int = 24,
    max_items: int = 10,
    timeout: float = 15.0,
) -> list[dict]:
    resp = httpx.get(
        url,
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    items: list[dict] = []
    for entry in parsed.entries:
        published = _entry_datetime(entry)
        if published is None or published < cutoff:
            continue
        items.append(
            {
                "source": source_name,
                "title": (entry.get("title") or "").strip(),
                "url": (entry.get("link") or "").strip(),
                "published_at": published.isoformat(),
                "rss_summary": _clean_html(entry.get("summary") or ""),
            }
        )
        if len(items) >= max_items:
            break
    return items


def _entry_datetime(entry) -> datetime | None:
    # feedparser exposes time.struct_time in UTC; use calendar.timegm (not
    # mktime, which would interpret it as local time).
    for key in ("published_parsed", "updated_parsed"):
        struct = entry.get(key)
        if struct:
            return datetime.fromtimestamp(calendar.timegm(struct), tz=timezone.utc)
    return None


def _clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()
