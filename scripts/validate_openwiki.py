#!/usr/bin/env python3
"""Validate the reviewed OpenWiki knowledge layer without third-party packages."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
WIKI = ROOT / "openwiki"

REQUIRED_PAGES = {
    "index.md",
    "quickstart.md",
    "architecture/langgraph-pipeline.md",
    "processing/feed-and-article.md",
    "llm-and-models.md",
    "image-generation.md",
    "archive-and-deployment.md",
    "persistence.md",
    "notifications-and-operations.md",
    "testing-and-gaps.md",
    "INSTRUCTIONS.md",
    "log.md",
}

CONCEPT_PAGES = REQUIRED_PAGES - {"index.md", "INSTRUCTIONS.md"}
LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")

# These identifiers appeared in an inaccurate initial generation. None exists
# in the current implementation, so their return is a useful review tripwire.
KNOWN_HALLUCINATIONS = {
    "asyncio.gather",
    "filter_ai_stories",
    "dedupe_urls",
    "score_and_summarize",
    "seen_urls.db",
    "newspaper3k",
}

REQUIRED_FACTS = {
    "quickstart.md": (
        "Source code,",
        "remain authoritative",
        "production pipeline never reads",
    ),
    "architecture/langgraph-pipeline.md": (
        "ThreadPoolExecutor",
        "A test run still",
        "are not graph nodes",
    ),
    "processing/feed-and-article.md": (
        "does not call a model",
        "state.db",
        "ICYMI is disabled for force, test, and dry runs",
    ),
    "llm-and-models.md": (
        "active graph calls only",
        "no graph node calls it",
        "pure-Python",
    ),
    "persistence.md": (
        "three persistence/search mechanisms",
        "NEWS_BUDDY_RAG_ENABLED=false",
        "separate FastMCP application",
    ),
    "notifications-and-operations.md": (
        "Test and dry runs suppress all channels",
        "preflight publish check",
        "never invokes `python -m news_buddy`",
    ),
}


def _frontmatter_has_type(text: str) -> bool:
    if not text.startswith("---\n"):
        return False
    try:
        frontmatter = text.split("---\n", 2)[1]
    except IndexError:
        return False
    return bool(re.search(r"(?m)^type:\s*\S+", frontmatter))


def _resolve_link(page: Path, raw_target: str) -> Path | None:
    target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
    if not target or target.startswith(("#", "http://", "https://", "mailto:")):
        return None
    target = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not target:
        return None
    if target.startswith("/"):
        return ROOT / target.lstrip("/")
    return page.parent / target


def main() -> int:
    errors: list[str] = []

    found = {
        path.relative_to(WIKI).as_posix()
        for path in WIKI.rglob("*.md")
        if path.is_file()
    }
    for missing in sorted(REQUIRED_PAGES - found):
        errors.append(f"missing required page: openwiki/{missing}")

    index = WIKI / "index.md"
    if index.exists() and 'okf_version: "0.1"' not in index.read_text(encoding="utf-8"):
        errors.append("openwiki/index.md is missing okf_version 0.1")

    repository_contracts = {
        ROOT / "AGENTS.md": (
            "## Documentation Contract",
            "Source code, configuration, tests, and workflows are authoritative",
            "maintained knowledge cache",
        ),
        ROOT / "CLAUDE.md": (
            "Follow `AGENTS.md`",
            "source code, configuration, tests, and workflows remain",
            "authoritative if documentation and implementation disagree",
        ),
    }
    for contract_path, required_fragments in repository_contracts.items():
        contract_text = contract_path.read_text(encoding="utf-8")
        for fragment in required_fragments:
            if fragment not in contract_text:
                errors.append(
                    f"{contract_path.relative_to(ROOT)} is missing documentation "
                    f"contract fragment: {fragment!r}"
                )

    all_text: list[str] = []
    for relative in sorted(found):
        page = WIKI / relative
        text = page.read_text(encoding="utf-8")
        all_text.append(text)

        if relative in CONCEPT_PAGES and not _frontmatter_has_type(text):
            errors.append(f"openwiki/{relative} is missing typed frontmatter")

        for raw_target in LINK_PATTERN.findall(text):
            resolved = _resolve_link(page, raw_target)
            if resolved is not None and not resolved.exists():
                errors.append(
                    f"openwiki/{relative} has broken link {raw_target!r} "
                    f"(resolved to {resolved})"
                )

        for fact in REQUIRED_FACTS.get(relative, ()):
            if fact not in text:
                errors.append(f"openwiki/{relative} is missing required fact: {fact!r}")

    corpus = "\n".join(all_text)
    for phrase in sorted(KNOWN_HALLUCINATIONS):
        if phrase in corpus:
            errors.append(f"known generated hallucination returned: {phrase!r}")

    if errors:
        print("OpenWiki validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"OpenWiki validation passed: {len(found)} Markdown pages checked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
