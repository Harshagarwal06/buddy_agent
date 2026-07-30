from scripts.eval_scoring import (
    aggregate,
    classify_failure,
    failure_result,
    success_result,
    unavailable,
)

_JSON_SIGNATURE = ["image_prompt", "image_layout", "image_labels", "image_alt"]


def _ok(url="u", tokens=900, latency=1.0, passed=True, words=90):
    return success_result(
        url=url, title="T", summary="s" * 10, rubric_passed=passed,
        total_tokens=tokens, latency_s=latency, word_count=words,
    )


def test_all_four_fields_missing_is_the_json_signature():
    assert classify_failure(_JSON_SIGNATURE) is True


def test_subset_failure_is_not_a_json_failure():
    assert classify_failure(["image_layout"]) is False
    assert classify_failure(["image_prompt", "image_alt"]) is False


def test_label_quality_failure_is_not_a_json_failure():
    assert classify_failure(["short image_labels"]) is False
    assert classify_failure(["article-specific image_labels"]) is False


def test_empty_errors_is_not_a_failure():
    assert classify_failure([]) is False


def test_failure_result_records_errors_and_flags_json():
    result = failure_result(
        url="u", title="T", brief_errors=_JSON_SIGNATURE,
        error="bad brief", latency_s=2.0,
    )
    assert result.ok is False
    assert result.json_failure is True
    assert result.rubric_passed is False


def test_aggregate_computes_rates():
    results = [_ok(passed=True), _ok(passed=False), failure_result(
        url="c", title="T", brief_errors=["image_layout"], error="e", latency_s=1.0
    )]
    agg = aggregate("m", results, strict_results=[])

    assert agg.article_count == 3
    assert round(agg.brief_valid_rate, 3) == round(2 / 3, 3)
    assert round(agg.first_pass_rate, 3) == round(1 / 3, 3)
    assert agg.field_failures == {"image_layout": 1}
    assert agg.json_failure_count == 0


def test_aggregate_counts_inferred_json_failures():
    results = [
        failure_result(url="a", title="T", brief_errors=_JSON_SIGNATURE, error="e", latency_s=1.0),
        failure_result(url="b", title="T", brief_errors=["image_alt"], error="e", latency_s=1.0),
    ]
    agg = aggregate("m", results, [])
    assert agg.json_failure_count == 1


def test_aggregate_reports_mean_total_tokens():
    agg = aggregate("m", [_ok(tokens=800), _ok(tokens=1000)], [])
    assert agg.mean_total_tokens == 900.0


def test_strict_recovery_rate_is_share_of_retried_that_pass():
    strict = [_ok(url="a", passed=True), _ok(url="b", passed=False)]
    agg = aggregate("m", [_ok(passed=False)], strict)
    assert agg.strict_recovery_rate == 0.5


def test_strict_recovery_rate_is_none_when_nothing_retried():
    agg = aggregate("m", [_ok(passed=True)], [])
    assert agg.strict_recovery_rate is None


def test_percentiles_on_single_result_do_not_crash():
    agg = aggregate("m", [_ok(latency=2.5)], [])
    assert agg.p50_latency == 2.5
    assert agg.p95_latency == 2.5


def test_aggregate_of_no_results_is_all_zero_not_a_crash():
    agg = aggregate("m", [], [])
    assert agg.article_count == 0
    assert agg.brief_valid_rate == 0.0
    assert agg.p50_latency == 0.0


def test_unavailable_model_carries_reason():
    agg = unavailable("m", "HTTP 404")
    assert agg.available is False
    assert agg.unavailable_reason == "HTTP 404"
    assert agg.article_count == 0


def test_word_count_in_range_uses_the_prompt_target():
    agg = aggregate("m", [_ok(words=90), _ok(words=40)], [])
    assert agg.word_count_in_range_rate == 0.5
