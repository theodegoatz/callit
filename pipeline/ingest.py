# pipeline/ingest.py — Downloads raw data from sources (Statcast, Retrosheet, etc.)
import os
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _patched_schedule_and_record(season, team):
    """Wrapper around pybaseball.schedule_and_record that handles pandas 3.x issues."""
    from pybaseball import schedule_and_record as _sar
    import numpy as np
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return _sar(season, team)
        except (ValueError, TypeError):
            pass

    import requests
    from io import StringIO
    url = f"https://www.baseball-reference.com/teams/{team}/{season}-schedule-scores.shtml"
    resp = requests.get(url, timeout=30)
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


def download_schedule(season: int = 2024) -> pd.DataFrame:
    """Download the MLB schedule/results for a season via pybaseball."""
    parquet = os.path.join(DATA_DIR, f"schedule_{season}.parquet")
    if os.path.exists(parquet):
        print(f"[ingest] Loading cached schedule for {season}")
        return pd.read_parquet(parquet)

    print(f"[ingest] Downloading schedule for {season} via pybaseball …")
    try:
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
        if not frames:
            raise RuntimeError("Could not download any team schedules")
        combined = pd.concat(frames, ignore_index=True)
        combined.to_parquet(parquet)
        print(f"[ingest] Saved {len(combined)} rows → {parquet}")
        return combined
    except Exception as e:
        print(f"[ingest] pybaseball download failed: {e}")
        print("[ingest] Generating sample schedule data for development …")
        return _generate_sample_schedule(season, parquet)


def _generate_sample_schedule(season: int, parquet: str) -> pd.DataFrame:
    """Generate realistic sample schedule data when pybaseball is unavailable."""
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
            })

    df = pd.DataFrame(rows)
    df.to_parquet(parquet)
    print(f"[ingest] Generated {len(df)} sample games → {parquet}")
    return df


def main():
    ensure_data_dir()
    df = download_schedule(2024)
    print(f"[ingest] Done. {len(df)} total rows.")


if __name__ == "__main__":
    main()
