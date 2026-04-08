"""Unit tests for MLB winProbability parsing (no live HTTP)."""
import pytest

from pipeline.mlb_win_probability import (
    game_pk_from_game_id,
    iter_decision_rows_from_plays,
)


def _play_with_sub(
    *,
    inning: int,
    half: str,
    home_wp: float,
    home_added: float,
    event_type: str,
    description: str,
    home_score: int = 4,
    away_score: int = 3,
):
    return {
        "about": {
            "halfInning": half,
            "inning": inning,
            "isTopInning": half == "top",
        },
        "homeTeamWinProbability": home_wp,
        "homeTeamWinProbabilityAdded": home_added,
        "playEvents": [
            {
                "isSubstitution": True,
                "details": {
                    "eventType": event_type,
                    "description": description,
                    "homeScore": home_score,
                    "awayScore": away_score,
                },
            }
        ],
    }


def test_game_pk_from_game_id():
    assert game_pk_from_game_id("2024_746418") == 746418
    assert game_pk_from_game_id("bad") is None


def test_pitching_change_top_inning_fielding_team_is_home():
    plays = [
        _play_with_sub(
            inning=7,
            half="top",
            home_wp=55.0,
            home_added=2.0,
            event_type="pitching_substitution",
            description="Pitching Change: Reliever replaces Starter.",
        )
    ]
    rows = list(
        iter_decision_rows_from_plays(
            plays,
            game_id="2024_1",
            home_team="HOU",
            away_team="NYY",
            home_score=4,
            away_score=3,
        )
    )
    assert len(rows) == 1
    assert rows[0]["decision_type"] == "pitching_change"
    assert rows[0]["team"] == "HOU"
    assert rows[0]["wpa_actual"] == pytest.approx(0.02)


def test_pitching_change_bottom_inning_fielding_team_is_away():
    plays = [
        _play_with_sub(
            inning=7,
            half="bottom",
            home_wp=55.0,
            home_added=-3.0,
            event_type="pitching_substitution",
            description="Pitching Change: RHP replaces LHP.",
        )
    ]
    rows = list(
        iter_decision_rows_from_plays(
            plays,
            game_id="2024_1",
            home_team="HOU",
            away_team="NYY",
            home_score=4,
            away_score=3,
        )
    )
    assert rows[0]["team"] == "NYY"
    assert rows[0]["wpa_actual"] == pytest.approx(0.03)


def test_pinch_hitter_classified():
    plays = [
        _play_with_sub(
            inning=8,
            half="bottom",
            home_wp=48.0,
            home_added=-1.5,
            event_type="offensive_substitution",
            description="Offensive Substitution: Pinch-hitter X replaces Y.",
        )
    ]
    rows = list(
        iter_decision_rows_from_plays(
            plays,
            game_id="2024_1",
            home_team="HOU",
            away_team="NYY",
            home_score=4,
            away_score=3,
        )
    )
    assert rows[0]["decision_type"] == "pinch_hitter"
    # Bottom half: batting team is home (HOU).
    assert rows[0]["team"] == "HOU"
