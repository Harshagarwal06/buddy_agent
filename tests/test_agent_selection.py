from news_buddy import agent, state as seen_state


def test_trusted_ai_sources_bypass_keyword_filter():
    config = {
        "ai_keywords": ["openai"],
        "trusted_ai_sources": ["Trusted AI Feed"],
    }
    items = [
        {
            "source": "Trusted AI Feed",
            "title": "A quiet model systems update",
            "rss_summary": "No configured keyword appears here.",
            "url": "https://example.test/trusted",
        },
        {
            "source": "General News",
            "title": "OpenAI launches a thing",
            "rss_summary": "",
            "url": "https://example.test/keyword",
        },
        {
            "source": "General News",
            "title": "Cloud pricing changes",
            "rss_summary": "",
            "url": "https://example.test/skip",
        },
    ]

    filtered = agent._filter_ai_items(items, config)

    assert [it["url"] for it in filtered] == [
        "https://example.test/trusted",
        "https://example.test/keyword",
    ]


def test_icymi_backfill_only_adds_seen_candidates(monkeypatch, tmp_path):
    db_path = tmp_path / "state.db"
    monkeypatch.setattr(agent, "_DB", db_path)
    seen_state.mark_seen(
        db_path,
        {
            "url": "https://example.test/seen",
            "source": "Trusted AI Feed",
            "title": "Seen article",
        },
    )

    state = {
        "config": {
            "icymi_backfill": True,
            "max_backfill_lookback_hours": 168,
            "backfill_max_items_per_feed": 25,
            "max_items_per_feed": 10,
        },
        "force": False,
        "test_run": False,
        "dry_run": False,
        "verbose": False,
    }
    current = [
        {
            "url": "https://example.test/current",
            "source": "Trusted AI Feed",
            "title": "Current article",
        }
    ]
    candidates = [
        {
            "url": "https://example.test/unseen",
            "source": "Trusted AI Feed",
            "title": "Unseen candidate",
        },
        {
            "url": "https://example.test/seen",
            "source": "Trusted AI Feed",
            "title": "Seen article",
        },
    ]
    monkeypatch.setattr(agent, "_fetch_ai_candidates", lambda *_args: candidates)

    topped_up = agent._top_up_icymi(state, current, target=2)

    assert len(topped_up) == 2
    assert topped_up[1]["url"] == "https://example.test/seen"
    assert topped_up[1]["is_icymi"] is True


def test_icymi_backfill_skips_test_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "_DB", tmp_path / "state.db")
    state = {
        "config": {"icymi_backfill": True},
        "force": False,
        "test_run": True,
        "dry_run": False,
        "verbose": False,
    }
    monkeypatch.setattr(agent, "_fetch_ai_candidates", lambda *_args: [])

    topped_up = agent._top_up_icymi(state, [], target=2)

    assert topped_up == []
