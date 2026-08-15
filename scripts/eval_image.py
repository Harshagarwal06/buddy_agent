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

from scripts.eval_image_scoring import STRATA, VARIANTS, ImageResult

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


POSITIVE_DIRECTIVE = (
    "Warm cream paper background. Flat hand-drawn editorial spot illustration "
    "with thick charcoal outlines and one muted brick-red or ochre accent. "
    "Exactly three inanimate symbolic objects in a clean horizontal row, "
    "linked by bold directional arrows. Every object is a simple mechanical or "
    "geometric form with smooth, blank, unmarked surfaces. Generous empty "
    "space surrounds each object. The image communicates purely through shape "
    "and arrangement."
)


def negated_directive() -> str:
    """Read the live production directive; never a copy."""
    from news_buddy.image_generator import (
        _STYLE_DIRECTIVE_MARKERS,
        _read_marked_section,
    )

    return _read_marked_section(
        ROOT / "prompts" / "image_style.md", _STYLE_DIRECTIVE_MARKERS
    )


def assemble_prompt(article_prompt: str, directive: str, preserve: bool) -> str:
    """Join the article half and the directive.

    preserve=False reproduces production: concatenate, then truncate the whole
    thing, which cuts the directive off the end.
    preserve=True reserves room for the directive and trims the article instead.
    """
    from news_buddy.image_generator import MAX_IMAGE_PROMPT_CHARS

    tail = f"\n\nVisual direction: {directive}"
    if not preserve:
        return (article_prompt + tail)[:MAX_IMAGE_PROMPT_CHARS]
    room = max(0, MAX_IMAGE_PROMPT_CHARS - len(tail))
    return article_prompt[:room] + tail


def variant_prompt(item: dict, variant: str) -> str:
    from news_buddy.image_generator import _visual_prompt

    phrasing, assembly = variant.split("-")
    directive = POSITIVE_DIRECTIVE if phrasing == "positive" else negated_directive()
    return assemble_prompt(
        _visual_prompt(item), directive, preserve=(assembly == "preserved")
    )


def run_variants(judge, client_factory, limit: int | None = None) -> list[ImageResult]:
    """Render every variant for every article and score the raw bytes."""
    import dataclasses

    import yaml

    from news_buddy.image_generator import ImageContentFilteredError, ImageSettings
    from scripts.eval_image_scoring import background_distance, background_is_cream

    topics = load_topics()
    briefs = load_briefs()
    urls = [u for u in briefs if u in topics]
    if limit:
        urls = urls[:limit]

    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    base = ImageSettings.from_config(config["images"])
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    results: list[ImageResult] = []
    for url in urls:
        item = briefs[url]
        for variant in VARIANTS:
            prompt = variant_prompt(item, variant)
            settings = dataclasses.replace(base, style="")
            client = client_factory(settings)
            try:
                raw = client.text_to_image(
                    prompt,
                    model=settings.model,
                    width=settings.width,
                    height=settings.height,
                    negative_prompt=settings.negative_prompt,
                )
            except ImageContentFilteredError as exc:
                results.append(ImageResult(url, topics[url], variant, ok=False,
                                           error=str(exc), content_filtered=True))
                continue
            except Exception as exc:  # noqa: BLE001 - a failed render is data
                results.append(ImageResult(url, topics[url], variant, ok=False,
                                           error=f"{type(exc).__name__}: {exc}"[:160]))
                continue

            stem = f"{variant}__{abs(hash(url)) % 10**8}"
            (ARTIFACTS_DIR / f"{stem}.png").write_bytes(raw)
            verdict = judge.judge(raw)
            results.append(
                ImageResult(
                    article_url=url,
                    stratum=topics[url],
                    variant=variant,
                    ok=True,
                    background_is_cream=background_is_cream(raw),
                    background_distance=background_distance(raw),
                    has_text=verdict.has_text,
                    has_person=verdict.has_person,
                    object_group_count=verdict.object_group_count,
                    judge_error=verdict.error,
                )
            )
            print(f"  {variant}: {url[:50]}", file=sys.stderr)

    (ARTIFACTS_DIR / "results.json").write_text(
        json.dumps([dataclasses.asdict(r) for r in results], indent=2),
        encoding="utf-8",
    )
    return results
