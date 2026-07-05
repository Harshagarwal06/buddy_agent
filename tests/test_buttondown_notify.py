"""Tests for news_buddy.buttondown_notify."""

import httpx

from news_buddy import buttondown_notify


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def test_send_digest_success(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _FakeResponse(201)

    monkeypatch.setattr(httpx, "post", fake_post)

    ok = buttondown_notify.send_digest(
        api_key="secret-key",
        digest_markdown="## Top Stories\n\n- something happened",
        date_str="2026-07-04",
        item_count=7,
    )

    assert ok is True
    assert captured["url"] == "https://api.buttondown.com/v1/emails"
    assert captured["headers"] == {
        "Authorization": "Token secret-key",
        "X-Buttondown-Live-Dangerously": "true",
    }
    assert captured["json"]["subject"] == "🗞️ News Buddy — 2026-07-04 (7 stories)"
    assert captured["json"]["body"] == "## Top Stories\n\n- something happened"
    assert captured["json"]["status"] == "about_to_send"


def test_send_digest_http_error_returns_false(monkeypatch):
    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **kw: _FakeResponse(401, "bad token"),
    )
    ok = buttondown_notify.send_digest("bad", "body", "2026-07-04", 1)
    assert ok is False


def test_send_digest_network_error_returns_false(monkeypatch):
    def fake_post(*a, **kw):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx, "post", fake_post)
    ok = buttondown_notify.send_digest("key", "body", "2026-07-04", 1)
    assert ok is False
