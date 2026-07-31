"""Frozen article fixtures for sub_model evaluation.

Bodies are third-party article text and are never committed. `articles.json`
is gitignored; `manifest.json` records a SHA-256 per body so a re-capture can
be checked against the original.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

ARTICLES_FILE = "articles.json"
MANIFEST_FILE = "manifest.json"

_FIELDS = ("url", "title", "source", "published_at", "body")


class Article(TypedDict):
    """Structured article data for fixture storage."""

    url: str
    title: str
    source: str
    published_at: str
    body: str


class FixtureError(RuntimeError):
    """Raised when fixtures are missing or disagree with the manifest."""


def body_sha256(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def save_fixtures(directory: Path, articles: list[Article]) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    rows = [{field: article.get(field, "") for field in _FIELDS} for article in articles]

    manifest = {
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "articles": [
            {
                "url": row["url"],
                "title": row["title"],
                "source": row["source"],
                "published_at": row["published_at"],
                "body_sha256": body_sha256(row["body"]),
            }
            for row in rows
        ],
    }

    articles_path = directory / ARTICLES_FILE
    manifest_path = directory / MANIFEST_FILE
    articles_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return articles_path, manifest_path


def load_fixtures(directory: Path) -> list[Article]:
    articles_path = directory / ARTICLES_FILE
    manifest_path = directory / MANIFEST_FILE

    if not manifest_path.exists():
        raise FixtureError(f"{manifest_path} is missing; it should be committed.")
    if not articles_path.exists():
        raise FixtureError(
            f"{articles_path} is missing. Article bodies are not committed — "
            "regenerate them with: python -m scripts.eval_sub_model --capture"
        )

    rows = json.loads(articles_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {entry["url"]: entry["body_sha256"] for entry in manifest["articles"]}

    for row in rows:
        url = row.get("url", "")
        if url not in expected:
            raise FixtureError(f"fixture {url!r} is not in the manifest; re-capture.")
        actual = body_sha256(row.get("body", ""))
        if actual != expected[url]:
            raise FixtureError(
                f"fixture body for {url!r} does not match the manifest "
                f"(expected {expected[url][:12]}, got {actual[:12]}); re-capture."
            )
    return rows
