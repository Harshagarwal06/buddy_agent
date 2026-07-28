"""Builds the public search index published alongside the HTML archive."""

from __future__ import annotations

import json
import re
from pathlib import Path

_DATE_JSON_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")


def _to_record(item: dict) -> dict:
    return {
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "source": item.get("source", ""),
        "published_at": (item.get("published_at") or "")[:10],
        "summary": item.get("summary", ""),
        "tags": item.get("tags") or [],
        "importance": item.get("importance", 3),
        "image_url": item.get("image_url", ""),
        "image_alt": item.get("image_alt", ""),
    }


def write_index(output_dir: Path, date_str: str, enriched_items: list[dict]) -> Path:
    """Write output_dir/{date_str}.json with one record per article. Atomic write."""
    output_dir.mkdir(parents=True, exist_ok=True)
    records = [_to_record(item) for item in enriched_items]
    target = output_dir / f"{date_str}.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)
    return target


def write_manifest(output_dir: Path) -> Path:
    """Scan output_dir for YYYY-MM-DD.json files and write index.json (newest first)."""
    dated_files = sorted(
        (p.stem for p in output_dir.glob("*.json") if _DATE_JSON_PATTERN.match(p.name)),
        reverse=True,
    )
    target = output_dir / "index.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps({"dates": dated_files}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)
    return target
