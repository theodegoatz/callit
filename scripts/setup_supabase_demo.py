#!/usr/bin/env python3
"""
One-shot: ensure schema, ingest MLB schedule, load games, decisions, managers.

Run on your machine (not in a restricted agent VM) with a valid DATABASE_URL in .env
(or unset DATABASE_URL / set CALLIT_USE_SQLITE=1 to use SQLite at data/callit_local.db):

  python3 scripts/setup_supabase_demo.py --season 2024

Then:

  uvicorn api.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import argparse
import sys

_REPO_ROOT = __file__.rsplit("/scripts/", 1)[0]
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap DB for local CallIt demo")
    parser.add_argument("--season", type=int, default=2024)
    parser.add_argument(
        "--force-schedule",
        action="store_true",
        help="Re-download schedule parquet even if cached",
    )
    args = parser.parse_args()

    from sqlalchemy import text

    from pipeline.db import ensure_schema, get_engine
    from pipeline.extract import extract_decisions
    from pipeline.games import load_games
    from pipeline.ingest import download_schedule
    from pipeline.load_managers import load_managers

    print("[setup] Connecting to DATABASE_URL …")
    try:
        engine = get_engine()
        ensure_schema(engine)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        print(
            "[setup] Database connection failed.\n"
            "  • In Supabase: Settings → Database → copy the **URI** (use the "
            "**Session pooler** / transaction pooler if IPv4-only networks).\n"
            "  • Password must be the **database** password, not the anon key.\n"
            f"  • Error: {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[setup] Ingesting schedule for {args.season} …")
    download_schedule(args.season, force_refresh=args.force_schedule)

    print("[setup] Loading games (replaces that season in DB) …")
    load_games(args.season)

    print("[setup] Extracting decision moments …")
    extract_decisions(args.season)

    print("[setup] Loading managers …")
    load_managers(args.season)

    print(
        "[setup] Done.\n"
        "  uvicorn api.main:app --host 127.0.0.1 --port 8000\n"
        "  → http://127.0.0.1:8000/"
    )


if __name__ == "__main__":
    main()
