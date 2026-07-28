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
        "importance": 0,  # _article_card clamps the importance label to 1
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
        "image_width": 1184,
        "image_height": 880,
    }

    html = _article_card(item, hero=True)

    assert 'class="article-card card-hero has-image"' in html
    assert 'src="images/visual.webp"' in html
    assert 'alt="A blue model emerging from a geometric circuit."' in html
    assert 'width="1184" height="880"' in html
    assert 'loading="eager"' in html
    assert 'fetchpriority="high"' in html
    assert html.count('href="https://example.test/visual"') == 1
    assert 'target="_blank"' not in html
    assert '<figure class="card-image">' in html
    assert '<time datetime="2026-07-17">Jul 17, 2026</time>' in html


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
    assert '<link rel="icon" href="favicon.svg" type="image/svg+xml">' in html
    assert '<h1 class="mast-name">News Buddy</h1>' in html
    assert "The briefing" in html
    assert 'href="#main-content">Skip to stories</a>' in html
    assert 'aria-label="Use dark theme" aria-pressed="false"' in html
    assert "Jul 28, 2026" in html
    assert 'class="filter-bar"' not in html
    assert "★★★★" not in html
    assert "--color-paper: oklch(" in tokens
    assert "macrostructure: Long Document" in tokens
    assert (tmp_path / "favicon.svg").exists()


def test_single_desk_uses_plain_more_stories_heading(tmp_path):
    items = [
        {
            "title": f"AI story {index}",
            "url": f"https://example.test/{index}",
            "source": "Test Feed",
            "published_at": "2026-07-28",
            "summary": "A concise summary.",
            "tags": ["world"],
            "importance": 3,
        }
        for index in range(6)
    ]

    page = write_html(tmp_path, "2026-07-28", items)
    html = page.read_text(encoding="utf-8")

    assert "<h2>More stories</h2>" in html
    assert "<h2>World</h2>" not in html
    assert 'class="filter-bar"' not in html


def test_multiple_desks_expose_filter_state(tmp_path):
    items = [
        {
            "title": f"Story {tag}",
            "url": f"https://example.test/{tag}",
            "source": "Test Feed",
            "published_at": "2026-07-28",
            "summary": "A concise summary.",
            "tags": [tag],
            "importance": 3,
        }
        for tag in ("research", "policy")
    ]

    page = write_html(tmp_path, "2026-07-28", items)
    html = page.read_text(encoding="utf-8")

    assert 'class="filter-btn active" type="button" data-tag="__all__" aria-pressed="true"' in html
    assert 'id="filter-status" class="sr-only" aria-live="polite"' in html
