"""LangChain tools wrapping feeds, state, extract, and file I/O."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import yaml
from langchain_core.tools import tool

from news_buddy import feeds as _feeds
from news_buddy import extract as _extract
from news_buddy import state as _state

_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
_config: dict | None = None


def _cfg() -> dict:
    global _config
    if _config is None:
        with open(_CONFIG_PATH) as f:
            _config = yaml.safe_load(f)
    return _config


def _db_path() -> Path:
    return Path(__file__).parent.parent / "state.db"


@tool
def list_feeds() -> str:
    """Return the configured RSS feeds as a JSON list of {name, url} objects."""
    cfg = _cfg()
    return json.dumps(cfg["feeds"])


@tool
def fetch_feed(name: str) -> str:
    """Fetch recent articles from the named RSS feed. Returns JSON list of article dicts."""
    cfg = _cfg()
    feed_entry = next((f for f in cfg["feeds"] if f["name"] == name), None)
    if feed_entry is None:
        return json.dumps({"error": f"Feed '{name}' not found in config."})
    items = _feeds.fetch_feed_items(
        url=feed_entry["url"],
        source_name=name,
        lookback_hours=cfg.get("lookback_hours", 24),
        max_items=cfg.get("max_items_per_feed", 10),
    )
    return json.dumps(items)


@tool
def extract_article(url: str) -> str:
    """Extract the full body text of an article URL. Returns plain text, empty string on failure."""
    return _extract.extract_body(url)


@tool
def filter_unseen(items_json: str) -> str:
    """
    Filter a JSON list of article dicts to only those not seen in previous runs.
    Input must be a JSON-encoded list. Returns JSON list of unseen items.
    """
    items = json.loads(items_json)
    unseen = _state.filter_unseen(_db_path(), items)
    return json.dumps(unseen)


@tool
def mark_seen(url: str, source: str, title: str) -> str:
    """Record a URL as seen so it is excluded from future runs."""
    _state.mark_seen(_db_path(), {"url": url, "source": source, "title": title})
    return "ok"


@tool
def save_digest(markdown: str) -> str:
    """
    Write the finished Markdown digest to ~/news/YYYY-MM-DD.md.
    Returns the absolute path of the written file.
    """
    cfg = _cfg()
    output_dir = Path(cfg.get("output_dir", "~/news")).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / f"{date.today().isoformat()}.md"
    # Atomic-ish write via temp file
    tmp = filename.with_suffix(".tmp")
    tmp.write_text(markdown, encoding="utf-8")
    tmp.replace(filename)
    return str(filename)
