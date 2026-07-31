"""Markdown rendering for the sub_model evaluation report. No network."""

from __future__ import annotations

from scripts.eval_scoring import ArticleResult, ModelAggregate, WORD_TARGET


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _rate_or_dash(value: float | None) -> str:
    return "n/a" if value is None else _pct(value)


def _escape_cell(text: str) -> str:
    """Escape characters that would break a markdown table row."""
    return text.replace("|", "\\|").replace("\n", " ")


def _summary_table(aggregates: list[ModelAggregate], baseline_model: str) -> list[str]:
    lines = [
        "| Model | N | Brief valid | First-pass rubric | Strict recovery | JSON fail | p50 | p95 | Mean tok (ok) | Words in range |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for agg in aggregates:
        label = agg.model + (" _(baseline)_" if agg.model == baseline_model else "")
        if not agg.available:
            reason = _escape_cell(agg.unavailable_reason)
            cells = [label, "", f"unavailable — {reason}", "", "", "", "", "", "", ""]
        else:
            cells = [
                label,
                str(agg.article_count),
                _pct(agg.brief_valid_rate),
                _pct(agg.first_pass_rate),
                _rate_or_dash(agg.strict_recovery_rate),
                str(agg.json_failure_count),
                f"{agg.p50_latency:.1f}s",
                f"{agg.p95_latency:.1f}s",
                f"{agg.mean_total_tokens:.0f}",
                _pct(agg.word_count_in_range_rate),
            ]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _failure_section(aggregates: list[ModelAggregate]) -> list[str]:
    lines = ["## Failure breakdown", ""]
    for agg in aggregates:
        if not agg.available:
            continue
        lines.append(f"**{agg.model}**")
        if not agg.field_failures:
            lines.append("- no brief failures")
        else:
            for name, count in sorted(agg.field_failures.items()):
                lines.append(f"- `{name}`: {count}")
        lines.append(
            f"- JSON parse failures (inferred from all four image fields "
            f"missing at once): {agg.json_failure_count}"
        )
        if agg.error_count:
            lines.append(
                f"- non-brief failures (timeouts, API errors): {agg.error_count}"
            )
        if agg.json_failure_count:
            lines.append(
                "  - a response truncated at the token cap is also invalid JSON, "
                "so these may be truncation rather than formatting failures"
            )
        lines.append("")
    return lines


def _samples_section(samples: dict[str, list[ArticleResult]]) -> list[str]:
    if not samples:
        return []
    lines = ["## Sample outputs", ""]
    for model, results in samples.items():
        lines.append(f"### {model}")
        lines.append("")
        for result in results:
            lines.append(f"**{result.title}**")
            lines.append("")
            lines.append(result.summary if result.ok else f"_failed: {result.error}_")
            lines.append("")
    return lines


def render_report(
    aggregates: list[ModelAggregate],
    samples: dict[str, list[ArticleResult]],
    captured_at: str,
    baseline_model: str,
) -> str:
    low, high = WORD_TARGET
    lines = [
        "# Sub-Model Baseline Evaluation",
        "",
        f"**Fixtures captured:** {captured_at}",
        f"**Word target:** {low}–{high} words per summary",
        "",
        "Scored with the pipeline's own `RubricMiddleware` and "
        "`_article_brief_errors`. Brief validity is the headline metric: an "
        "invalid brief blocks publication under `images.require_all`.",
        "",
        "## Results",
        "",
    ]
    lines += _summary_table(aggregates, baseline_model)
    lines += ["", *_failure_section(aggregates)]
    lines += _samples_section(samples)
    return "\n".join(lines) + "\n"
