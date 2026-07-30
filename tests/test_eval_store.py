import json

import pytest

from scripts.eval_store import (
    FixtureError,
    body_sha256,
    load_fixtures,
    save_fixtures,
)


def _article(url: str = "https://example.com/a", body: str = "body text") -> dict:
    return {
        "url": url,
        "title": "A Title",
        "source": "Example",
        "published_at": "2026-07-30",
        "body": body,
    }


def test_body_sha256_is_stable_and_content_dependent():
    assert body_sha256("abc") == body_sha256("abc")
    assert body_sha256("abc") != body_sha256("abd")


def test_save_writes_bodies_only_to_articles_file(tmp_path):
    articles_path, manifest_path = save_fixtures(tmp_path, [_article()])

    articles = json.loads(articles_path.read_text())
    manifest = json.loads(manifest_path.read_text())

    assert articles[0]["body"] == "body text"
    assert "body" not in manifest["articles"][0]
    assert manifest["articles"][0]["body_sha256"] == body_sha256("body text")
    assert manifest["articles"][0]["url"] == "https://example.com/a"


def test_round_trip_returns_articles(tmp_path):
    save_fixtures(tmp_path, [_article()])
    assert load_fixtures(tmp_path) == [_article()]


def test_load_rejects_body_that_does_not_match_manifest(tmp_path):
    articles_path, _ = save_fixtures(tmp_path, [_article()])
    tampered = json.loads(articles_path.read_text())
    tampered[0]["body"] = "different text"
    articles_path.write_text(json.dumps(tampered))

    with pytest.raises(FixtureError, match="does not match"):
        load_fixtures(tmp_path)


def test_load_rejects_article_missing_from_manifest(tmp_path):
    articles_path, _ = save_fixtures(tmp_path, [_article()])
    extra = json.loads(articles_path.read_text())
    extra.append(_article(url="https://example.com/b"))
    articles_path.write_text(json.dumps(extra))

    with pytest.raises(FixtureError, match="not in the manifest"):
        load_fixtures(tmp_path)


def test_load_reports_missing_articles_file(tmp_path):
    save_fixtures(tmp_path, [_article()])
    (tmp_path / "articles.json").unlink()

    with pytest.raises(FixtureError, match="--capture"):
        load_fixtures(tmp_path)


def test_capture_writes_fixtures_without_network(tmp_path, monkeypatch):
    from scripts import eval_sub_model

    monkeypatch.setattr(
        eval_sub_model, "_fetch_json",
        lambda url: (
            {"dates": ["2026-07-29"]} if url.endswith("index.json")
            else [{
                "title": "T", "url": "https://example.com/a",
                "source": "Example", "published_at": "2026-07-29",
            }]
        ),
    )
    monkeypatch.setattr(eval_sub_model, "_extract_body", lambda url: "captured body")

    count = eval_sub_model.capture("https://example.com/", limit=1, fixtures_dir=tmp_path)

    assert count == 1
    assert load_fixtures(tmp_path)[0]["body"] == "captured body"


def test_capture_skips_articles_with_empty_bodies(tmp_path, monkeypatch):
    from scripts import eval_sub_model

    monkeypatch.setattr(
        eval_sub_model, "_fetch_json",
        lambda url: (
            {"dates": ["2026-07-29"]} if url.endswith("index.json")
            else [
                {"title": "A", "url": "https://example.com/a", "source": "E", "published_at": "2026-07-29"},
                {"title": "B", "url": "https://example.com/b", "source": "E", "published_at": "2026-07-29"},
            ]
        ),
    )
    monkeypatch.setattr(
        eval_sub_model, "_extract_body",
        lambda url: "" if url.endswith("/a") else "real body",
    )

    count = eval_sub_model.capture("https://example.com/", limit=5, fixtures_dir=tmp_path)

    assert count == 1
    assert load_fixtures(tmp_path)[0]["url"] == "https://example.com/b"
