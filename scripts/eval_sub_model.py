"""Measure sub_model performance on frozen article fixtures.

Opt-in: this script makes real model calls and is never run by CI.

    python -m scripts.eval_sub_model --capture
    python -m scripts.eval_sub_model --run
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx
import yaml

from scripts.eval_report import render_report
from scripts.eval_scoring import (
    ArticleResult,
    ModelAggregate,
    aggregate,
    failure_result,
    success_result,
    unavailable,
)
from scripts.eval_store import load_fixtures, save_fixtures

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "scripts" / "eval_fixtures"
ARCHIVE_BASE = "https://harshagarwal06.github.io/buddy_agent/"
DEFAULT_CORPUS = 25

BASELINE_MODEL = "meta/llama-3.1-8b-instruct"
CANDIDATE_MODELS = [
    BASELINE_MODEL,
    "nvidia/nemotron-3-super-120b-a12b",
    "poolside/laguna-xs-2.1",
    "mistralai/mistral-medium-3.5-128b",
    "google/gemma-4-31b-it",
]

_BRIEF_ERROR_PREFIX = "summarizer returned an incomplete article image brief:"


def _fetch_json(url: str):
    response = httpx.get(url, timeout=30.0, follow_redirects=True)
    response.raise_for_status()
    return response.json()


def _extract_body(url: str) -> str:
    from news_buddy.extract import extract_body

    return extract_body(url) or ""


def _load_config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def _build_model(config: dict):
    from news_buddy.llm import get_sub_model

    return get_sub_model(config)


def _summarize(sub_llm, item: dict, strict: bool = False):
    from news_buddy.agent import _summarize_one

    enriched, tokens, _body = _summarize_one(sub_llm, item, strict=strict)
    return enriched, tokens


def _parse_brief_errors(message: str) -> list[str]:
    if _BRIEF_ERROR_PREFIX not in message:
        return []
    tail = message.split(_BRIEF_ERROR_PREFIX, 1)[1]
    return [part.strip() for part in tail.split(",") if part.strip()]


def _patch_body_source(articles: list[dict]):
    """Feed frozen bodies to _summarize_one instead of re-extracting over the network."""
    from news_buddy import agent as _agent

    bodies = {article["url"]: article["body"] for article in articles}
    original = _agent._extract.extract_body
    _agent._extract.extract_body = lambda url: bodies.get(url, "")
    return _agent, original


def _score_one(sub_llm, article: dict, rubric, strict: bool) -> ArticleResult:
    start = time.monotonic()
    try:
        enriched, tokens = _summarize(sub_llm, article, strict=strict)
    except Exception as exc:  # noqa: BLE001 - every failure mode is data here
        return failure_result(
            url=article["url"], title=article.get("title", ""),
            brief_errors=_parse_brief_errors(str(exc)),
            error=str(exc)[:200], latency_s=time.monotonic() - start,
        )

    elapsed = time.monotonic() - start
    scored = rubric.score(enriched)
    summary = scored.get("summary", "")
    return success_result(
        url=article["url"], title=article.get("title", ""), summary=summary,
        rubric_passed=bool(scored["rubric"]["passed"]),
        total_tokens=tokens, latency_s=elapsed,
        word_count=len(summary.split()),
    )


def evaluate_model(
    model: str, articles: list[dict], config: dict
) -> tuple[ModelAggregate, list[ArticleResult]]:
    from news_buddy.rubric import RubricMiddleware

    model_config = {**config, "llm": {**config["llm"], "sub_model": model}}
    try:
        sub_llm = _build_model(model_config)
    except Exception as exc:  # noqa: BLE001
        return unavailable(model, str(exc)[:120]), []

    rubric_config = config.get("rubric", {})
    rubric = RubricMiddleware(
        min_length=rubric_config.get("min_summary_length", 60),
        min_words=rubric_config.get("min_summary_words"),
        importance_penalty=rubric_config.get("importance_penalty", 2),
    )

    results = [_score_one(sub_llm, a, rubric, strict=False) for a in articles]

    retry_urls = {r.url for r in results if r.ok and not r.rubric_passed}
    strict_results = [
        _score_one(sub_llm, a, rubric, strict=True)
        for a in articles if a["url"] in retry_urls
    ]

    return aggregate(model, results, strict_results), results


def run(
    models: list[str], fixtures_dir: Path, output: Path, baseline: str,
    limit: int | None = None, rpm: int | None = None,
) -> int:
    import json
    import os

    # Fail fast rather than reporting every model as "unavailable — no key".
    if not os.getenv("NVIDIA_API_KEY", "").strip():
        raise SystemExit(
            "NVIDIA_API_KEY is not set. Create a key at "
            "https://build.nvidia.com/ and add it to .env."
        )

    articles = load_fixtures(fixtures_dir)
    if limit:
        articles = articles[:limit]
    config = _load_config()
    if rpm:
        config = {**config, "llm": {**config["llm"], "requests_per_minute": rpm}}
    captured_at = json.loads(
        (fixtures_dir / "manifest.json").read_text(encoding="utf-8")
    )["captured_at"]

    agent_module, original_extract = _patch_body_source(articles)
    try:
        aggregates, samples = [], {}
        for model in models:
            print(f"Evaluating {model} …", file=sys.stderr)
            agg, results = evaluate_model(model, articles, config)
            aggregates.append(agg)
            samples[model] = results[:3]
    finally:
        agent_module._extract.extract_body = original_extract

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_report(aggregates, samples, captured_at, baseline), encoding="utf-8"
    )
    print(f"Report written to {output}")
    return 0


def capture(base_url: str, limit: int, fixtures_dir: Path) -> int:
    base = base_url.rstrip("/") + "/"
    manifest = _fetch_json(base + "index.json")

    articles: list[dict] = []
    for date in manifest.get("dates", []):
        if len(articles) >= limit:
            break
        for record in _fetch_json(f"{base}{date}.json"):
            if len(articles) >= limit:
                break
            url = record.get("url", "")
            if not url:
                continue
            body = _extract_body(url)
            if not body.strip():
                print(f"  skipped (no body): {url}", file=sys.stderr)
                continue
            articles.append({
                "url": url,
                "title": record.get("title", ""),
                "source": record.get("source", ""),
                "published_at": record.get("published_at", ""),
                "body": body,
            })
            print(f"  captured: {record.get('title', '')[:60]}", file=sys.stderr)

    save_fixtures(fixtures_dir, articles)
    return len(articles)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true", help="Snapshot fixtures from the published archive")
    parser.add_argument("--run", action="store_true", help="Evaluate models against captured fixtures")
    parser.add_argument("--limit", type=int, default=DEFAULT_CORPUS,
                        help="Articles to capture, or to evaluate when used with --run")
    parser.add_argument("--rpm", type=int, default=None,
                        help="Override llm.requests_per_minute for this session")
    parser.add_argument("--archive-base", default=ARCHIVE_BASE)
    parser.add_argument("--models", default=",".join(CANDIDATE_MODELS))
    parser.add_argument("--baseline", default=BASELINE_MODEL)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs" / "evals" / "2026-07-30-sub-model-baseline.md",
    )
    args = parser.parse_args(argv)

    if args.capture:
        count = capture(args.archive_base, args.limit, FIXTURES_DIR)
        print(f"Captured {count} articles to {FIXTURES_DIR}")
        return 0

    if args.run:
        models = [m.strip() for m in args.models.split(",") if m.strip()]
        return run(models, FIXTURES_DIR, args.output, args.baseline,
                   limit=args.limit, rpm=args.rpm)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
