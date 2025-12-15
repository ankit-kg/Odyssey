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
    args = parser.parse_args()

    config = Config.from_env()
    result = run_scrape(config=config, run_type=args.run_type)

    if result.status != "success":
        sys.stderr.write(result.error_message or "Unknown failure\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


