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

    if "game_id" not in df.columns:
        df["game_id"] = df.apply(
            lambda r: f"{season}_{r.name:05d}", axis=1
        )

    col_map = {}
    for col in df.columns:
        low = col.lower().replace(" ", "_")
        if low in ("date",):
            col_map[col] = "game_date"
        elif low in ("r", "runs", "home_score"):
            col_map[col] = "home_score"
        elif low in ("ra", "runs_against", "away_score"):
            col_map[col] = "away_score"
        elif low in ("home", "home_team", "tm"):
            col_map[col] = "home_team"
        elif low in ("opp", "away_team"):
            col_map[col] = "away_team"
    df = df.rename(columns=col_map)

    needed = ["game_id", "game_date", "home_team", "away_team"]
    for c in needed:
        if c not in df.columns:
            raise KeyError(f"Missing column: {c} (have: {list(df.columns)})")

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

    df = df.drop_duplicates(subset=["game_id"])
    keep = [
        "game_id", "game_date", "home_team", "away_team",
        "home_score", "away_score", "season", "winning_team", "losing_team",
    ]
    df = df[[c for c in keep if c in df.columns]]

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM decision_moments WHERE game_id IN "
                          "(SELECT game_id FROM games WHERE season = :s)"),
                     {"s": season})
        conn.execute(text("DELETE FROM games WHERE season = :s"), {"s": season})

        rows = df.to_dict("records")
        if rows:
            cols = list(rows[0].keys())
            placeholders = ", ".join(f":{c}" for c in cols)
            col_names = ", ".join(cols)
            conn.execute(
                text(f"INSERT INTO games ({col_names}) VALUES ({placeholders})"),
                rows,
            )

    print(f"[games] Inserted {len(df)} games for season {season}")


def main():
    load_games(2024)


if __name__ == "__main__":
    main()
