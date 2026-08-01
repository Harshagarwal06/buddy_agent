import base64
import io

import httpx
from PIL import Image

from news_buddy import image_generator


def _item():
    return {
        "title": "Small models decide when to use the cloud",
        "url": "https://example.test/hybrid",
        "summary": "A local model estimates confidence before handing work to a cloud model.",
        "tags": ["ai"],
        "image_prompt": "A local model routes uncertain work to a larger cloud model.",
        "image_layout": "branching",
        "image_labels": ["local model", "confidence", "cloud model"],
        "image_alt": "A local model routing uncertain work to a cloud model.",
    }


def _config():
    return {
        "enabled": True,
        "provider": "auto",
        "model": "example/image-model",
        "width": 640,
        "height": 480,
        "quality": 80,
        "max_workers": 2,
        "style_version": "test-v1",
    }


def test_missing_token_creates_placeholder(tmp_path, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)

    items, ready, failures = image_generator.generate_article_images(
        [_item()],
        tmp_path,
        _config(),
    )

    assert ready == 1
    assert failures == 1
    assert items[0]["image_url"].startswith("images/")
    assert items[0]["image_url"].endswith(".svg")
    assert (tmp_path / items[0]["image_url"]).exists()


def test_generated_image_is_cached(tmp_path, monkeypatch):
    calls = []

    class FakeClient:
        def text_to_image(self, prompt, **kwargs):
            calls.append((prompt, kwargs))
            return Image.new("RGB", (320, 240), "#3366cc")

    monkeypatch.setenv("HF_TOKEN", "test-token")
    monkeypatch.setattr(
        image_generator,
        "_make_client",
        lambda _settings, _token: FakeClient(),
    )

    first, first_ready, first_failures = image_generator.generate_article_images(
        [_item()],
        tmp_path,
        _config(),
    )
    second, second_ready, second_failures = image_generator.generate_article_images(
        [_item()],
        tmp_path,
        _config(),
    )

    assert len(calls) == 1
    assert first_ready == second_ready == 1
    assert first_failures == second_failures == 0
    assert first[0]["image_url"] == second[0]["image_url"]
    assert first[0]["image_url"].endswith(".webp")
    assert first[0]["image_width"] == second[0]["image_width"] == 640
    assert first[0]["image_height"] == second[0]["image_height"] == 480
    assert '"LOCAL MODEL"' not in calls[0][0]
    assert "split into two or three paths" in calls[0][0]
    assert "warm cream paper" in calls[0][0].lower()
    assert "completely unlabeled" in calls[0][0]
    assert len(calls[0][0]) <= image_generator.MAX_IMAGE_PROMPT_CHARS
    with Image.open(tmp_path / first[0]["image_url"]) as rendered:
        assert rendered.size == (640, 480)
        pixel = rendered.getpixel((10, 470))
        assert all(abs(actual - expected) <= 2 for actual, expected in zip(pixel, (243, 236, 216)))
        header_pixel = rendered.getpixel((10, 10))
        assert all(
            abs(actual - expected) <= 2
            for actual, expected in zip(header_pixel, (243, 236, 216))
        )


def test_nvidia_provider_decodes_hosted_image_response(tmp_path, monkeypatch):
    source = io.BytesIO()
    Image.new("RGB", (320, 240), "#8d2f25").save(source, format="PNG")
    encoded = base64.b64encode(source.getvalue()).decode()
    calls = []

    class FakeResponse:
        def __init__(self, image_data, finish_reason=None):
            self.image_data = image_data
            self.finish_reason = finish_reason

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "artifacts": [
                    {
                        "base64": self.image_data,
                        "finishReason": self.finish_reason,
                    }
                ]
            }

    def fake_post(url, *, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        if len(calls) == 1:
            return FakeResponse("", "CONTENT_FILTERED")
        return FakeResponse(encoded)

    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-token")
    monkeypatch.setattr(httpx, "post", fake_post)
    config = {
        **_config(),
        "provider": "nvidia",
        "model": "black-forest-labs/flux.2-klein-4b",
        "api_url": "https://example.test/nvidia-image",
        "steps": 4,
        "retry_delay": 0,
    }

    items, ready, failures = image_generator.generate_article_images(
        [_item()],
        tmp_path,
        config,
    )
    cached_items, cached_ready, cached_failures = (
        image_generator.generate_article_images([_item()], tmp_path, config)
    )

    assert ready == cached_ready == 1
    assert failures == cached_failures == 0
    assert items[0]["image_url"].endswith(".webp")
    assert cached_items[0]["image_url"] == items[0]["image_url"]
    assert items[0]["image_alt"].startswith("AI-generated explainer diagram")
    assert len(calls) == 2
    url, headers, payload, timeout = calls[-1]
    assert url == "https://example.test/nvidia-image"
    assert headers["Authorization"] == "Bearer test-nvidia-token"
    assert payload["width"] == 640
    assert payload["height"] == 480
    assert payload["steps"] == 4
    assert timeout == 180
    assert "local model routes" not in payload["prompt"].lower()
    assert "locked cloud" in payload["prompt"].lower()
    assert '"LOCAL MODEL"' not in payload["prompt"]
    assert "people, logos, photos" in payload["prompt"].lower()


def test_image_request_retries_before_fallback(tmp_path, monkeypatch):
    calls = []

    class FlakyClient:
        def text_to_image(self, prompt, **kwargs):
            calls.append((prompt, kwargs))
            if len(calls) < 3:
                raise httpx.ReadTimeout("temporary timeout")
            return Image.new("RGB", (320, 240), "#3366cc")

    monkeypatch.setenv("HF_TOKEN", "test-token")
    monkeypatch.setattr(
        image_generator,
        "_make_client",
        lambda _settings, _token: FlakyClient(),
    )
    config = {**_config(), "retries": 2, "retry_delay": 0}

    items, ready, failures = image_generator.generate_article_images(
        [_item()],
        tmp_path,
        config,
    )

    assert len(calls) == 3
    assert ready == 1
    assert failures == 0
    assert items[0]["image_url"].endswith(".webp")


def test_required_brief_does_not_retry_with_generic_safe_prompt(tmp_path, monkeypatch):
    calls = []

    class FilteredClient:
        def text_to_image(self, prompt, **kwargs):
            calls.append((prompt, kwargs))
            raise image_generator.ImageContentFilteredError("filtered")

    monkeypatch.setenv("NVIDIA_API_KEY", "test-token")
    monkeypatch.setattr(
        image_generator,
        "_make_client",
        lambda _settings, _token: FilteredClient(),
    )
    config = {
        **_config(),
        "provider": "nvidia",
        "require_article_brief": True,
    }

    items, ready, failures = image_generator.generate_article_images(
        [_item()],
        tmp_path,
        config,
    )

    assert len(calls) == 1
    assert ready == 1
    assert failures == 1
    assert items[0]["image_url"].endswith(".svg")
    assert "local model routes" in calls[0][0].lower()


def test_disabled_images_leave_items_unchanged(tmp_path):
    original = [_item()]

    items, ready, failures = image_generator.generate_article_images(
        original,
        tmp_path,
        {"enabled": False},
    )

    assert items is original
    assert ready == 0
    assert failures == 0


def test_style_is_loaded_from_markdown_contract(tmp_path):
    guide = tmp_path / "image-style.md"
    guide.write_text(
        "Human guidance\n"
        "<!-- image-model-directive:start -->\n"
        "Cream paper and charcoal arrows.\n"
        "<!-- image-model-directive:end -->\n",
        encoding="utf-8",
    )

    settings = image_generator.ImageSettings.from_config(
        {**_config(), "style_guide": str(guide)}
    )

    assert settings.style == "Cream paper and charcoal arrows."


def test_required_article_brief_rejects_generic_fallback(tmp_path):
    item = {
        "title": "Grid constraints slow data center expansion",
        "summary": "Power shortages are delaying new computing capacity.",
    }

    try:
        image_generator.generate_article_images(
            [item],
            tmp_path,
            {**_config(), "require_article_brief": True},
        )
    except RuntimeError as exc:
        assert "refusing generic images" in str(exc)
        assert "image_prompt" in str(exc)
        assert "image_labels" in str(exc)
    else:
        raise AssertionError("missing article brief should stop image generation")


def test_article_brief_accepts_long_labels_because_renderer_truncates():
    """Over-long labels are normalised by _image_labels, so they are not fatal."""
    item = {
        **_item(),
        "image_labels": [
            "local confidence estimator",
            "cloud escalation path",
            "final answer returned",
        ],
    }

    assert image_generator._article_brief_errors(item) == []
    assert image_generator._image_labels(item) == [
        "LOCAL CONFIDENCE",
        "CLOUD ESCALATION",
        "FINAL ANSWER",
    ]


def test_required_article_brief_rejects_generic_label_triad(tmp_path):
    item = {
        **_item(),
        "image_labels": ["input", "system", "result"],
    }

    try:
        image_generator.generate_article_images(
            [item],
            tmp_path,
            {**_config(), "require_article_brief": True},
        )
    except RuntimeError as exc:
        assert "article-specific image_labels" in str(exc)
    else:
        raise AssertionError("generic labels should not pass the article brief gate")


def test_unplanned_visual_prompt_uses_article_context():
    item = {
        "title": "Grid constraints slow data center expansion",
        "summary": "Power shortages are delaying new computing capacity.",
    }

    prompt = image_generator._visual_prompt(item)

    assert "Grid constraints slow data center expansion" in prompt
    assert "Power shortages" in prompt
    assert "input entering a system" not in prompt


def test_label_band_normalizes_white_background_to_cream():
    source = Image.new("RGB", (640, 480), "#ffffff")

    rendered = image_generator._add_label_band(
        source,
        ["GRID DEMAND", "POWER CUTS", "ON-SITE POWER"],
    )

    assert rendered.getpixel((10, 100)) == (243, 236, 216)


def test_safe_briefs_preserve_distinct_article_mechanisms():
    database_item = {
        "title": "Hacker wipes land registry and backups",
        "summary": "Both the primary database and backup storage were erased.",
    }
    swarm_item = {
        "title": "Agent swarm completes complex tasks",
        "summary": "A planner delegates work to several worker agents.",
    }

    database_prompt = image_generator._safe_infographic_prompt(database_item)
    swarm_prompt = image_generator._safe_infographic_prompt(swarm_item)

    assert "main database and its backup both crossed out" in database_prompt
    assert image_generator._image_labels(database_item) == ["PRIMARY", "BACKUP", "HALT"]
    assert "planner node branching to three worker nodes" in swarm_prompt
    assert image_generator._image_labels(swarm_item) == ["PLANNER", "WORKERS", "RESULT"]
    assert database_prompt != swarm_prompt


def test_image_labels_are_short_sanitized_and_limited_to_three():
    item = {
        "image_labels": [
            "Local model!",
            "confidence score is huge",
            "Cloud/model",
            "ignored",
        ]
    }

    assert image_generator._image_labels(item) == [
        "LOCAL MODEL",
        "CONFIDENCE SCORE",
        "CLOUD/MODEL",
    ]
