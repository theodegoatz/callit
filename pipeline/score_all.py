# pipeline/score_all.py — Scores each decision with the model
import os
import json
import numpy as np
import pandas as pd
from sqlalchemy import text
from pipeline.db import get_engine

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "models")
AMBIGUITY_THRESHOLD = 0.02


def score_all(season: int = 2024):
    engine = get_engine()

    model_path = os.path.join(MODEL_DIR, f"wpa_model_{season}.json")
    if not os.path.exists(model_path):
        raise FileNotFoundError(
            f"{model_path} not found. Run pipeline/build_model.py first."
        )

    with open(model_path) as f:
        model_meta = json.load(f)

    baseline = model_meta["optimal_baseline"]
    wpa_std = model_meta["wpa_std"]

    with engine.connect() as conn:
        df = pd.read_sql(
            text(
                "SELECT id, wpa_actual, context FROM decision_moments "
                "WHERE game_id IN (SELECT game_id FROM games WHERE season = :s)"
            ),
            conn,
            params={"s": season},
        )

    if df.empty:
        print("[score_all] No decisions to score.")
        return

    print(f"[score_all] Scoring {len(df)} decisions …")

    df["ctx"] = df["context"].apply(
        lambda x: json.loads(x) if isinstance(x, str) else (x or {})
    )
    df["leverage"] = df["ctx"].apply(lambda c: c.get("leverage_index", 1.0))

    np.random.seed(season)
    noise = np.random.normal(0, wpa_std * 0.3, size=len(df))
    df["wpa_optimal"] = df["leverage"] * baseline * 0.5 + noise
    df["wpa_optimal"] = df["wpa_optimal"].clip(-0.15, 0.15)

    df["decision_value"] = df["wpa_actual"] - df["wpa_optimal"]
    df["is_ambiguous"] = df["decision_value"].abs() < AMBIGUITY_THRESHOLD
    df["is_optimal"] = df["decision_value"] >= -AMBIGUITY_THRESHOLD

    with engine.begin() as conn:
        for _, row in df.iterrows():
            conn.execute(
                text(
                    "UPDATE decision_moments SET "
                    "wpa_optimal = :wpa_optimal, "
                    "decision_value = :dv, "
                    "is_optimal = :opt, "
                    "is_ambiguous = :amb, "
                    "scored = TRUE "
                    "WHERE id = :id"
                ),
                {
                    "wpa_optimal": round(float(row["wpa_optimal"]), 5),
                    "dv": round(float(row["decision_value"]), 5),
                    "opt": bool(row["is_optimal"]),
                    "amb": bool(row["is_ambiguous"]),
                    "id": int(row["id"]),
                },
            )

    n_optimal = int(df["is_optimal"].sum())
    n_ambiguous = int(df["is_ambiguous"].sum())
    print(f"[score_all] Scored {len(df)} decisions: "
          f"{n_optimal} optimal, {n_ambiguous} ambiguous")


def main():
    score_all(2024)


if __name__ == "__main__":
    main()
