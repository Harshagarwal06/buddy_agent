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

from scripts.eval_image_scoring import (
    STRATA,
    VARIANTS,
    ImageResult,
    aggregate,
    judge_agreement,
    label_key,
)

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


def write_label_template(results, sample_size: int = 20) -> Path:
    """Emit an empty labels file for hand calibration.

    Samples round-robin across variants so every arm of the experiment is
    represented. Sorting by label_key alone would order by the variant name
    prefix and hand back a sample drawn from only the first variant or two,
    leaving the rest of the experiment's judge accuracy unmeasured.
    """
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    judged = [r for r in results if r.ok]

    groups: dict[str, list] = {}
    for result in sorted(judged, key=lambda r: label_key(r.variant, r.article_url)):
        groups.setdefault(result.variant, []).append(result)

    sample = []
    depth = 0
    while len(sample) < sample_size and any(len(g) > depth for g in groups.values()):
        for variant in sorted(groups):
            if len(sample) >= sample_size:
                break
            if len(groups[variant]) > depth:
                sample.append(groups[variant][depth])
        depth += 1

    template = {
        label_key(r.variant, r.article_url): {"has_text": None, "has_person": None}
        for r in sample
    }
    path = ARTIFACTS_DIR / "labels.json"
    path.write_text(json.dumps(template, indent=2), encoding="utf-8")
    return path


def load_labels() -> dict[str, dict]:
    """Read hand labels, ignoring entries still left as null."""
    path = ARTIFACTS_DIR / "labels.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        key: value
        for key, value in raw.items()
        if isinstance(value.get("has_text"), bool)
        and isinstance(value.get("has_person"), bool)
    }


def load_results() -> list:
    path = ARTIFACTS_DIR / "results.json"
    if not path.exists():
        raise RuntimeError(
            f"{path} is missing. Run: python -m scripts.eval_image --run"
        )
    return [ImageResult(**row) for row in json.loads(path.read_text(encoding="utf-8"))]


def build_report(output: Path) -> Path:
    from datetime import datetime, timezone

    from scripts.eval_image_report import render_report

    results = load_results()
    aggregates = [
        aggregate(variant, [r for r in results if r.variant == variant])
        for variant in VARIANTS
    ]
    agreement = judge_agreement(results, load_labels())
    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_report(aggregates, agreement, captured_at), encoding="utf-8"
    )
    return output


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", action="store_true",
                        help="Generate and cache one brief per article")
    parser.add_argument("--run", action="store_true",
                        help="Render every variant and judge the raw images")
    parser.add_argument("--label", action="store_true",
                        help="Emit a labels template for judge calibration")
    parser.add_argument("--report", action="store_true",
                        help="Aggregate results and write the markdown report")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--judge-model", default=None)
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "docs" / "evals" / "2026-08-15-image-directive.md",
    )
    args = parser.parse_args(argv)

    if args.brief or args.run:
        if not os.getenv("NVIDIA_API_KEY", "").strip():
            raise SystemExit(
                "NVIDIA_API_KEY is not set. Create a key at "
                "https://build.nvidia.com/ and add it to .env."
            )
    if args.run and not os.getenv("GOOGLE_API_KEY", "").strip():
        raise SystemExit("GOOGLE_API_KEY is not set; the image judge requires it.")

    if args.brief:
        print(f"Cached {cache_briefs(args.limit)} briefs to {BRIEFS_FILE}")
        return 0

    if args.run:
        from news_buddy.image_generator import _NvidiaImageClient
        from scripts.eval_image_judge import DEFAULT_JUDGE_MODEL, ImageJudge

        token = os.getenv("NVIDIA_API_KEY", "").strip()
        judge = ImageJudge(model=args.judge_model or DEFAULT_JUDGE_MODEL)
        results = run_variants(
            judge, lambda settings: _NvidiaImageClient(settings, token), args.limit
        )
        print(f"Rendered and judged {len(results)} images into {ARTIFACTS_DIR}")
        return 0

    if args.label:
        path = write_label_template(load_results())
        print(f"Label template written to {path}. Fill in each true/false, "
              f"then run --report.")
        return 0

    if args.report:
        print(f"Report written to {build_report(args.output)}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
