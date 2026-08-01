"""One repair attempt for an unusable image plan, then publish without an image."""

import json

import pytest

from news_buddy import agent


_GOOD_SUMMARY = (
    "Anthropic said Claude reached three corporate networks during a scheduled "
    "security exercise, and disclosed the access after an internal review. Two "
    "of the networks belonged to partners who had not agreed to that scope. The "
    "company now says it will narrow the blast radius of future red-team runs."
)

_VALID_PLAN = {
    "image_prompt": "An agent reaching into three separate corporate networks.",
    "image_layout": "branching",
    "image_labels": ["agent probe", "three networks", "disclosure"],
    "image_alt": "An agent reaching into three networks.",
}


def _enriched(**overrides):
    return {
        "title": "Claude reached three networks during security tests",
        "url": "https://example.test/claude",
        "summary": _GOOD_SUMMARY,
        "tags": ["ai", "security"],
        "importance": 4,
        "image_prompt": "",
        "image_layout": "spiral",
        "image_labels": ["input", "system", "result"],
        "image_alt": "",
        **overrides,
    }


class _Resp:
    def __init__(self, payload, tokens=300):
        self.content = payload if isinstance(payload, str) else json.dumps(payload)
        self.usage_metadata = {"input_tokens": tokens, "output_tokens": 0}


def _capture(monkeypatch, resp):
    """Patch the model call and record the messages it was sent."""
    seen = {}

    def _fake(_llm, messages, **_kwargs):
        seen["system"] = messages[0].content
        seen["payload"] = json.loads(messages[1].content)
        return resp

    monkeypatch.setattr(agent, "_invoke_with_retry", _fake)
    return seen


def test_repair_returns_a_publishable_plan(monkeypatch):
    seen = _capture(monkeypatch, _Resp(_VALID_PLAN))

    repaired, tokens = agent._repair_image_brief(
        object(), _enriched(), ["image_prompt", "image_layout"]
    )

    assert repaired["image_layout"] == "branching"
    assert repaired["image_labels"] == ["agent probe", "three networks", "disclosure"]
    # The accepted summary is carried through untouched.
    assert repaired["summary"] == _GOOD_SUMMARY
    assert repaired["tags"] == ["ai", "security"]
    assert tokens == 300
    # The model is told what it got wrong, not just the rules it already had.
    assert seen["payload"]["summary"] == _GOOD_SUMMARY
    assert seen["payload"]["rejected"]["image_layout"] == "spiral"
    assert any("pipeline" in problem for problem in seen["payload"]["problems"])


def test_repair_explains_the_generic_label_triad(monkeypatch):
    seen = _capture(monkeypatch, _Resp(_VALID_PLAN))

    agent._repair_image_brief(object(), _enriched(), ["article-specific image_labels"])

    [problem] = seen["payload"]["problems"]
    assert "INPUT / SYSTEM / RESULT" in problem


def test_repair_composes_field_rules_from_the_summarizer_prompt(monkeypatch):
    """Field definitions are pulled from summarizer.md so they cannot drift."""
    seen = _capture(monkeypatch, _Resp(_VALID_PLAN))

    agent._repair_image_brief(object(), _enriched(), ["image_prompt"])

    assert "no more than 18 characters" in seen["system"]
    assert '"pipeline", "branching"' in seen["system"]


def test_repair_that_is_still_invalid_raises(monkeypatch):
    _capture(monkeypatch, _Resp({**_VALID_PLAN, "image_layout": "still-wrong"}))

    with pytest.raises(agent.IncompleteImageBrief) as excinfo:
        agent._repair_image_brief(object(), _enriched(), ["image_layout"])

    assert excinfo.value.errors == ["image_layout"]
    assert excinfo.value.tokens == 300


def test_repair_tolerates_unparseable_json(monkeypatch):
    _capture(monkeypatch, _Resp("not json at all"))

    with pytest.raises(agent.IncompleteImageBrief):
        agent._repair_image_brief(object(), _enriched(), ["image_prompt"])
