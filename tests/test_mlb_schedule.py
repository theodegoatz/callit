"""Unit tests for MLB Stats API schedule parsing (no live HTTP)."""
from pipeline.mlb_schedule import (
    parse_game_row,
    schedule_payload_to_records,
    normalize_team_abbrev,
)


def test_normalize_team_abbrev():
    assert normalize_team_abbrev("KC") == "KCR"
    assert normalize_team_abbrev("sd") == "SDP"
    assert normalize_team_abbrev("NYY") == "NYY"


def _final_game(
    game_pk: int,
    official_date: str,
    home_abbr: str,
    away_abbr: str,
    hs: int,
    aw: int,
    detailed: str = "Final",
):
    return {
        "gamePk": game_pk,
        "officialDate": official_date,
        "gameType": "R",
        "status": {"abstractGameState": "Final", "detailedState": detailed},
        "teams": {
            "home": {
                "team": {"abbreviation": home_abbr},
                "score": hs,
            },
            "away": {
                "team": {"abbreviation": away_abbr},
                "score": aw,
            },
        },
    }


def test_parse_game_row_skips_postponed_despite_abstract_final():
    g = _final_game(1, "2024-04-01", "PHI", "ATL", 0, 0)
    g["status"]["detailedState"] = "Postponed"
    g["teams"]["home"].pop("score", None)
    g["teams"]["away"].pop("score", None)
    assert parse_game_row(g, 2024) is None


def test_parse_game_row_maps_kc_to_kcr():
    g = _final_game(746335, "2024-03-28", "KC", "MIN", 1, 4)
    row = parse_game_row(g, 2024)
    assert row is not None
    assert row["game_id"] == "2024_746335"
    assert row["home_team"] == "KCR"
    assert row["away_team"] == "MIN"
    assert row["home_score"] == 1
    assert row["away_score"] == 4
    assert row["data_source"] == "mlb_api"


def test_schedule_payload_to_records_dedup_structure():
    payload = {
        "dates": [
            {
                "date": "2024-03-28",
                "games": [
                    _final_game(746418, "2024-03-28", "HOU", "NYY", 4, 5),
                ],
            }
        ]
    }
    rows = schedule_payload_to_records(payload, 2024)
    assert len(rows) == 1
    assert rows[0]["game_id"] == "2024_746418"
    assert rows[0]["away_team"] == "NYY"
