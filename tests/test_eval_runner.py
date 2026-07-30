import json

from news_buddy import agent as news_buddy_agent
from scripts import eval_sub_model


def _config():
    return {
        "llm": {"sub_model": "base", "max_tokens": 512, "temperature": 0.2},
        "rubric": {"min_summary_length": 200, "min_summary_words": 65, "importance_penalty": 2},
    }


def _article(url="https://example.com/a"):
    return {"url": url, "title": "T", "source": "E", "published_at": "2026-07-29", "body": "body"}


# Comfortably over the 65-word rubric floor, three sentences, no vague
# boilerplate phrases, and doesn't open with a thin pronoun — passes
# specificity, completeness, and context.
_PASSING_SUMMARY = (
    "Acme Robotics unveiled a new manufacturing line in Ohio this week, adding "
    "hundreds of jobs and expanding production capacity for its warehouse "
    "automation systems across several regional distribution hubs. The company "
    "said the facility will begin shipping units within three months, targeting "
    "logistics providers across the Midwest region and beyond. Executives "
    "outlined plans to double output by next year while investing heavily in "
    "local training programs for assembly technicians and engineers."
)

# Well under the 65-word floor and a single sentence — fails completeness
# (and context, since it opens with "It ") without raising.
_FAILING_SUMMARY = "It was a short update with no real details to share."


def _success(item, summary=_PASSING_SUMMARY):
    return {**item, "summary": summary, "tags": ["ai"], "importance": 4}, 700


def _write_fixtures_manifest(tmp_path):
    """run() reads captured_at straight off manifest.json, independent of
    whatever load_fixtures() is monkeypatched to return."""
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "manifest.json").write_text(
        json.dumps({"captured_at": "2026-07-29T00:00:00+00:00"}), encoding="utf-8"
    )
    return fixtures_dir


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


def test_run_restores_extractor_patch_even_when_model_build_raises(monkeypatch, tmp_path):
    original_extract = news_buddy_agent._extract.extract_body

    monkeypatch.setenv("NVIDIA_API_KEY", "dummy-key")
    monkeypatch.setattr(eval_sub_model, "load_fixtures", lambda directory: [_article()])

    def _boom(config):
        raise RuntimeError("model build failed")

    monkeypatch.setattr(eval_sub_model, "_build_model", _boom)

    fixtures_dir = _write_fixtures_manifest(tmp_path)
    output = tmp_path / "report.md"

    eval_sub_model.run(["m"], fixtures_dir, output, baseline="m")

    assert news_buddy_agent._extract.extract_body is original_extract


def test_run_does_not_mutate_the_loaded_config_across_models(monkeypatch, tmp_path):
    monkeypatch.setenv("NVIDIA_API_KEY", "dummy-key")

    articles = [_article("https://example.com/a"), _article("https://example.com/b")]
    monkeypatch.setattr(eval_sub_model, "load_fixtures", lambda directory: articles)
    monkeypatch.setattr(eval_sub_model, "_build_model", lambda config: object())
    monkeypatch.setattr(
        eval_sub_model, "_summarize",
        lambda llm, item, strict=False: _success(item),
    )

    config = {
        "llm": {"sub_model": "model-a", "max_tokens": 512, "temperature": 0.2},
        "rubric": {"min_summary_length": 200, "min_summary_words": 65, "importance_penalty": 2},
    }
    monkeypatch.setattr(eval_sub_model, "_load_config", lambda: config)

    fixtures_dir = _write_fixtures_manifest(tmp_path)
    output = tmp_path / "report.md"

    eval_sub_model.run(["model-a", "model-b"], fixtures_dir, output, baseline="model-a")

    assert config == {
        "llm": {"sub_model": "model-a", "max_tokens": 512, "temperature": 0.2},
        "rubric": {"min_summary_length": 200, "min_summary_words": 65, "importance_penalty": 2},
    }


def test_run_limit_truncates_the_article_set(monkeypatch, tmp_path):
    monkeypatch.setenv("NVIDIA_API_KEY", "dummy-key")

    articles = [_article(f"https://example.com/{i}") for i in range(5)]
    monkeypatch.setattr(eval_sub_model, "load_fixtures", lambda directory: articles)
    monkeypatch.setattr(eval_sub_model, "_build_model", lambda config: object())

    called_urls = []

    def _fake_summarize(llm, item, strict=False):
        called_urls.append(item["url"])
        return _success(item)

    monkeypatch.setattr(eval_sub_model, "_summarize", _fake_summarize)

    fixtures_dir = _write_fixtures_manifest(tmp_path)
    output = tmp_path / "report.md"

    eval_sub_model.run(["m"], fixtures_dir, output, baseline="m", limit=2)

    assert len(set(called_urls)) == 2


def test_run_rpm_reaches_the_model_building_config(monkeypatch, tmp_path):
    monkeypatch.setenv("NVIDIA_API_KEY", "dummy-key")

    monkeypatch.setattr(eval_sub_model, "load_fixtures", lambda directory: [_article()])

    recorded = {}

    def _fake_build_model(config):
        recorded["config"] = config
        return object()

    monkeypatch.setattr(eval_sub_model, "_build_model", _fake_build_model)
    monkeypatch.setattr(
        eval_sub_model, "_summarize",
        lambda llm, item, strict=False: _success(item),
    )

    fixtures_dir = _write_fixtures_manifest(tmp_path)
    output = tmp_path / "report.md"

    eval_sub_model.run(["m"], fixtures_dir, output, baseline="m", rpm=42)

    assert recorded["config"]["llm"]["requests_per_minute"] == 42


def test_run_strict_retry_targets_only_articles_that_failed_the_rubric(monkeypatch, tmp_path):
    monkeypatch.setenv("NVIDIA_API_KEY", "dummy-key")

    passing = _article("https://example.com/pass")
    failing = _article("https://example.com/fail")
    erroring = _article("https://example.com/error")
    articles = [passing, failing, erroring]

    monkeypatch.setattr(eval_sub_model, "load_fixtures", lambda directory: articles)
    monkeypatch.setattr(eval_sub_model, "_build_model", lambda config: object())

    strict_calls = []

    def _fake_summarize(llm, item, strict=False):
        if strict:
            strict_calls.append(item["url"])
        if item["url"] == erroring["url"]:
            raise ValueError("boom")
        if item["url"] == failing["url"]:
            return _success(item, summary=_FAILING_SUMMARY)
        return _success(item)

    monkeypatch.setattr(eval_sub_model, "_summarize", _fake_summarize)

    fixtures_dir = _write_fixtures_manifest(tmp_path)
    output = tmp_path / "report.md"

    eval_sub_model.run(["m"], fixtures_dir, output, baseline="m")

    assert strict_calls == [failing["url"]]
