# pipeline/ingest.py — Downloads raw data from sources (Statcast, Retrosheet, etc.)
import logging
import os
import sys
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

logger = logging.getLogger(__name__)


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def _patched_schedule_and_record(season, team):
    """Wrapper around pybaseball.schedule_and_record that handles pandas 3.x issues."""
    import warnings
    import signal

    class _Timeout(Exception):
        pass

    def _handler(signum, frame):
        raise _Timeout()

    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(15)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from pybaseball import schedule_and_record as _sar
            return _sar(season, team)
    except (ValueError, TypeError):
        from io import StringIO
        import requests
        url = f"https://www.baseball-reference.com/teams/{team}/{season}-schedule-scores.shtml"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        tables = pd.read_html(StringIO(resp.text))
        for tbl in tables:
            if "R" in tbl.columns or "Tm" in tbl.columns:
                tbl = tbl[tbl["Gm#"].apply(lambda x: str(x).isdigit())].copy()
                if "Attendance" in tbl.columns:
                    tbl["Attendance"] = (
                        tbl["Attendance"]
                        .astype(str)
                        .str.replace(r"[^0-9]", "", regex=True)
                    )
                    tbl["Attendance"] = pd.to_numeric(
                        tbl["Attendance"], errors="coerce"
                    )
                return tbl
        raise ValueError("Could not parse schedule table")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def _download_pybaseball_schedule(season: int) -> pd.DataFrame:
    frames = []
    teams = [
        "NYY", "BOS", "TBR", "TOR", "BAL",
        "CLE", "MIN", "DET", "CHW", "KCR",
        "HOU", "SEA", "TEX", "LAA", "OAK",
        "ATL", "NYM", "PHI", "MIA", "WSN",
        "MIL", "CHC", "STL", "CIN", "PIT",
        "LAD", "SDP", "SFG", "ARI", "COL",
    ]
    for team in teams:
        try:
            df = _patched_schedule_and_record(season, team)
            df["team"] = team
            frames.append(df)
            print(f"  ✓ {team}: {len(df)} games")
        except Exception as e:
            print(f"  ✗ {team}: {e}")
    if len(frames) < 5:
        raise RuntimeError(f"Only {len(frames)} teams from pybaseball/BR")
    combined = pd.concat(frames, ignore_index=True)
    if "Gm#" in combined.columns:
        combined = combined[combined["Gm#"].apply(
            lambda x: str(x).replace(".0", "").isdigit()
        )].copy()
    for col in ("R", "RA", "Gm#"):
        if col in combined.columns:
            combined[col] = pd.to_numeric(combined[col], errors="coerce")
    if "Attendance" in combined.columns:
        combined["Attendance"] = pd.to_numeric(
            combined["Attendance"].astype(str).str.replace(r"[^0-9.]", "", regex=True),
            errors="coerce",
        )
    for col in combined.columns:
        if combined[col].dtype == object:
            combined[col] = combined[col].astype(str)
    combined["data_source"] = "pybaseball"
    return combined


def _generate_sample_schedule(season: int) -> pd.DataFrame:
    """Synthetic schedule for local dev only (randomized matchups)."""
    import random
    random.seed(42)

    teams = [
        "NYY", "BOS", "TBR", "TOR", "BAL",
        "CLE", "MIN", "DET", "CHW", "KCR",
        "HOU", "SEA", "TEX", "LAA", "OAK",
        "ATL", "NYM", "PHI", "MIA", "WSN",
        "MIL", "CHC", "STL", "CIN", "PIT",
        "LAD", "SDP", "SFG", "ARI", "COL",
    ]

    rows = []
    game_dates = pd.date_range(f"{season}-03-28", f"{season}-09-29", freq="D")

    game_counter = 0
    for date in game_dates:
        random.shuffle(teams)
        pairs = [(teams[i], teams[i + 1]) for i in range(0, len(teams) - 1, 2)]
        for home, away in pairs:
            home_score = random.randint(0, 12)
            away_score = random.randint(0, 12)
            if home_score == away_score:
                home_score += 1
            game_counter += 1
            rows.append({
                "game_id": f"{season}_{game_counter:05d}",
                "Date": date,
                "home_team": home,
                "away_team": away,
                "R": home_score,
                "RA": away_score,
                "W/L": "W" if home_score > away_score else "L",
                "team": home,
                "data_source": "sample",
            })

    return pd.DataFrame(rows)


def download_schedule(season: int = 2024, *, force_refresh: bool = False) -> pd.DataFrame:
    """
    Download MLB schedule/results. Primary: MLB Stats API. Backup: pybaseball/BR.
    Sample data only when USE_SAMPLE_SCHEDULE=true (and never without explicit opt-in).
    """
    ensure_data_dir()
    parquet = os.path.join(DATA_DIR, f"schedule_{season}.parquet")
    use_sample = _truthy_env("USE_SAMPLE_SCHEDULE")

    if os.path.exists(parquet) and not force_refresh:
        print(f"[ingest] Loading cached schedule for {season}")
        return pd.read_parquet(parquet)

    print(f"[ingest] Downloading schedule for {season} (MLB Stats API) …")
    try:
        from pipeline.mlb_schedule import download_season_dataframe
        df = download_season_dataframe(season)
        df.to_parquet(parquet)
        print(f"[ingest] Saved {len(df)} MLB API rows → {parquet} (data_source=mlb_api)")
        return df
    except Exception as e:
        logger.exception("MLB Stats API schedule download failed: %s", e)
        print(f"[ingest] MLB Stats API failed: {e}")

    print("[ingest] Trying pybaseball / Baseball Reference fallback …")
    try:
        combined = _download_pybaseball_schedule(season)
        combined.to_parquet(parquet)
        print(f"[ingest] Saved {len(combined)} pybaseball rows → {parquet}")
        return combined
    except Exception as e:
        logger.exception("pybaseball schedule download failed: %s", e)
        print(f"[ingest] pybaseball download failed: {e}")

    if use_sample:
        logger.warning(
            "USE_SAMPLE_SCHEDULE=true: writing RANDOM matchup parquet to %s — not real MLB",
            parquet,
        )
        print(
            "[ingest] WARNING: USE_SAMPLE_SCHEDULE=true — generating random sample "
            f"schedule (NOT REAL MLB). Writing → {parquet}"
        )
        df = _generate_sample_schedule(season)
        df.to_parquet(parquet)
        print(f"[ingest] Generated {len(df)} sample games → {parquet}")
        return df

    logger.error(
        "Schedule ingest failed and USE_SAMPLE_SCHEDULE is not enabled. "
        "Refusing to write random sample data. Set USE_SAMPLE_SCHEDULE=true "
        "for local dev only."
    )
    print(
        "[ingest] FATAL: All schedule sources failed and USE_SAMPLE_SCHEDULE is not set.\n"
        "        Real analytics must not use random matchups. Fix network/API access or set\n"
        "        USE_SAMPLE_SCHEDULE=true explicitly for synthetic dev data.",
        file=sys.stderr,
    )
    sys.exit(1)


def main():
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Download MLB schedule parquet")
    parser.add_argument("--season", type=int, default=2024)
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Re-download even if schedule_{season}.parquet exists",
    )
    args = parser.parse_args()
    ensure_data_dir()
    df = download_schedule(args.season, force_refresh=args.force_refresh)
    print(f"[ingest] Done. {len(df)} total rows.")


if __name__ == "__main__":
    main()
