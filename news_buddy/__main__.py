"""CLI entry point: python -m news_buddy run [options]"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv


def _load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _run(args: argparse.Namespace) -> None:
    config = _load_config(args.config)
    date_str = args.date or __import__("datetime").date.today().isoformat()

    # Telegram credentials (optional — skip silently if not set)
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat  = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    notifications_enabled = not args.dry_run and not args.test_run
    use_tg   = bool(tg_token and tg_chat) and notifications_enabled

    from news_buddy.agent import run_pipeline

    t_start = time.monotonic()
    result = run_pipeline(
        config,
        date_str=date_str,
        dry_run=args.dry_run,
        force=args.force,
        test_run=args.test_run,
        verbose=args.verbose,
    )
    duration_secs = time.monotonic() - t_start

    # Gemini 2.5 Flash pay-as-you-go rate: $0.15 / 1M input tokens (blended estimate)
    tokens = result.get("total_tokens", 0)
    est_cost_usd = (tokens / 1_000_000) * 0.15

    # ── Telegram notification ────────────────────────────────────────────────
    has_articles = result["item_count"] > 0
    tg_sent: bool | None = None
    if use_tg:
        from news_buddy.telegram_notify import send_digest, send_error_alert
        if result["error"]:
            tg_sent = send_error_alert(tg_token, tg_chat, result["error"], date_str)
        elif has_articles:
            tg_sent = send_digest(tg_token, tg_chat, result["digest"], date_str,
                                  result["item_count"], duration_secs, tokens, est_cost_usd)

    # ── Slack notification ───────────────────────────────────────────────────
    slack_url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    use_slack = bool(slack_url) and notifications_enabled
    slack_sent: bool | None = None
    if use_slack:
        from news_buddy import slack_notify
        if result["error"]:
            slack_sent = slack_notify.send_error_alert(slack_url, result["error"], date_str)
        elif has_articles:
            slack_sent = slack_notify.send_digest(slack_url, result["digest"], date_str,
                                                  result["item_count"], duration_secs, tokens, est_cost_usd)

    # ── Buttondown email (subscriber list) ───────────────────────────────────
    bd_key = os.getenv("BUTTONDOWN_API_KEY", "").strip()
    use_bd = bool(bd_key) and notifications_enabled
    bd_sent: bool | None = None
    if use_bd and not result["error"] and has_articles:
        from news_buddy import buttondown_notify
        bd_sent = buttondown_notify.send_digest(bd_key, result["digest"], date_str,
                                                result["item_count"])

    # ── Terminal output ──────────────────────────────────────────────────────
    if result["error"]:
        print(f"\n❌ Pipeline failed: {result['error']}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print(result["digest"])
    else:
        print(f"✅ Digest written → {result['output_path']}")
        if args.test_run:
            print("   Test run: dedup state, RAG cache, and notifications were not updated")
        rubric_fails = result.get("rubric_failures", 0)
        print(f"   Articles: {result['item_count']}  |  "
              f"Tokens: {tokens:,}  |  "
              f"Est. cost: ${est_cost_usd:.4f}  |  "
              f"Duration: {duration_secs:.1f}s  |  "
              f"Rubric failures: {rubric_fails}")
        skip_reason = _notification_skip_reason(args, result)
        tg_status = _status(tg_sent, bool(tg_token and tg_chat), skip_reason)
        slack_status = _status(slack_sent, bool(slack_url), skip_reason)
        bd_status = _status(bd_sent, bool(bd_key), skip_reason)
        print(f"   Telegram: {tg_status}  |  Slack: {slack_status}  |  Email: {bd_status}")
        print(f"\n--- Preview (first 20 lines) ---")
        lines = result["digest"].splitlines()
        print("\n".join(lines[:20]))
        if len(lines) > 20:
            print(f"… ({len(lines) - 20} more lines)")


def _notification_skip_reason(args: argparse.Namespace, result: dict) -> str | None:
    if args.test_run:
        return "test run"
    if not result["error"] and result["item_count"] == 0:
        return "0 articles"
    return None


def _status(sent: bool | None, configured: bool, skip_reason: str | None = None) -> str:
    if not configured:
        return "not configured"
    if sent is True:
        return "sent ✅"
    if sent is False:
        return "failed ❌"
    if skip_reason:
        return f"skipped ({skip_reason})"
    return "skipped"


def main() -> None:
    load_dotenv()

    # Set up OTel/Phoenix tracing BEFORE the pipeline's LangChain models are built.
    from news_buddy.observability import setup_tracing
    setup_tracing()

    parser = argparse.ArgumentParser(prog="news-buddy")
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Run the daily curation job")
    run_p.add_argument(
        "--config",
        default=str(Path(__file__).parent.parent / "config.yaml"),
    )
    run_p.add_argument("--date", default=None, help="Override today's date (YYYY-MM-DD)")
    run_p.add_argument("--dry-run", action="store_true", help="No network or file calls")
    run_p.add_argument("--force", action="store_true", help="Skip deduplication")
    run_p.add_argument(
        "--test-run",
        action="store_true",
        help="Run live fetch/summarization without marking articles seen or sending notifications",
    )
    run_p.add_argument("--verbose", action="store_true", help="Log progress to stderr")

    args = parser.parse_args()

    if args.command == "run":
        _run(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
