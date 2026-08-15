"""Scoring and aggregation for the image directive evaluation. No network."""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

# The cream paper token from prompts/image_style.md and tokens.css.
CREAM_RGB = (243, 236, 216)

# Measured separation on raw generations: white backgrounds land at 36.0-43.5,
# cream backgrounds at 9.4-23.0. 30 splits them with margin on both sides.
BACKGROUND_THRESHOLD = 30.0

_RING_PX = 8


def background_distance(image_bytes: bytes) -> float:
    """Euclidean RGB distance from the border-ring median colour to cream."""
    with Image.open(io.BytesIO(image_bytes)) as opened:
        pixels = np.asarray(opened.convert("RGB")).astype(float)
    ring = np.concatenate(
        [
            pixels[:_RING_PX].reshape(-1, 3),
            pixels[-_RING_PX:].reshape(-1, 3),
            pixels[:, :_RING_PX].reshape(-1, 3),
            pixels[:, -_RING_PX:].reshape(-1, 3),
        ]
    )
    median = np.median(ring, axis=0)
    return float(np.sqrt(((median - np.array(CREAM_RGB, dtype=float)) ** 2).sum()))


def background_is_cream(image_bytes: bytes) -> bool:
    return background_distance(image_bytes) <= BACKGROUND_THRESHOLD


VARIANTS = (
    "negated-truncated",
    "negated-preserved",
    "positive-truncated",
    "positive-preserved",
)
BASELINE_VARIANT = "negated-truncated"
STRATA = ("mechanism", "person")


@dataclass
class ImageResult:
    article_url: str
    stratum: str
    variant: str
    ok: bool
    error: str = ""
    content_filtered: bool = False
    background_is_cream: bool = False
    background_distance: float = 0.0
    has_text: bool | None = None
    has_person: bool | None = None
    object_group_count: int | None = None
    judge_error: str = ""


@dataclass
class VariantAggregate:
    variant: str
    generated: int = 0
    judged: int = 0
    content_filtered: int = 0
    clean_rate: float = 0.0
    text_rate: float = 0.0
    person_rate: float = 0.0
    palette_rate: float = 0.0
    three_group_rate: float = 0.0
    by_stratum: dict[str, "VariantAggregate"] = field(default_factory=dict)


def is_clean(result: ImageResult) -> bool | None:
    """True when publishable, False when violating, None when unknowable.

    None is returned whenever the judge failed. Callers must exclude those
    rather than coercing them, so a broken judge cannot inflate clean_rate.
    """
    if result.has_text is None or result.has_person is None:
        return None
    return (
        not result.has_text
        and not result.has_person
        and result.background_is_cream
    )


def _rate(count: int, total: int) -> float:
    return count / total if total else 0.0


def _aggregate_flat(variant: str, results: list[ImageResult]) -> VariantAggregate:
    generated = [r for r in results if r.ok]
    judged = [r for r in generated if is_clean(r) is not None]
    total = len(judged)
    return VariantAggregate(
        variant=variant,
        generated=len(generated),
        judged=total,
        content_filtered=sum(1 for r in results if r.content_filtered),
        clean_rate=_rate(sum(1 for r in judged if is_clean(r)), total),
        text_rate=_rate(sum(1 for r in judged if r.has_text), total),
        person_rate=_rate(sum(1 for r in judged if r.has_person), total),
        palette_rate=_rate(
            sum(1 for r in judged if not r.background_is_cream), total
        ),
        three_group_rate=_rate(
            sum(1 for r in judged if r.object_group_count == 3), total
        ),
    )


def aggregate(variant: str, results: list[ImageResult]) -> VariantAggregate:
    combined = _aggregate_flat(variant, results)
    combined.by_stratum = {
        stratum: _aggregate_flat(variant, [r for r in results if r.stratum == stratum])
        for stratum in STRATA
        if any(r.stratum == stratum for r in results)
    }
    return combined
