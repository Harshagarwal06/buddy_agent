from argparse import Namespace

from news_buddy.__main__ import _notification_skip_reason, _status


def test_empty_success_skips_configured_notifications():
    args = Namespace(test_run=False)
    result = {"error": None, "item_count": 0}

    assert _notification_skip_reason(args, result) == "0 articles"
    assert _status(None, configured=True, skip_reason="0 articles") == "skipped (0 articles)"


def test_test_run_skip_reason_takes_precedence():
    args = Namespace(test_run=True)
    result = {"error": None, "item_count": 5}

    assert _notification_skip_reason(args, result) == "test run"
    assert _status(None, configured=True, skip_reason="test run") == "skipped (test run)"


def test_error_does_not_get_empty_skip_reason():
    args = Namespace(test_run=False)
    result = {"error": "RuntimeError: boom", "item_count": 0}

    assert _notification_skip_reason(args, result) is None
