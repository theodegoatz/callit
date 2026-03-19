#!/usr/bin/env python3
"""
Parquet + (optional) DB/API checks for MLB schedule ingest.

Usage:
  python3 scripts/verify_schedule.py --season 2024
  python3 scripts/verify_schedule.py --season 2024 --parquet data/schedule_2024.parquet --api-smoke
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

# Repo root on path
_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _fail(msg: str) -> None:
    print(f"VERIFY FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def verify_parquet(path: str, season: int) -> None:
    import pandas as pd
    from pipeline.mlb_schedule import SPOTCHECK_GAMES_2024

    if not os.path.isfile(path):
        _fail(f"Parquet not found: {path}")

    df = pd.read_parquet(path)
    print(f"[verify] Loaded {len(df)} rows from {path}")

    src = None
    if "data_source" in df.columns:
        srcs = df["data_source"].dropna().astype(str).unique().tolist()
        if len(srcs) != 1:
            _fail(f"Mixed or empty data_source values: {srcs}")
        src = srcs[0]
        print(f"[verify] data_source={src}")

    if src == "mlb_api" or ("game_pk" in df.columns and df["game_pk"].notna().any()):
        n = len(df)
        if n < 2300 or n > 2550:
            _fail(f"MLB row count {n} outside plausible range [2300, 2550]")

        dates = pd.to_datetime(df["game_date"]).dt.year
        bad_year = (dates != season).sum()
        if bad_year:
            _fail(f"{bad_year} rows have game_date not in season {season}")

        # duplicate (game_date, home, away) with same game_pk should not happen
        if df["game_pk"].duplicated().any():
            dup_ids = df.loc[df["game_pk"].duplicated(), "game_pk"].tolist()
            _fail(f"Duplicate game_pk values: {dup_ids[:15]}")

        for game_pk, gd, home, away, hs, aw in SPOTCHECK_GAMES_2024:
            row = df.loc[df["game_pk"] == game_pk]
            if row.empty:
                _fail(f"Spot-check gamePk {game_pk} missing from parquet")
            r = row.iloc[0]
            rdate = r["game_date"]
            if hasattr(rdate, "date"):
                rdate = rdate.date()
            elif isinstance(rdate, str):
                from datetime import datetime

                rdate = datetime.strptime(rdate[:10], "%Y-%m-%d").date()
            from datetime import datetime as dt

            exp = dt.strptime(gd, "%Y-%m-%d").date()
            if str(r["home_team"]) != home or str(r["away_team"]) != away:
                _fail(
                    f"Spot-check {game_pk} teams: got {r['home_team']} vs {r['away_team']}, "
                    f"expected {home} vs {away}"
                )
            if rdate != exp:
                _fail(f"Spot-check {game_pk} date: got {rdate}, expected {exp}")
            if int(r["home_score"]) != hs or int(r["away_score"]) != aw:
                _fail(
                    f"Spot-check {game_pk} scores: got {r['home_score']}-{r['away_score']}, "
                    f"expected {hs}-{aw}"
                )

        print("[verify] MLB parquet sanity + spot checks OK")
        return

    if src == "sample":
        _fail(
            "Parquet is data_source=sample (random matchups). "
            "Regenerate without USE_SAMPLE_SCHEDULE for real MLB verification."
        )

    if src == "pybaseball":
        print(
            "[verify] pybaseball format detected — skipping MLB-specific row-count "
            "and spot checks. Run ingest with MLB API for full verification."
        )
        return

    _fail(
        f"Cannot verify unknown format (data_source={src!r}). "
        f"Columns: {list(df.columns)}"
    )


def verify_api_smoke(season: int) -> None:
    if not os.getenv("DATABASE_URL"):
        print("[verify] Skipping API smoke (no DATABASE_URL)")
        return

    from fastapi.testclient import TestClient
    from api.main import app

    with TestClient(app) as client:
        r = client.get("/health")
        if r.status_code != 200:
            _fail(f"GET /health -> {r.status_code}")
        r2 = client.get("/")
        if r2.status_code != 200:
            _fail(f"GET / -> {r.status_code}")

    from pipeline.db import get_engine
    from sqlalchemy import text

    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT game_id, game_date, home_team, away_team "
                "FROM games WHERE season = :s AND game_id = :gid"
            ),
            {"s": season, "gid": f"{season}_747065"},
        ).mappings().first()

    if not row:
        print(
            "[verify] Optional SQL spot-check skipped (game 747065 not in DB — "
            "run load_games after MLB ingest)"
        )
        return

    if str(row["home_team"]) != "ATL" or str(row["away_team"]) != "KCR":
        _fail(
            f"DB spot-check ATL/KCR Sep 2024: got {row['home_team']} vs {row['away_team']}"
        )
    print("[verify] API + DB spot check OK")


def main() -> None:
    p = argparse.ArgumentParser(description="Verify schedule parquet and optional API/DB")
    p.add_argument("--season", type=int, default=2024)
    p.add_argument(
        "--parquet",
        default=None,
        help="Path to schedule parquet (default: data/schedule_{season}.parquet)",
    )
    p.add_argument(
        "--api-smoke",
        action="store_true",
        help="FastAPI /health and / plus optional DB game spot-check (needs DATABASE_URL)",
    )
    args = p.parse_args()
    pq = args.parquet or os.path.join(_ROOT, "data", f"schedule_{args.season}.parquet")
    verify_parquet(pq, args.season)
    if args.api_smoke:
        verify_api_smoke(args.season)
    print("[verify] All checks passed.")


if __name__ == "__main__":
    main()
