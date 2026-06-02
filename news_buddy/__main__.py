"""CLI entry point: python -m news_buddy run [options]"""

from __future__ import annotations

import argparse
import os
import sys
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
    use_tg   = bool(tg_token and tg_chat) and not args.dry_run

    from news_buddy.agent import run_pipeline

    result = run_pipeline(
        config,
        date_str=date_str,
        dry_run=args.dry_run,
        force=args.force,
        verbose=args.verbose,
    )

    # ── Telegram notification ────────────────────────────────────────────────
    if use_tg:
        from news_buddy.telegram_notify import send_digest, send_error_alert
        if result["error"]:
            send_error_alert(tg_token, tg_chat, result["error"], date_str)
        else:
            send_digest(tg_token, tg_chat, result["digest"], date_str, result["item_count"])

    # ── Terminal output ──────────────────────────────────────────────────────
    if result["error"]:
        print(f"\n❌ Pipeline failed: {result['error']}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print(result["digest"])
    else:
        print(f"✅ Digest written → {result['output_path']}")
        print(f"   Articles summarized: {result['item_count']}")
        tg_status = "sent to Telegram ✅" if use_tg else "Telegram not configured"
        print(f"   Notification: {tg_status}")
        print(f"\n--- Preview (first 20 lines) ---")
        lines = result["digest"].splitlines()
        print("\n".join(lines[:20]))
        if len(lines) > 20:
            print(f"… ({len(lines) - 20} more lines)")


def main() -> None:
    load_dotenv()

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
    run_p.add_argument("--verbose", action="store_true", help="Log progress to stderr")

    args = parser.parse_args()

    if args.command == "run":
        _run(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
