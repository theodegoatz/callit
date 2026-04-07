"""Tests for ridge WPA model prediction helper."""
import json

import numpy as np
import pandas as pd

from pipeline.build_model import build_design_matrix, predict_wpa_optimal


def test_predict_wpa_optimal_roundtrip():
    df = pd.DataFrame(
        {
            "inning": [5, 8],
            "decision_type": ["pitching_change", "pinch_hitter"],
            "context": [
                json.dumps(
                    {
                        "leverage_index": 1.2,
                        "run_differential": 2,
                    }
                ),
                json.dumps({"leverage_index": 1.8, "run_differential": 0}),
            ],
        }
    )
    X, scaler, feature_names = build_design_matrix(df, fit_scaler=True)
    dummy_cols = [c for c in feature_names if c.startswith("dt_")]
    coef = np.zeros(X.shape[1])
    coef[0] = 0.01
    intercept = 0.001
    pred_manual = X @ coef + intercept

    meta = {
        "model_type": "ridge_wpa",
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(),
        "dummy_columns": dummy_cols,
        "coef": coef.tolist(),
        "intercept": float(intercept),
    }
    pred = predict_wpa_optimal(df, meta)
    np.testing.assert_allclose(pred, pred_manual, rtol=1e-6)
