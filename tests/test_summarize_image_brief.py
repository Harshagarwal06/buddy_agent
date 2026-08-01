"""An unusable image brief must cost the article its image, not its summary."""

import json

from news_buddy import agent
from scripts import eval_sub_model


_GOOD_SUMMARY = (
    "Anthropic said Claude reached three corporate networks during a scheduled "
    "security exercise, and the company disclosed the access after internal "
    "review. The tests were authorised, but two of the networks belonged to "
    "partners who had not agreed to that scope. Anthropic now says it will "
    "narrow the blast radius of future red-team runs and publish the results."
)


def _item():
    return {
        "title": "Claude reached three networks during security tests",
        "url": "https://example.test/claude",
        "source": "Example",
        "published_at": "2026-08-01",
    }


def _response(payload: dict):
    class _Resp:
        content = json.dumps(payload)
        usage_metadata = {"input_tokens": 900, "output_tokens": 120}

    return _Resp()


def _payload(**overrides):
    return {
        "summary": _GOOD_SUMMARY,
        "tags": ["ai", "security"],
        "importance": 4,
        "image_prompt": "An agent reaching into three separate corporate networks.",
        "image_layout": "branching",
        "image_labels": ["agent", "three networks", "disclosure"],
        "image_alt": "An agent reaching into three networks.",
        **overrides,
    }


def _patch_model(monkeypatch, payload: dict):
    monkeypatch.setattr(agent._extract, "extract_body", lambda url: "article body")
    monkeypatch.setattr(
        agent,
        "_invoke_with_retry",
        lambda *_args, **_kwargs: _response(payload),
    )


def test_incomplete_brief_carries_the_parsed_item(monkeypatch):
    _patch_model(monkeypatch, _payload(image_prompt="", image_alt=""))

    try:
        agent._summarize_one(object(), _item())
    except agent.IncompleteImageBrief as exc:
        # The good summary survives the bad image plan.
        assert exc.item["summary"] == _GOOD_SUMMARY
        assert exc.item["tags"] == ["ai", "security"]
        assert exc.errors == ["image_prompt", "image_alt"]
        assert exc.tokens == 1020
    else:
        raise AssertionError("an unusable brief should still be signalled")


def test_incomplete_brief_message_matches_the_eval_contract(monkeypatch):
    """scripts/eval_sub_model parses this exact wording to score brief validity."""
    _patch_model(monkeypatch, _payload(image_layout="spiral"))

    try:
        agent._summarize_one(object(), _item())
    except agent.IncompleteImageBrief as exc:
        assert str(exc) == (
            "summarizer returned an incomplete article image brief: image_layout"
        )
        assert eval_sub_model._parse_brief_errors(str(exc)) == ["image_layout"]
    else:
        raise AssertionError("an unusable brief should still be signalled")


def test_summarize_node_keeps_the_summary_and_drops_only_the_image(monkeypatch):
    _patch_model(monkeypatch, _payload(image_labels=["input", "system", "result"]))
    monkeypatch.setattr(agent, "get_sub_model", lambda _config: object())
    monkeypatch.setattr(agent._state, "mark_seen", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(agent, "_rag_enabled", lambda: False)

    state = {
        "config": {
            "llm": {"sub_model": "m"},
            "rubric": {"enabled": False},
        },
        "unseen_items": [_item()],
        "dry_run": False,
        "force": False,
        "test_run": False,
        "verbose": False,
    }

    result = agent.summarize_articles_node(state)

    [article] = result["enriched_items"]
    assert article["summary"] == _GOOD_SUMMARY
    assert article["tags"] == ["ai", "security"]
    # No half-brief leaks downstream.
    assert not any(key.startswith("image_") for key in article)
