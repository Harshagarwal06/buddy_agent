import httpx
import pytest

from news_buddy_mcp.index_client import ArchiveIndexClient


def _client_with_responses(responses: dict[str, httpx.Response]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.lstrip("/")
        if path in responses:
            return responses[path]
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_manifest_returns_dates_from_index_json():
    client = _client_with_responses({
        "index.json": httpx.Response(200, json={"dates": ["2026-07-17", "2026-07-16"]}),
    })
    archive = ArchiveIndexClient("https://example.test", client=client)

    dates, stale = archive.manifest()

    assert dates == ["2026-07-17", "2026-07-16"]
    assert stale is False


def test_manifest_serves_stale_cache_on_fetch_failure():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={"dates": ["2026-07-17"]})
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    archive = ArchiveIndexClient("https://example.test", ttl_seconds=0, client=client)

    first_dates, first_stale = archive.manifest()
    second_dates, second_stale = archive.manifest()

    assert first_dates == ["2026-07-17"]
    assert first_stale is False
    assert second_dates == ["2026-07-17"]
    assert second_stale is True


def test_manifest_raises_when_no_cache_and_fetch_fails():
    client = _client_with_responses({})  # everything 404s

    archive = ArchiveIndexClient("https://example.test", client=client)

    with pytest.raises(httpx.HTTPStatusError):
        archive.manifest()


def test_day_returns_none_for_missing_date():
    client = _client_with_responses({
        "index.json": httpx.Response(200, json={"dates": []}),
    })
    archive = ArchiveIndexClient("https://example.test", client=client)

    records, stale = archive.day("2026-01-01")

    assert records is None
    assert stale is False


def test_day_returns_records_for_existing_date():
    client = _client_with_responses({
        "2026-07-17.json": httpx.Response(200, json=[{"title": "X"}]),
    })
    archive = ArchiveIndexClient("https://example.test", client=client)

    records, stale = archive.day("2026-07-17")

    assert records == [{"title": "X"}]
    assert stale is False
