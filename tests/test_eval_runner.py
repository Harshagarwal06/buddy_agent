from scripts import eval_sub_model


def _config():
    return {
        "llm": {"sub_model": "base", "max_tokens": 512, "temperature": 0.2},
        "rubric": {"min_summary_length": 200, "min_summary_words": 65, "importance_penalty": 2},
    }


def _article(url="https://example.com/a"):
    return {"url": url, "title": "T", "source": "E", "published_at": "2026-07-29", "body": "body"}


def test_evaluate_model_scores_a_successful_summary(monkeypatch):
    monkeypatch.setattr(eval_sub_model, "_build_model", lambda config: object())
    monkeypatch.setattr(
        eval_sub_model, "_summarize",
        lambda llm, item, strict=False: (
            {**item, "summary": "A named subject did a specific thing. " * 6,
             "tags": ["ai"], "importance": 4},
            700,
        ),
    )

    agg, results = eval_sub_model.evaluate_model("m", [_article()], _config())

    assert agg.article_count == 1
    assert agg.brief_valid_rate == 1.0
    assert results[0].ok is True


def test_evaluate_model_records_brief_failure_without_aborting(monkeypatch):
    def _boom(llm, item, strict=False):
        raise ValueError(
            "summarizer returned an incomplete article image brief: image_layout"
        )

    monkeypatch.setattr(eval_sub_model, "_build_model", lambda config: object())
    monkeypatch.setattr(eval_sub_model, "_summarize", _boom)

    agg, results = eval_sub_model.evaluate_model("m", [_article(), _article("u2")], _config())

    assert agg.article_count == 2
    assert agg.brief_valid_rate == 0.0
    assert agg.field_failures == {"image_layout": 2}
    assert results[0].json_failure is False


def test_evaluate_model_marks_unavailable_when_build_fails(monkeypatch):
    def _fail(config):
        raise RuntimeError("HTTP 404: model not found")

    monkeypatch.setattr(eval_sub_model, "_build_model", _fail)

    agg, results = eval_sub_model.evaluate_model("gone", [_article()], _config())

    assert agg.available is False
    assert "404" in agg.unavailable_reason
    assert results == []


def test_brief_errors_are_parsed_from_the_exception_message():
    parsed = eval_sub_model._parse_brief_errors(
        "summarizer returned an incomplete article image brief: "
        "image_prompt, image_layout, image_labels, image_alt"
    )
    assert parsed == ["image_prompt", "image_layout", "image_labels", "image_alt"]


def test_unrelated_exception_message_yields_no_brief_errors():
    assert eval_sub_model._parse_brief_errors("connection reset") == []
