from news_buddy_mcp.server import _get_digest, _list_digests, _search_articles


class _FakeArchive:
    def __init__(self, manifest_dates, days, manifest_stale=False, day_stale=False, fail_manifest=False, fail_day_dates=None):
        self._dates = manifest_dates
        self._days = days
        self._manifest_stale = manifest_stale
        self._day_stale = day_stale
        self._fail_manifest = fail_manifest
        self._fail_day_dates = fail_day_dates or []

    def manifest(self):
        if self._fail_manifest:
            raise RuntimeError("manifest fetch failed")
        return self._dates, self._manifest_stale

    def day(self, date_str):
        if date_str in self._fail_day_dates:
            raise RuntimeError(f"day fetch failed for {date_str}")
        if date_str not in self._days:
            return None, False
        return self._days[date_str], self._day_stale


_DAY_A = [
    {"title": "Model launches", "url": "https://example.test/a", "source": "Test Feed",
     "published_at": "2026-07-17", "summary": "A new model launched.", "tags": ["ai"], "importance": 5},
    {"title": "Weather update", "url": "https://example.test/b", "source": "Other Feed",
     "published_at": "2026-07-17", "summary": "Sunny today.", "tags": ["world"], "importance": 2},
]


def test_search_articles_matches_title_and_summary_case_insensitively():
    archive = _FakeArchive(["2026-07-17"], {"2026-07-17": _DAY_A})

    result = _search_articles(archive, "model launches", None, None, None, 20)

    assert result["count"] == 1
    assert result["results"][0]["url"] == "https://example.test/a"


def test_search_articles_filters_by_source():
    archive = _FakeArchive(["2026-07-17"], {"2026-07-17": _DAY_A})

    result = _search_articles(archive, "", "Other Feed", None, None, 20)

    assert result["count"] == 1
    assert result["results"][0]["url"] == "https://example.test/b"


def test_search_articles_filters_by_date_range():
    days = {"2026-07-16": _DAY_A, "2026-07-17": _DAY_A}
    archive = _FakeArchive(["2026-07-17", "2026-07-16"], days)

    result = _search_articles(archive, "", None, "2026-07-17", "2026-07-17", 20)

    assert result["count"] == 2
    assert all(r["date"] == "2026-07-17" for r in result["results"])


def test_search_articles_returns_error_when_manifest_fetch_fails():
    archive = _FakeArchive([], {}, fail_manifest=True)

    result = _search_articles(archive, "model", None, None, None, 20)

    assert "error" in result


def test_get_digest_returns_articles_for_known_date():
    archive = _FakeArchive(["2026-07-17"], {"2026-07-17": _DAY_A})

    result = _get_digest(archive, "2026-07-17")

    assert result["count"] == 2
    assert result["articles"] == _DAY_A


def test_get_digest_returns_explicit_error_for_unknown_date():
    archive = _FakeArchive(["2026-07-17"], {"2026-07-17": _DAY_A})

    result = _get_digest(archive, "1999-01-01")

    assert result == {"error": "no digest for 1999-01-01"}


def test_list_digests_returns_counts_per_date():
    archive = _FakeArchive(["2026-07-17", "2026-07-16"], {"2026-07-17": _DAY_A, "2026-07-16": []})

    result = _list_digests(archive, 30)

    assert result["digests"] == [
        {"date": "2026-07-17", "article_count": 2},
        {"date": "2026-07-16", "article_count": 0},
    ]


def test_get_digest_returns_error_when_day_fetch_fails():
    archive = _FakeArchive(["2026-07-17"], {"2026-07-17": _DAY_A}, fail_day_dates=["2026-07-17"])

    result = _get_digest(archive, "2026-07-17")

    assert "error" in result
    assert "could not load digest for 2026-07-17" in result["error"]


def test_list_digests_returns_error_when_manifest_fetch_fails():
    archive = _FakeArchive([], {}, fail_manifest=True)

    result = _list_digests(archive, 30)

    assert "error" in result
    assert "could not load archive manifest" in result["error"]


def test_list_digests_skips_dates_when_day_fetch_fails():
    archive = _FakeArchive(
        ["2026-07-17", "2026-07-16", "2026-07-15"],
        {"2026-07-17": _DAY_A, "2026-07-16": [], "2026-07-15": _DAY_A},
        fail_day_dates=["2026-07-16"],
    )

    result = _list_digests(archive, 30)

    assert result["digests"] == [
        {"date": "2026-07-17", "article_count": 2},
        {"date": "2026-07-16", "article_count": 0},
        {"date": "2026-07-15", "article_count": 2},
    ]
