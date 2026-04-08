# pipeline/build_model.py — Builds WPA regression model for scoring decisions
import json
import os

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sqlalchemy import text

from pipeline.db import get_engine

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "models")

NUMERIC_FEATURES = ["inning", "leverage", "run_diff", "late_inning"]


def _parse_context_series(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ctx"] = out["context"].apply(
        lambda x: json.loads(x) if isinstance(x, str) else (x or {})
    )
    out["leverage"] = out["ctx"].apply(lambda c: float(c.get("leverage_index", 1.0)))
    out["run_diff"] = out["ctx"].apply(lambda c: float(c.get("run_differential", 0)))
    out["late_inning"] = (out["inning"] >= 7).astype(int)
    return out


def _dummy_columns(decision_types: pd.Series) -> tuple[pd.DataFrame, list[str]]:
    dummies = pd.get_dummies(
        decision_types.fillna("unknown").astype(str),
        prefix="dt",
        dtype=float,
    )
    cols = sorted(dummies.columns.tolist())
    dummies = dummies.reindex(columns=cols, fill_value=0.0)
    return dummies, cols


def build_design_matrix(
    df: pd.DataFrame,
    *,
    scaler: StandardScaler | None = None,
    dummy_cols: list[str] | None = None,
    fit_scaler: bool = False,
) -> tuple[np.ndarray, StandardScaler, list[str]]:
    """
    Numeric features are scaled; decision_type is one-hot (dt_*).
    """
    work = _parse_context_series(df)
    numeric = work[NUMERIC_FEATURES].astype(float).values
    if fit_scaler:
        scaler = StandardScaler()
        X_num = scaler.fit_transform(numeric)
    else:
        if scaler is None:
            raise ValueError("scaler required when fit_scaler=False")
        X_num = scaler.transform(numeric)

    dummies, inferred_dummy_cols = _dummy_columns(work["decision_type"])
    if dummy_cols is not None:
        dummies = dummies.reindex(columns=dummy_cols, fill_value=0.0)
    else:
        dummy_cols = inferred_dummy_cols

    X = np.hstack([X_num, dummies.values])
    feature_names = NUMERIC_FEATURES + dummy_cols
    return X, scaler, feature_names


def predict_wpa_optimal(df: pd.DataFrame, model_meta: dict) -> np.ndarray:
    """Vectorized optimal WPA from a saved ridge model."""
    scaler = StandardScaler()
    scaler.mean_ = np.array(model_meta["scaler_mean"], dtype=float)
    scaler.scale_ = np.array(model_meta["scaler_scale"], dtype=float)
    scaler.var_ = scaler.scale_**2
    scaler.n_features_in_ = len(scaler.mean_)

    dummy_cols = model_meta["dummy_columns"]
    X, _, _ = build_design_matrix(
        df, scaler=scaler, dummy_cols=dummy_cols, fit_scaler=False
    )
    coef = np.array(model_meta["coef"], dtype=float)
    intercept = float(model_meta["intercept"])
    return X @ coef + intercept


def build_model(season: int = 2024):
    """
    Fit Ridge regression: context + decision type → typical WPA (expected value).

    `wpa_optimal` at score time is this prediction (counterfactual baseline for
    “what similar situations tend to produce”), compared to `wpa_actual` from
    the win-probability feed or synthetic data.
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

    y = df["wpa_actual"].astype(float).values
    X, scaler, feature_names = build_design_matrix(df, fit_scaler=True)
    dummy_cols = [c for c in feature_names if c.startswith("dt_")]

    model = Ridge(alpha=1.0)
    model.fit(X, y)
    pred = model.predict(X)
    residuals = y - pred
    rmse = float(np.sqrt(np.mean(residuals**2)))

    wpa_std = float(np.std(y))
    model_meta = {
        "model_type": "ridge_wpa",
        "season": season,
        "n_decisions": len(df),
        "numeric_features": NUMERIC_FEATURES,
        "dummy_columns": dummy_cols,
        "feature_names": feature_names,
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(),
        "coef": model.coef_.tolist(),
        "intercept": float(model.intercept_),
        "wpa_mean": float(np.mean(y)),
        "wpa_std": wpa_std,
        "train_rmse": rmse,
        "optimal_baseline": float(np.percentile(np.abs(y), 75)),
    }

    model_path = os.path.join(MODEL_DIR, f"wpa_model_{season}.json")
    with open(model_path, "w") as f:
        json.dump(model_meta, f, indent=2)

    print(f"[build_model] Model saved → {model_path}")
    print(
        f"[build_model] WPA mean={model_meta['wpa_mean']:.4f}, "
        f"std={model_meta['wpa_std']:.4f}, train_rmse={rmse:.4f}"
    )


def main():
    build_model(2024)


if __name__ == "__main__":
    main()
