from PIL import Image

from news_buddy import image_generator


def _item():
    return {
        "title": "Small models decide when to use the cloud",
        "url": "https://example.test/hybrid",
        "summary": "A local model estimates confidence before handing work to a cloud model.",
        "tags": ["ai"],
        "image_prompt": "A small blue robot deciding whether to pass a task to a large cloud.",
        "image_alt": "A small robot choosing whether to hand a task to a cloud.",
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
    with Image.open(tmp_path / first[0]["image_url"]) as rendered:
        assert rendered.size == (640, 480)


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
