"""Scoring and aggregation for sub_model evaluation. Pure functions, no network."""

from __future__ import annotations

from dataclasses import dataclass, field

# prompts/summarizer.md asks for a 70-110 word briefing.
WORD_TARGET = (70, 110)

# _article_brief_errors emits one entry per missing image field. When JSON
# parsing fails, _summarize_one substitutes a fallback dict with no image
# fields at all, so every one of these appears together.
_JSON_FAILURE_SIGNATURE = frozenset(
    {"image_prompt", "image_layout", "image_labels", "image_alt"}
)


@dataclass
class ArticleResult:
    url: str
    title: str
    ok: bool
    summary: str = ""
    rubric_passed: bool = False
    brief_errors: list[str] = field(default_factory=list)
    json_failure: bool = False
    # _summarize_one returns input + output tokens as one sum; there is no
    # separate output figure, so cap hits cannot be measured. Truncation shows
    # up as a JSON failure instead.
    total_tokens: int = 0
    latency_s: float = 0.0
    word_count: int = 0
    error: str = ""


@dataclass
class ModelAggregate:
    model: str
    available: bool = True
    unavailable_reason: str = ""
    article_count: int = 0
    brief_valid_rate: float = 0.0
    first_pass_rate: float = 0.0
    strict_recovery_rate: float | None = None
    json_failure_count: int = 0
    field_failures: dict[str, int] = field(default_factory=dict)
    p50_latency: float = 0.0
    p95_latency: float = 0.0
    mean_total_tokens: float = 0.0
    word_count_in_range_rate: float = 0.0


def classify_failure(brief_errors: list[str]) -> bool:
    """True when the failure pattern indicates unparseable JSON.

    Heuristic, not exact: _summarize_one collapses a JSON parse failure and a
    genuinely bad brief into the same ValueError. All four image fields missing
    at once is the fallback-dict signature.
    """
    return _JSON_FAILURE_SIGNATURE.issubset(set(brief_errors))


def success_result(
    *, url: str, title: str, summary: str, rubric_passed: bool,
    total_tokens: int, latency_s: float, word_count: int,
) -> ArticleResult:
    return ArticleResult(
        url=url, title=title, ok=True, summary=summary,
        rubric_passed=rubric_passed, total_tokens=total_tokens,
        latency_s=latency_s, word_count=word_count,
    )


def failure_result(
    *, url: str, title: str, brief_errors: list[str], error: str, latency_s: float,
) -> ArticleResult:
    return ArticleResult(
        url=url, title=title, ok=False, brief_errors=list(brief_errors),
        json_failure=classify_failure(brief_errors), error=error,
        latency_s=latency_s,
    )


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def aggregate(
    model: str,
    results: list[ArticleResult],
    strict_results: list[ArticleResult],
) -> ModelAggregate:
    count = len(results)
    if count == 0:
        return ModelAggregate(model=model, article_count=0)

    field_failures: dict[str, int] = {}
    for result in results:
        for name in result.brief_errors:
            field_failures[name] = field_failures.get(name, 0) + 1

    latencies = [r.latency_s for r in results]
    low, high = WORD_TARGET
    in_range = sum(1 for r in results if r.ok and low <= r.word_count <= high)

    strict_rate = None
    if strict_results:
        strict_rate = sum(1 for r in strict_results if r.rubric_passed) / len(strict_results)

    return ModelAggregate(
        model=model,
        article_count=count,
        brief_valid_rate=sum(1 for r in results if r.ok) / count,
        first_pass_rate=sum(1 for r in results if r.ok and r.rubric_passed) / count,
        strict_recovery_rate=strict_rate,
        json_failure_count=sum(1 for r in results if r.json_failure),
        field_failures=field_failures,
        p50_latency=_percentile(latencies, 0.50),
        p95_latency=_percentile(latencies, 0.95),
        mean_total_tokens=sum(r.total_tokens for r in results) / count,
        word_count_in_range_rate=in_range / count,
    )


def unavailable(model: str, reason: str) -> ModelAggregate:
    return ModelAggregate(model=model, available=False, unavailable_reason=reason)
