# pipeline/games.py — Processes game-level data and loads into DB
import os
import pandas as pd
from sqlalchemy import text
from pipeline.db import get_engine, ensure_schema

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def _detect_schedule_kind(df: pd.DataFrame) -> str:
    """
    Choose parser for schedule parquet. MLB-normalized rows include game_pk; pybaseball
    uses Tm/Opp; synthetic sample uses home_team + game_id without game_pk.
    """
    cols = set(df.columns)
    if "game_pk" in cols and df["game_pk"].notna().any():
        return "mlb_api"
    if "Tm" in cols and "Opp" in cols:
        return "pybaseball"
    if "data_source" in cols:
        srcs = df["data_source"].dropna().astype(str).unique()
        if len(srcs) == 1 and srcs[0] == "sample":
            return "sample"
    if "home_team" in cols and "game_id" in cols:
        return "sample"
    raise KeyError(
        "Unrecognized schedule format. Columns: "
        f"{list(df.columns)}. Re-run ingest or use MLB-normalized / pybaseball output."
    )


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

    kind = _detect_schedule_kind(df)
    if kind == "mlb_api":
        games = _process_mlb_normalized(df, season)
    elif kind == "pybaseball":
        games = _process_pybaseball_format(df, season)
    elif kind == "sample":
        games = _process_sample_format(df, season)
    else:
        raise KeyError(f"Unknown schedule kind {kind!r}")

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


def _process_mlb_normalized(df, season):
    """Parquet from pipeline.mlb_schedule / MLB Stats API."""
    records = []
    for _, row in df.iterrows():
        gd = row["game_date"]
        if hasattr(gd, "date"):
            gd = gd.date()
        records.append({
            "game_id": str(row["game_id"]),
            "game_date": gd,
            "home_team": str(row["home_team"]),
            "away_team": str(row["away_team"]),
            "home_score": int(row["home_score"]),
            "away_score": int(row["away_score"]),
            "season": int(row.get("season", season)),
            "venue": (None if pd.isna(row.get("venue")) else str(row["venue"])),
            "winning_team": (
                None if pd.isna(row.get("winning_team")) else str(row["winning_team"])
            ),
            "losing_team": (
                None if pd.isna(row.get("losing_team")) else str(row["losing_team"])
            ),
            "data_source": str(row.get("data_source", "mlb_api")),
        })
    return pd.DataFrame(records)


def _process_pybaseball_format(df, season):
    """Process real pybaseball schedule_and_record output."""
    records = []
    seen = set()

    for _, row in df.iterrows():
        tm = str(row.get("Tm", row.get("team", "")))
        opp = str(row.get("Opp", ""))
        if opp in ("nan", "Opp", ""):
            continue
        is_away = str(row.get("Unnamed: 4", "")).strip() == "@"
        runs = int(row.get("R", 0) or 0)
        runs_against = int(row.get("RA", 0) or 0)

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

        if home_score == away_score:
            winning_team, losing_team = None, None
        else:
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
            "venue": None,
            "winning_team": winning_team,
            "losing_team": losing_team,
            "data_source": "pybaseball",
        })

    return pd.DataFrame(records)


def _process_sample_format(df, season):
    """Process sample/generated data format (random matchups)."""
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
    df["venue"] = None
    if "data_source" not in df.columns:
        df["data_source"] = "sample"

    keep = [
        "game_id", "game_date", "home_team", "away_team",
        "home_score", "away_score", "season", "venue",
        "winning_team", "losing_team", "data_source",
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
