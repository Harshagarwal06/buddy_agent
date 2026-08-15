from scripts.eval_image_report import render_report
from scripts.eval_image_scoring import Agreement, VariantAggregate


def _agg(variant, clean=0.5, judged=16):
    return VariantAggregate(
        variant=variant, generated=judged, judged=judged, clean_rate=clean,
        text_rate=0.25, person_rate=0.125, palette_rate=0.0,
        three_group_rate=0.75, content_filtered=1,
        by_stratum={
            "mechanism": VariantAggregate(variant=variant, judged=8, clean_rate=clean),
            "person": VariantAggregate(variant=variant, judged=8, clean_rate=clean / 2),
        },
    )


def test_report_marks_the_baseline():
    report = render_report(
        [_agg("negated-truncated")], Agreement(labelled=20, text_accuracy=1.0,
        person_accuracy=1.0, trustworthy=True), "2026-08-15T00:00:00+00:00"
    )
    assert "_(production)_" in report


def test_report_states_the_decision_rule_before_the_numbers():
    report = render_report(
        [_agg("negated-truncated")], Agreement(labelled=20, text_accuracy=1.0,
        person_accuracy=1.0, trustworthy=True), "2026-08-15T00:00:00+00:00"
    )
    assert report.index("Decision rule") < report.index("## Results")


def test_untrustworthy_judge_marks_the_report_provisional():
    report = render_report(
        [_agg("negated-truncated")],
        Agreement(labelled=20, text_accuracy=0.6, person_accuracy=1.0,
                  trustworthy=False),
        "2026-08-15T00:00:00+00:00",
    )
    assert "PROVISIONAL" in report
    assert "should not be acted on" in report


def test_report_shows_both_judged_and_generated_counts():
    agg = _agg("negated-truncated")
    agg.generated = 16
    agg.judged = 14
    report = render_report(
        [agg],
        Agreement(labelled=20, text_accuracy=1.0, person_accuracy=1.0,
                  trustworthy=True),
        "2026-08-15T00:00:00+00:00",
    )
    assert "14/16" in report


def test_variant_names_with_pipes_do_not_break_the_table():
    agg = _agg("weird|name")
    report = render_report([agg], Agreement(), "2026-08-15T00:00:00+00:00")
    assert "weird\\|name" in report
