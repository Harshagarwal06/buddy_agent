import hashlib

import yaml

from news_buddy import knowledge_base as kb


def _read_frontmatter(path):
    text = path.read_text(encoding="utf-8")
    _, frontmatter, body = text.split("---\n", 2)
    return yaml.safe_load(frontmatter), body


def test_write_article_creates_expected_frontmatter_and_body(monkeypatch, tmp_path):
    monkeypatch.setattr(kb, "_KB_PATH", tmp_path)

    path = kb.write_article(
        url="https://example.test/a",
        title="Model launches",
        summary="A new model launched today. It handles longer contexts.",
        tags=["ai", "product"],
        source="Test Feed",
        published_at="2026-07-17T09:00:00+00:00",
    )

    frontmatter, body = _read_frontmatter(path)
    assert frontmatter == {
        "type": "Article",
        "title": "Model launches",
        "description": "A new model launched today.",
        "resource": "https://example.test/a",
        "tags": ["ai", "product"],
        "timestamp": "2026-07-17T09:00:00+00:00",
        "source": "Test Feed",
    }
    assert "## Summary" in body
    assert "A new model launched today. It handles longer contexts." in body


def test_write_article_description_falls_back_to_full_summary_without_sentence_break(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(kb, "_KB_PATH", tmp_path)

    path = kb.write_article(
        url="https://example.test/b",
        title="Short update",
        summary="No period-space break here",
        tags=[],
        source="Test Feed",
        published_at="2026-07-17T09:00:00+00:00",
    )

    frontmatter, _ = _read_frontmatter(path)
    assert frontmatter["description"] == "No period-space break here"


def test_write_article_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(kb, "_KB_PATH", tmp_path)

    first = kb.write_article(
        url="https://example.test/c",
        title="Original title",
        summary="Original summary.",
        tags=["ai"],
        source="Test Feed",
        published_at="2026-07-17T09:00:00+00:00",
    )
    second = kb.write_article(
        url="https://example.test/c",
        title="Changed title",
        summary="Changed summary.",
        tags=["changed"],
        source="Test Feed",
        published_at="2026-07-18T09:00:00+00:00",
    )

    assert first == second
    frontmatter, _ = _read_frontmatter(first)
    assert frontmatter["title"] == "Original title"


def test_write_article_filename_is_deterministic_per_url(monkeypatch, tmp_path):
    monkeypatch.setattr(kb, "_KB_PATH", tmp_path)

    path = kb.write_article(
        url="https://example.test/d",
        title="A",
        summary="A summary.",
        tags=[],
        source="Test Feed",
        published_at="2026-07-17T09:00:00+00:00",
    )

    expected_name = hashlib.sha256(b"https://example.test/d").hexdigest()[:16] + ".md"
    assert path.name == expected_name
