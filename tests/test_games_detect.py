"""Tests for schedule parquet format detection."""
import pandas as pd
import pytest
from pipeline.games import _detect_schedule_kind


def test_detect_mlb_by_game_pk():
    df = pd.DataFrame(
        [
            {
                "game_pk": 747065,
                "game_id": "2024_747065",
                "game_date": "2024-09-27",
                "home_team": "ATL",
                "away_team": "KCR",
                "home_score": 3,
                "away_score": 0,
                "data_source": "mlb_api",
            }
        ]
    )
    assert _detect_schedule_kind(df) == "mlb_api"


def test_detect_pybaseball_over_data_source_column():
    """Tm/Opp shape wins even if a stale data_source column exists."""
    df = pd.DataFrame(
        [
            {
                "Tm": "NYY",
                "Opp": "BOS",
                "R": 5,
                "RA": 3,
                "Date": "Thursday, Mar 28",
                "data_source": "pybaseball",
            }
        ]
    )
    assert _detect_schedule_kind(df) == "pybaseball"


def test_detect_sample_by_data_source():
    df = pd.DataFrame(
        [
            {
                "game_id": "2024_00001",
                "home_team": "ATL",
                "away_team": "SEA",
                "R": 3,
                "RA": 1,
                "data_source": "sample",
            }
        ]
    )
    assert _detect_schedule_kind(df) == "sample"


def test_detect_unknown_raises():
    df = pd.DataFrame([{"foo": 1}])
    with pytest.raises(KeyError):
        _detect_schedule_kind(df)
