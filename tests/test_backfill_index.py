from news_buddy.html_writer import _article_card, write_html
from scripts.backfill_index import parse_archive_dates, parse_digest_html


def test_parse_archive_dates_extracts_day_links():
    html = (
        '<a href="2026-07-17.html" class="day-row">...</a>'
        '<a href="2026-07-16.html" class="day-row">...</a>'
    )
    assert parse_archive_dates(html) == ["2026-07-17", "2026-07-16"]


def test_parse_digest_html_extracts_full_record_from_real_markup():
    item = {
        "title": "Model launches",
        "url": "https://example.test/a",
        "source": "Test Feed",
        "published_at": "2026-07-17T09:00:00Z",
        "summary": "A new model launched today.",
        "tags": ["ai", "product"],
        "importance": 4,
    }
    html = f"<html><body>{_article_card(item)}</body></html>"

    records = parse_digest_html(html)

    assert records == [
        {
            "title": "Model launches",
            "url": "https://example.test/a",
            "source": "Test Feed",
            "published_at": "2026-07-17",
            "summary": "A new model launched today.",
            "tags": ["ai", "product"],
            "importance": 4,
        }
    ]


def test_parse_digest_html_handles_missing_summary_and_clamps_importance():
    item = {
        "title": "Minor update",
        "url": "https://example.test/b",
        "source": "Test Feed",
        "published_at": "2026-07-16T09:00:00Z",
        "summary": "",
        "tags": [],
        "importance": 0,  # _article_card clamps this to 1 via _stars()
    }
    html = f"<html><body>{_article_card(item)}</body></html>"

    records = parse_digest_html(html)

    assert records[0]["importance"] == 1
    assert records[0]["summary"] == ""
    assert records[0]["tags"] == []


def test_parse_digest_html_returns_empty_list_for_page_with_no_articles():
    assert parse_digest_html("<html><body>No new articles today.</body></html>") == []


def test_article_card_renders_responsive_image_markup():
    item = {
        "title": "Visual model launch",
        "url": "https://example.test/visual",
        "source": "Test Feed",
        "published_at": "2026-07-17T09:00:00Z",
        "summary": "A visual model launched.",
        "tags": ["ai"],
        "importance": 5,
        "image_url": "images/visual.webp",
        "image_alt": "A blue model emerging from a geometric circuit.",
    }

    html = _article_card(item, hero=True)

    assert 'class="article-card card-hero has-image"' in html
    assert 'src="images/visual.webp"' in html
    assert 'alt="A blue model emerging from a geometric circuit."' in html
    assert 'loading="eager"' in html
    assert 'fetchpriority="high"' in html


def test_digest_uses_shared_editorial_tokens_and_masthead(tmp_path):
    item = {
        "title": "A carefully edited AI story",
        "url": "https://example.test/editorial",
        "source": "Test Feed",
        "published_at": "2026-07-28T09:00:00Z",
        "summary": "A concise summary written for a daily briefing.",
        "tags": ["ai"],
        "importance": 4,
    }

    page = write_html(tmp_path, "2026-07-28", [item])
    html = page.read_text(encoding="utf-8")
    tokens = (tmp_path / "tokens.css").read_text(encoding="utf-8")

    assert '<link rel="stylesheet" href="tokens.css">' in html
    assert '<h1 class="mast-name">News Buddy</h1>' in html
    assert "The briefing" in html
    assert "★★★★" not in html
    assert "--color-paper: oklch(" in tokens
    assert "macrostructure: Long Document" in tokens
