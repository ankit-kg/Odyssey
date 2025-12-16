from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from .config import Config
from .runner import run_scrape


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Odyssey Reddit comment scraper → Supabase")
    parser.add_argument("--run-type", choices=["initial", "scheduled"], required=True)
    parser.add_argument("--dry-run", action="store_true", help="Scrape Reddit but do not write to Supabase")
    parser.add_argument(
        "--thread-limit",
        type=int,
        default=None,
        help="Optional: only scan the first N threads (useful for testing; do not use for real initial scrape)",
    )
    args = parser.parse_args()

    config = Config.from_env(require_supabase=not args.dry_run)
    result = run_scrape(
        config=config, run_type=args.run_type, dry_run=bool(args.dry_run), thread_limit=args.thread_limit
    )

    if result.status != "success":
        sys.stderr.write(result.error_message or "Unknown failure\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


