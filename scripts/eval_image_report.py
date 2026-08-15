"""Markdown rendering for the image directive evaluation. No network."""

from __future__ import annotations

from scripts.eval_image_scoring import (
    AGREEMENT_THRESHOLD,
    BASELINE_VARIANT,
    Agreement,
    VariantAggregate,
)


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _escape_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _stratum_rate(agg: VariantAggregate, stratum: str) -> str:
    child = agg.by_stratum.get(stratum)
    return "n/a" if child is None else _pct(child.clean_rate)


def _summary_table(aggregates: list[VariantAggregate]) -> list[str]:
    lines = [
        "| Variant | Clean (all) | Clean (mechanism) | Clean (person) | Text | "
        "Person | Palette | 3-group | Filtered | Judged/Generated |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for agg in aggregates:
        label = _escape_cell(agg.variant)
        if agg.variant == BASELINE_VARIANT:
            label += " _(production)_"
        lines.append(
            "| "
            + " | ".join(
                [
                    label,
                    _pct(agg.clean_rate),
                    _stratum_rate(agg, "mechanism"),
                    _stratum_rate(agg, "person"),
                    _pct(agg.text_rate),
                    _pct(agg.person_rate),
                    _pct(agg.palette_rate),
                    _pct(agg.three_group_rate),
                    str(agg.content_filtered),
                    f"{agg.judged}/{agg.generated}",
                ]
            )
            + " |"
        )
    return lines


def _agreement_section(agreement: Agreement) -> list[str]:
    if agreement.labelled == 0:
        return [
            "> **PROVISIONAL — the judge is uncalibrated.** No hand labels were "
            "supplied, so the verdicts below have no measured accuracy and "
            "should not be acted on. Run `--label`, fill in the template, and "
            "re-run `--report`.",
            "",
        ]
    lines = [
        f"**Judge agreement** ({agreement.labelled} hand-labelled images): "
        f"text {_pct(agreement.text_accuracy)}, "
        f"person {_pct(agreement.person_accuracy)}.",
        "",
    ]
    if not agreement.trustworthy:
        lines = [
            f"> **PROVISIONAL — judge agreement is below "
            f"{_pct(AGREEMENT_THRESHOLD)}.** These conclusions should not be "
            f"acted on until the judge is improved.",
            "",
        ] + lines
    return lines


def render_report(
    aggregates: list[VariantAggregate],
    agreement: Agreement,
    captured_at: str,
) -> str:
    lines = [
        "# Image Directive Evaluation",
        "",
        f"**Fixtures captured:** {captured_at}",
        "",
        *_agreement_section(agreement),
        "## Decision rule (fixed before the run)",
        "",
        "`clean_rate` is the share of judged images with no text, no person, and "
        "a cream background. A variant is adopted only if it beats "
        f"`{BASELINE_VARIANT}` on `clean_rate` **in both strata**. A variant "
        "that wins overall but loses on the `person` stratum is conditional, not "
        "adopted. \"No variant wins\" is a valid outcome and would indicate the "
        "leverage is in the planner, not the renderer.",
        "",
        "Rates divide by judged images, never by attempts. Generation failures "
        "and judge failures are excluded and reported separately so a variant "
        "cannot benefit from producing nothing.",
        "",
        "## Results",
        "",
    ]
    lines += _summary_table(aggregates)
    lines.append("")
    return "\n".join(lines) + "\n"
