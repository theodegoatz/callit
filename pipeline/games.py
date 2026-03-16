# pipeline/games.py — Processes game-level data and loads into DB
import os
import pandas as pd
from sqlalchemy import text
from pipeline.db import get_engine, ensure_schema

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def load_games(season: int = 2024):
    engine = get_engine()
    ensure_schema(engine)

    parquet = os.path.join(DATA_DIR, f"schedule_{season}.parquet")
    if not os.path.exists(parquet):
        raise FileNotFoundError(
            f"{parquet} not found. Run pipeline/ingest.py first."
        )

    df = pd.read_parquet(parquet)
    print(f"[games] Loaded {len(df)} rows from {parquet}")

    if "game_id" in df.columns:
        games = _process_sample_format(df, season)
    elif "Tm" in df.columns and "Opp" in df.columns:
        games = _process_pybaseball_format(df, season)
    else:
        raise KeyError(f"Unrecognized format. Columns: {list(df.columns)}")

    games = games.drop_duplicates(subset=["game_id"])
    print(f"[games] {len(games)} unique games after dedup")

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM decision_moments WHERE game_id IN "
                 "(SELECT game_id FROM games WHERE season = :s)"),
            {"s": season},
        )
        conn.execute(text("DELETE FROM games WHERE season = :s"), {"s": season})

        rows = games.to_dict("records")
        if rows:
            cols = list(rows[0].keys())
            placeholders = ", ".join(f":{c}" for c in cols)
            col_names = ", ".join(cols)
            conn.execute(
                text(f"INSERT INTO games ({col_names}) VALUES ({placeholders})"),
                rows,
            )

    print(f"[games] Inserted {len(games)} games for season {season}")


def _process_pybaseball_format(df, season):
    """Process real pybaseball schedule_and_record output."""
    records = []
    seen = set()

    for _, row in df.iterrows():
        tm = str(row.get("Tm", row.get("team", "")))
        opp = str(row.get("Opp", ""))
        is_away = str(row.get("Unnamed: 4", "")).strip() == "@"
        runs = int(row.get("R", 0))
        runs_against = int(row.get("RA", 0))

        if is_away:
            home_team, away_team = opp, tm
            home_score, away_score = runs_against, runs
        else:
            home_team, away_team = tm, opp
            home_score, away_score = runs, runs_against

        date_str = str(row.get("Date", ""))
        game_date = _parse_date(date_str, season)

        matchup = tuple(sorted([home_team, away_team]))
        game_key = (game_date, matchup)
        if game_key in seen:
            continue
        seen.add(game_key)

        game_id = f"{season}_{game_date}_{home_team}_{away_team}"

        winning_team = home_team if home_score > away_score else away_team
        losing_team = away_team if home_score > away_score else home_team

        records.append({
            "game_id": game_id,
            "game_date": game_date,
            "home_team": home_team,
            "away_team": away_team,
            "home_score": home_score,
            "away_score": away_score,
            "season": season,
            "winning_team": winning_team,
            "losing_team": losing_team,
        })

    return pd.DataFrame(records)


def _process_sample_format(df, season):
    """Process sample/generated data format."""
    col_map = {}
    for col in df.columns:
        low = col.lower().replace(" ", "_")
        if low in ("date",):
            col_map[col] = "game_date"
        elif low in ("r", "runs", "home_score"):
            col_map[col] = "home_score"
        elif low in ("ra", "runs_against", "away_score"):
            col_map[col] = "away_score"
    df = df.rename(columns=col_map)

    if "game_date" in df.columns:
        df["game_date"] = pd.to_datetime(df["game_date"]).dt.date

    df["season"] = season
    if "home_score" not in df.columns:
        df["home_score"] = 0
    if "away_score" not in df.columns:
        df["away_score"] = 0
    df["home_score"] = pd.to_numeric(df["home_score"], errors="coerce").fillna(0).astype(int)
    df["away_score"] = pd.to_numeric(df["away_score"], errors="coerce").fillna(0).astype(int)

    df["winning_team"] = df.apply(
        lambda r: r["home_team"] if r["home_score"] > r["away_score"] else r["away_team"],
        axis=1,
    )
    df["losing_team"] = df.apply(
        lambda r: r["away_team"] if r["home_score"] > r["away_score"] else r["home_team"],
        axis=1,
    )

    keep = [
        "game_id", "game_date", "home_team", "away_team",
        "home_score", "away_score", "season", "winning_team", "losing_team",
    ]
    return df[[c for c in keep if c in df.columns]]


def _parse_date(date_str, season):
    """Parse pybaseball date format like 'Thursday, Mar 28' or 'Friday, Mar 29 (1)'."""
    import re
    date_str = re.sub(r"\s*\(\d+\)\s*$", "", date_str).strip()
    parts = date_str.split(",")
    if len(parts) >= 2:
        date_part = parts[-1].strip()
    else:
        date_part = date_str.strip()
    try:
        parsed = pd.to_datetime(f"{date_part} {season}", format="%b %d %Y")
        return parsed.date()
    except Exception:
        try:
            parsed = pd.to_datetime(date_str)
            return parsed.date()
        except Exception:
            import datetime
            return datetime.date(season, 1, 1)


def main():
    load_games(2024)


if __name__ == "__main__":
    main()
