import io
import json

import pytest
from PIL import Image

from news_buddy.image_generator import MAX_IMAGE_PROMPT_CHARS
from scripts import eval_image
from scripts.eval_image import assemble_prompt, load_topics
from scripts.eval_image_judge import JudgeVerdict


def test_load_topics_maps_url_to_stratum(tmp_path):
    path = tmp_path / "topics.json"
    path.write_text(json.dumps({"mechanism": ["u1", "u2"], "person": ["u3"]}))
    topics = load_topics(path)
    assert topics == {"u1": "mechanism", "u2": "mechanism", "u3": "person"}


def test_load_topics_rejects_a_url_in_both_strata(tmp_path):
    path = tmp_path / "topics.json"
    path.write_text(json.dumps({"mechanism": ["u1"], "person": ["u1"]}))
    with pytest.raises(ValueError, match="both strata"):
        load_topics(path)


def test_load_topics_rejects_unknown_strata(tmp_path):
    path = tmp_path / "topics.json"
    path.write_text(json.dumps({"mechanism": ["u1"], "vibes": ["u2"]}))
    with pytest.raises(ValueError, match="unknown stratum"):
        load_topics(path)


def test_truncated_assembly_loses_the_directive_tail():
    """Reproduces the production defect: the contract is what gets cut."""
    article = "A" * 600
    directive = "D" * 390
    prompt = assemble_prompt(article, directive, preserve=False)
    assert len(prompt) == MAX_IMAGE_PROMPT_CHARS
    assert directive not in prompt


def test_preserved_assembly_keeps_the_whole_directive():
    article = "A" * 600
    directive = "D" * 390
    prompt = assemble_prompt(article, directive, preserve=True)
    assert len(prompt) <= MAX_IMAGE_PROMPT_CHARS
    assert directive in prompt


def test_preserved_assembly_trims_the_article_half_instead():
    article = "A" * 600
    directive = "D" * 390
    prompt = assemble_prompt(article, directive, preserve=True)
    assert prompt.count("A") < 600


def test_short_prompts_are_identical_under_both_assemblies():
    article = "A" * 50
    directive = "D" * 100
    assert assemble_prompt(article, directive, preserve=False) == assemble_prompt(
        article, directive, preserve=True
    )


def _png(color=(243, 236, 216)):
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="PNG")
    return buf.getvalue()


class _FakeJudge:
    def judge(self, image_bytes, mime_type="image/png"):
        return JudgeVerdict(has_text=False, has_person=False, object_group_count=3)


class _FakeImageClient:
    def __init__(self, settings):
        self.settings = settings

    def text_to_image(self, prompt, *, model, width, height, negative_prompt):
        return _png()


def test_run_variants_produces_one_result_per_variant(monkeypatch, tmp_path):
    monkeypatch.setattr(eval_image, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(eval_image, "load_topics", lambda *a, **k: {"u1": "mechanism"})
    monkeypatch.setattr(
        eval_image, "load_briefs",
        lambda: {"u1": {"title": "T", "summary": "S", "image_prompt": "P",
                        "image_layout": "pipeline", "image_labels": ["A", "B", "C"],
                        "image_alt": "alt"}},
    )
    results = eval_image.run_variants(_FakeJudge(), _FakeImageClient)
    assert len(results) == 4
    assert {r.variant for r in results} == set(eval_image.VARIANTS)
    assert all(r.ok for r in results)
    assert all(r.background_is_cream for r in results)
