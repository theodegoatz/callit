# pipeline/extract.py — Finds decision moments in game data
import json
import logging
import random
import time

import pandas as pd
from sqlalchemy import text

from pipeline.db import get_engine
from pipeline.mlb_win_probability import (
    fetch_win_probability_plays,
    game_pk_from_game_id,
    iter_decision_rows_from_plays,
)

logger = logging.getLogger(__name__)

DECISION_TYPES = [
    "pitching_change",
    "pinch_hitter",
    "intentional_walk",
    "sacrifice_bunt",
    "stolen_base",
    "defensive_shift",
    "pitchout",
    "mound_visit",
]

DECISION_WEIGHTS = [0.35, 0.20, 0.12, 0.10, 0.08, 0.07, 0.05, 0.03]

REQUEST_SLEEP_SEC = 0.12


def extract_decisions(season: int = 2024):
    """
    Extract decision moments from game data.

    For `games.data_source = mlb_api`, pulls substitution events and team WPA
    from the MLB Stats API `winProbability` feed. For other sources (or if
    no rows are returned), falls back to heuristic synthetic moments so the
    pipeline still runs offline.
    """
    engine = get_engine()

    with engine.connect() as conn:
        games = pd.read_sql(
            text("SELECT * FROM games WHERE season = :s"), conn, params={"s": season}
        )

    if games.empty:
        print("[extract] No games found. Run pipeline/games.py first.")
        return

    print(f"[extract] Processing {len(games)} games for decision extraction …")

    decisions = _extract_from_mlb_win_probability(games)
    if not decisions:
        print(
            "[extract] No MLB winProbability rows; using synthetic decision moments "
            "(heuristic placeholder)."
        )
        decisions = _synthetic_decisions(games, season)
    else:
        print(
            f"[extract] Extracted {len(decisions)} decisions from MLB winProbability "
            "(substitutions / mound visits)."
        )

    df = pd.DataFrame(decisions)

    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM decision_moments WHERE game_id IN "
                "(SELECT game_id FROM games WHERE season = :s)"
            ),
            {"s": season},
        )
        rows = df.to_dict("records")
        for row in rows:
            row["context"] = json.dumps(row["context"])
        if rows:
            conn.execute(
                text(
                    "INSERT INTO decision_moments "
                    "(game_id, inning, half, decision_type, team, description, "
                    " wpa_actual, context) "
                    "VALUES (:game_id, :inning, :half, :decision_type, :team, "
                    " :description, :wpa_actual, CAST(:context AS JSONB))"
                ),
                rows,
            )

    print(f"[extract] Inserted {len(df)} decision moments for season {season}")


def _extract_from_mlb_win_probability(games: pd.DataFrame) -> list[dict]:
    decisions: list[dict] = []
    for _, game in games.iterrows():
        src = str(game.get("data_source") or "").strip().lower()
        if src != "mlb_api":
            continue
        gpk = game_pk_from_game_id(str(game["game_id"]))
        if gpk is None:
            continue
        try:
            plays = fetch_win_probability_plays(gpk)
            rows = list(
                iter_decision_rows_from_plays(
                    plays,
                    game_id=str(game["game_id"]),
                    home_team=str(game["home_team"]),
                    away_team=str(game["away_team"]),
                    home_score=int(game["home_score"]),
                    away_score=int(game["away_score"]),
                )
            )
            decisions.extend(rows)
        except Exception as e:
            logger.warning("winProbability failed for game_pk=%s: %s", gpk, e)
        time.sleep(REQUEST_SLEEP_SEC)
    return decisions


def _synthetic_decisions(games: pd.DataFrame, season: int) -> list[dict]:
    random.seed(season)
    decisions = []
    for _, game in games.iterrows():
        run_diff = abs(int(game["home_score"]) - int(game["away_score"]))
        is_close = run_diff <= 3
        n_decisions = random.randint(4, 10) if is_close else random.randint(2, 6)

        for _ in range(n_decisions):
            inning = random.randint(1, 9)
            half = random.choice(["top", "bottom"])
            dtype = random.choices(DECISION_TYPES, weights=DECISION_WEIGHTS, k=1)[0]
            team = game["away_team"] if half == "top" else game["home_team"]

            leverage = _leverage_index(inning, run_diff, is_close)
            wpa_swing = random.gauss(0, 0.04 * leverage)

            decisions.append({
                "game_id": game["game_id"],
                "inning": inning,
                "half": half,
                "decision_type": dtype,
                "team": team,
                "description": _describe(dtype, inning, half, team),
                "wpa_actual": round(wpa_swing, 5),
                "context": _build_context(inning, half, run_diff, leverage, dtype),
            })
    return decisions


def _leverage_index(inning, run_diff, is_close):
    base = 1.0
    if inning >= 7:
        base *= 1.5
    if inning >= 9:
        base *= 1.3
    if is_close:
        base *= 1.4
    if run_diff == 0:
        base *= 1.5
    return base


def _describe(dtype, inning, half, team):
    half_str = "top" if half == "top" else "bottom"
    templates = {
        "pitching_change": f"{team} makes a pitching change in the {half_str} of inning {inning}",
        "pinch_hitter": f"{team} sends in a pinch hitter in the {half_str} of inning {inning}",
        "intentional_walk": f"{team} issues an intentional walk in the {half_str} of inning {inning}",
        "sacrifice_bunt": f"{team} calls for a sacrifice bunt in the {half_str} of inning {inning}",
        "stolen_base": f"{team} attempts a stolen base in the {half_str} of inning {inning}",
        "defensive_shift": f"{team} employs a defensive shift in the {half_str} of inning {inning}",
        "pitchout": f"{team} calls a pitchout in the {half_str} of inning {inning}",
        "mound_visit": f"{team} makes a mound visit in the {half_str} of inning {inning}",
    }
    return templates.get(dtype, f"{team} decision in inning {inning}")


def _build_context(inning, half, run_diff, leverage, dtype):
    return {
        "inning": inning,
        "half": half,
        "run_differential": run_diff,
        "leverage_index": round(leverage, 2),
        "decision_type": dtype,
        "source": "synthetic",
    }


def main():
    extract_decisions(2024)


if __name__ == "__main__":
    main()
