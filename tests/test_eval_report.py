from scripts.eval_report import _escape_cell, render_report
from scripts.eval_scoring import ModelAggregate, success_result, unavailable


def _agg(model="m", **kwargs):
    defaults = dict(
        article_count=25, ok_count=24, brief_valid_rate=0.96, first_pass_rate=0.72,
        strict_recovery_rate=0.5, json_failure_count=1, error_count=0,
        field_failures={"image_layout": 1},
        p50_latency=1.2, p95_latency=3.4, mean_total_tokens=1310.0,
        word_count_in_range_rate=0.88,
    )
    defaults.update(kwargs)
    return ModelAggregate(model=model, **defaults)


def test_report_has_a_row_per_model():
    text = render_report([_agg("a"), _agg("b")], {}, "2026-07-30", "a")
    assert "| a " in text
    assert "| b " in text


def test_baseline_model_is_marked():
    text = render_report([_agg("a"), _agg("b")], {}, "2026-07-30", "a")
    assert "baseline" in text.lower()


def test_unavailable_model_shows_reason_not_zeros():
    text = render_report([_agg("a"), unavailable("b", "HTTP 404")], {}, "2026-07-30", "a")
    assert "HTTP 404" in text
    assert "unavailable" in text.lower()


def test_zero_article_model_renders_without_crashing():
    text = render_report([ModelAggregate(model="empty")], {}, "2026-07-30", "empty")
    assert "empty" in text


def test_json_failure_count_is_labelled_as_inferred():
    text = render_report([_agg()], {}, "2026-07-30", "m")
    assert "inferred" in text.lower()


def test_json_failures_are_described_as_possible_truncation():
    text = render_report([_agg(json_failure_count=3)], {}, "2026-07-30", "m")
    assert "truncat" in text.lower()


def test_samples_render_summaries_per_model():
    sample = success_result(
        url="u", title="Sample Title", summary="A specific briefing.",
        rubric_passed=True, total_tokens=800, latency_s=1.0, word_count=90,
    )
    text = render_report([_agg("a")], {"a": [sample]}, "2026-07-30", "a")
    assert "Sample Title" in text
    assert "A specific briefing." in text


def test_strict_recovery_none_renders_as_dash():
    text = render_report([_agg(strict_recovery_rate=None)], {}, "2026-07-30", "m")
    assert "n/a" in text.lower() or "—" in text


def test_summary_table_has_an_n_column_showing_corpus_size():
    text = render_report([_agg("a", article_count=24)], {}, "2026-07-30", "a")
    assert "| N |" in text
    row = next(line for line in text.splitlines() if line.startswith("| a "))
    # the data row carries article_count as the N value
    assert "24" in row


def test_mean_tok_column_header_notes_successful_calls_only():
    text = render_report([_agg("a")], {}, "2026-07-30", "a")
    assert "Mean tok (ok)" in text


def test_error_count_appears_in_failure_section_when_nonzero():
    text = render_report([_agg("a", error_count=6)], {}, "2026-07-30", "a")
    line = next(line for line in text.splitlines() if "non-brief failures" in line)
    assert "6" in line


def test_error_count_omitted_from_failure_section_when_zero():
    text = render_report([_agg("a", error_count=0)], {}, "2026-07-30", "a")
    assert "non-brief failures" not in text


def test_escape_cell_escapes_pipes_and_newlines():
    assert _escape_cell("a | b") == "a \\| b"
    assert _escape_cell("line1\nline2") == "line1 line2"


def test_unavailable_reason_with_pipe_and_newline_does_not_break_table_row():
    reason = "HTTP 500 | body: {\"error\": \"x\"}\nsecond line"
    text = render_report([unavailable("a", reason)], {}, "2026-07-30", "a")
    row = next(line for line in text.splitlines() if line.startswith("| a "))
    # the row must still parse as exactly one markdown table row: no bare
    # (unescaped) pipe from the reason, and no literal newline inside a cell.
    assert "\\| body" in row
    assert "\n" not in row
    # column count must match the header once escaped pipes are discounted
    # (an escaped "\|" is a literal character inside a cell, not a separator)
    header = next(line for line in text.splitlines() if line.startswith("| Model"))
    unescaped_pipes_in_row = row.replace("\\|", "").count("|")
    assert unescaped_pipes_in_row == header.count("|")
