"""Measure image contract violations across prompt directive variants.

Opt-in: this script makes real model and image API calls and is never run by
CI. It touches no production state and writes only to scripts/eval_artifacts/.

    python -m scripts.eval_image --brief
    python -m scripts.eval_image --run
    python -m scripts.eval_image --label
    python -m scripts.eval_image --report
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.eval_image_scoring import STRATA

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "scripts" / "eval_fixtures"
ARTIFACTS_DIR = ROOT / "scripts" / "eval_artifacts"
TOPICS_FILE = FIXTURES_DIR / "topics.json"
BRIEFS_FILE = FIXTURES_DIR / "briefs.json"


def load_topics(path: Path = TOPICS_FILE) -> dict[str, str]:
    """Return {url: stratum}, rejecting overlaps and unknown strata."""
    data = json.loads(path.read_text(encoding="utf-8"))
    topics: dict[str, str] = {}
    for stratum, urls in data.items():
        if stratum not in STRATA:
            raise ValueError(f"unknown stratum {stratum!r} in {path}")
        for url in urls:
            if url in topics:
                raise ValueError(f"{url!r} appears in both strata in {path}")
            topics[url] = stratum
    return topics


def cache_briefs(limit: int | None = None) -> int:
    """Generate one brief per article, once, and cache it. Returns brief count."""
    import yaml

    from news_buddy import agent as agent_module
    from news_buddy.agent import _summarize_one
    from news_buddy.llm import get_sub_model
    from scripts.eval_store import load_fixtures

    articles = load_fixtures(FIXTURES_DIR)
    topics = load_topics()
    articles = [a for a in articles if a["url"] in topics]
    if limit:
        articles = articles[:limit]

    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    sub_llm = get_sub_model(config)

    bodies = {a["url"]: a["body"] for a in articles}
    original = agent_module._extract.extract_body
    agent_module._extract.extract_body = lambda url: bodies.get(url, "")
    briefs: dict[str, dict] = {}
    try:
        for article in articles:
            try:
                item, _tokens, _body = _summarize_one(sub_llm, article)
            except Exception as exc:  # noqa: BLE001 - a failed brief is data
                print(f"[warn] brief failed for {article['url']}: {exc}", file=sys.stderr)
                continue
            briefs[article["url"]] = {
                key: item.get(key)
                for key in ("title", "summary", "image_prompt", "image_layout",
                            "image_labels", "image_alt")
            }
            print(f"  brief: {article['title'][:60]}", file=sys.stderr)
    finally:
        agent_module._extract.extract_body = original

    BRIEFS_FILE.write_text(
        json.dumps(briefs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return len(briefs)


def load_briefs() -> dict[str, dict]:
    if not BRIEFS_FILE.exists():
        raise RuntimeError(
            f"{BRIEFS_FILE} is missing. Run: python -m scripts.eval_image --brief"
        )
    return json.loads(BRIEFS_FILE.read_text(encoding="utf-8"))
