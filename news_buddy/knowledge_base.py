"""OKF-formatted knowledge-base files for accepted articles.

Each article is written once as a Markdown file with YAML frontmatter,
following Google Cloud's Open Knowledge Format (okf_version 0.1). This is
the source of truth for what news_buddy/rag.py embeds into Chroma.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

_KB_PATH = Path(__file__).parent.parent / "knowledge_base" / "articles"


def _description(summary: str) -> str:
    first, sep, _rest = summary.partition(". ")
    if sep:
        return first + "."
    return summary


def write_article(
    url: str,
    title: str,
    summary: str,
    tags: list[str],
    source: str,
    published_at: str,
) -> Path:
    """Write an OKF-formatted article file. No-ops if it already exists."""
    _KB_PATH.mkdir(parents=True, exist_ok=True)
    filename = hashlib.sha256(url.encode()).hexdigest()[:16] + ".md"
    path = _KB_PATH / filename
    if path.exists():
        return path

    frontmatter = yaml.safe_dump(
        {
            "type": "Article",
            "title": title,
            "description": _description(summary),
            "resource": url,
            "tags": tags,
            "timestamp": published_at,
            "source": source,
        },
        sort_keys=False,
    )
    path.write_text(
        f"---\n{frontmatter}---\n\n## Summary\n\n{summary}\n", encoding="utf-8"
    )
    return path
