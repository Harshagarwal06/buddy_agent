from news_buddy import agent


def _state(tmp_path, *, test_run=False, generate_in_test_run=False):
    return {
        "config": {
            "output_dir": str(tmp_path),
            "images": {
                "enabled": True,
                "generate_in_test_run": generate_in_test_run,
            },
        },
        "enriched_items": [{"title": "Story", "url": "https://example.test/story"}],
        "dry_run": False,
        "test_run": test_run,
        "verbose": False,
    }


def test_generate_images_node_skips_test_run_by_default(tmp_path, monkeypatch):
    def should_not_run(*_args, **_kwargs):
        raise AssertionError("generator should not be called")

    monkeypatch.setattr(
        "news_buddy.image_generator.generate_article_images",
        should_not_run,
    )

    result = agent.generate_article_images_node(_state(tmp_path, test_run=True))

    assert result == {"images_ready": 0, "image_failures": 0}


def test_generate_images_node_updates_enriched_items(tmp_path, monkeypatch):
    generated = [{
        "title": "Story",
        "url": "https://example.test/story",
        "image_url": "images/story.webp",
        "image_alt": "A story illustration",
    }]
    monkeypatch.setattr(
        "news_buddy.image_generator.generate_article_images",
        lambda *_args, **_kwargs: (generated, 1, 0),
    )

    result = agent.generate_article_images_node(_state(tmp_path))

    assert result["enriched_items"] == generated
    assert result["images_ready"] == 1
    assert result["image_failures"] == 0
