# pipeline/build_model.py — Builds WPA-based model for scoring decisions
import os
import json
import numpy as np
import pandas as pd
from sqlalchemy import text
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from pipeline.db import get_engine

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "models")


def build_model(season: int = 2024):
    """
    Build a simple WPA-based decision scoring model.

    The model learns the relationship between game context
    (inning, leverage, run differential) and decision quality.
    It estimates the optimal WPA for a given context, which is
    then used to evaluate whether a manager's actual decision
    was close to optimal.
    """
    os.makedirs(MODEL_DIR, exist_ok=True)
    engine = get_engine()

    with engine.connect() as conn:
        df = pd.read_sql(
            text(
                "SELECT dm.*, g.home_score, g.away_score, g.winning_team "
                "FROM decision_moments dm "
                "JOIN games g ON dm.game_id = g.game_id "
                "WHERE g.season = :s"
            ),
            conn,
            params={"s": season},
        )

    if df.empty:
        print("[build_model] No decision data found.")
        return

    print(f"[build_model] Training on {len(df)} decisions …")

    df["ctx"] = df["context"].apply(
        lambda x: json.loads(x) if isinstance(x, str) else (x or {})
    )
    df["leverage"] = df["ctx"].apply(lambda c: c.get("leverage_index", 1.0))
    df["run_diff"] = df["ctx"].apply(lambda c: c.get("run_differential", 0))
    df["late_inning"] = (df["inning"] >= 7).astype(int)

    features = df[["inning", "leverage", "run_diff", "late_inning"]].values
    wpa = df["wpa_actual"].values

    scaler = StandardScaler()
    X = scaler.fit_transform(features)

    wpa_positive = (wpa > 0).astype(int)
    model = LogisticRegression(max_iter=1000)
    model.fit(X, wpa_positive)

    probs = model.predict_proba(X)[:, 1]
    df["wpa_optimal_est"] = probs * df["leverage"] * 0.05

    model_meta = {
        "season": season,
        "n_decisions": len(df),
        "features": ["inning", "leverage", "run_diff", "late_inning"],
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(),
        "coef": model.coef_.tolist(),
        "intercept": model.intercept_.tolist(),
        "wpa_mean": float(np.mean(wpa)),
        "wpa_std": float(np.std(wpa)),
        "optimal_baseline": float(np.percentile(np.abs(wpa), 75)),
    }

    model_path = os.path.join(MODEL_DIR, f"wpa_model_{season}.json")
    with open(model_path, "w") as f:
        json.dump(model_meta, f, indent=2)

    print(f"[build_model] Model saved → {model_path}")
    print(f"[build_model] WPA mean={model_meta['wpa_mean']:.4f}, "
          f"std={model_meta['wpa_std']:.4f}, "
          f"optimal_baseline={model_meta['optimal_baseline']:.4f}")


def main():
    build_model(2024)


if __name__ == "__main__":
    main()
