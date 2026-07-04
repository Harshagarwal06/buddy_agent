"""Tests for the Buttondown signup form embed in the archive page."""

from pathlib import Path

from news_buddy.archive_writer import write_archive


def _make_digest(tmp_path: Path) -> None:
    (tmp_path / "2026-07-04.html").write_text(
        '<html><body>3 articles <span data-tag="ai"></span></body></html>',
        encoding="utf-8",
    )


def test_signup_form_rendered_when_username_set(tmp_path, monkeypatch):
    monkeypatch.setenv("BUTTONDOWN_USERNAME", "newsbuddy")
    _make_digest(tmp_path)

    index = write_archive(tmp_path)
    html = index.read_text(encoding="utf-8")

    assert "https://buttondown.com/api/emails/embed-subscribe/newsbuddy" in html
    assert 'name="email"' in html
    assert "signup-box" in html


def test_signup_form_omitted_when_username_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("BUTTONDOWN_USERNAME", raising=False)
    _make_digest(tmp_path)

    index = write_archive(tmp_path)
    html = index.read_text(encoding="utf-8")

    assert "embed-subscribe" not in html
    assert "signup-box" not in html
