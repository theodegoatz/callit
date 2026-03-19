# pipeline/mlb_schedule.py — Official MLB Stats API schedule + results
"""
Fetches regular-season schedules via statsapi.mlb.com and normalizes rows
aligned with the `games` table (gamePk-based game_id, CallIt team abbrevs).
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import date, datetime
from typing import Any, Iterator

import pandas as pd

logger = logging.getLogger(__name__)

SCHEDULE_URL = (
    "https://statsapi.mlb.com/api/v1/schedule"
    "?sportId=1&season={season}&gameType=R&hydrate=team,linescore"
)

# MLB Stats API abbreviations that differ from CallIt / pybaseball conventions
MLB_TO_CALLIT_ABBR: dict[str, str] = {
    "AZ": "ARI",
    "KC": "KCR",
    "SD": "SDP",
    "SF": "SFG",
    "TB": "TBR",
    "WSH": "WSN",
}


def normalize_team_abbrev(mlb_abbr: str) -> str:
    a = (mlb_abbr or "").strip().upper()
    return MLB_TO_CALLIT_ABBR.get(a, a)


def fetch_schedule_payload(season: int, timeout: int = 120) -> dict[str, Any]:
    url = SCHEDULE_URL.format(season=season)
    req = urllib.request.Request(url, headers={"User-Agent": "CallItPipeline/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.URLError as e:
        logger.error("MLB schedule request failed: %s", e)
        raise
    return json.loads(raw)


def iter_schedule_games(payload: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    for day in payload.get("dates") or []:
        d = day.get("date") or ""
        for game in day.get("games") or []:
            yield d, game


def _is_completed_game_status(game: dict[str, Any]) -> bool:
    """
    MLB sometimes sets abstractGameState=Final for postponed games; use detailedState.
    """
    st = game.get("status") or {}
    detailed = (st.get("detailedState") or "").strip()
    return detailed in ("Final", "Completed Early")


def parse_game_row(
    game: dict[str, Any],
    season: int,
    *,
    require_final: bool = True,
    max_official_date: date | None = None,
) -> dict[str, Any] | None:
    """
    Build one normalized row. Returns None if the game should be skipped.
    """
    if require_final and not _is_completed_game_status(game):
        return None

    game_pk = game.get("gamePk")
    if game_pk is None:
        return None

    teams = game.get("teams") or {}
    home_side = teams.get("home") or {}
    away_side = teams.get("away") or {}
    home_team_obj = (home_side.get("team") or {})
    away_team_obj = (away_side.get("team") or {})

    home_abbr = normalize_team_abbrev(str(home_team_obj.get("abbreviation") or ""))
    away_abbr = normalize_team_abbrev(str(away_team_obj.get("abbreviation") or ""))
    if not home_abbr or not away_abbr:
        return None

    official = game.get("officialDate") or ""
    if not official:
        return None
    try:
        game_date = datetime.strptime(official, "%Y-%m-%d").date()
    except ValueError:
        return None

    if game_date.year != season:
        return None

    if max_official_date is not None and game_date > max_official_date:
        return None

    hs = home_side.get("score")
    aw = away_side.get("score")
    if hs is None or aw is None:
        if require_final:
            return None
        home_score, away_score = 0, 0
    else:
        home_score, away_score = int(hs), int(aw)

    venue_name = None
    venue = home_team_obj.get("venue") or {}
    if isinstance(venue, dict):
        venue_name = venue.get("name")

    winning_team = home_abbr if home_score > away_score else away_abbr
    losing_team = away_abbr if home_score > away_score else home_abbr
    if home_score == away_score:
        winning_team, losing_team = None, None

    game_id = f"{season}_{game_pk}"

    return {
        "game_pk": int(game_pk),
        "game_id": game_id,
        "game_date": game_date,
        "home_team": home_abbr,
        "away_team": away_abbr,
        "home_score": home_score,
        "away_score": away_score,
        "season": season,
        "venue": venue_name,
        "winning_team": winning_team,
        "losing_team": losing_team,
        "data_source": "mlb_api",
    }


def schedule_payload_to_records(
    payload: dict[str, Any],
    season: int,
    *,
    require_final: bool = True,
    max_official_date: date | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, game in iter_schedule_games(payload):
        row = parse_game_row(
            game,
            season,
            require_final=require_final,
            max_official_date=max_official_date,
        )
        if row:
            rows.append(row)
    return rows


def download_season_dataframe(
    season: int,
    *,
    require_final: bool = True,
    max_official_date: date | None = None,
) -> pd.DataFrame:
    payload = fetch_schedule_payload(season)
    records = schedule_payload_to_records(
        payload,
        season,
        require_final=require_final,
        max_official_date=max_official_date,
    )
    if not records:
        raise RuntimeError(f"No schedule rows parsed for season {season}")
    df = pd.DataFrame(records)
    dup_n = int(df["game_pk"].duplicated().sum())
    if dup_n:
        logger.warning("Dropping %s duplicate game_pk rows from MLB schedule payload", dup_n)
        df = df.drop_duplicates(subset=["game_pk"], keep="first")
    df["game_date"] = pd.to_datetime(df["game_date"]).dt.date
    return df


# Known 2024 regular-season spot checks (gamePk, officialDate, home, away, home_score, away_score)
# Verified against MLB Stats API schedule feed.
SPOTCHECK_GAMES_2024: tuple[tuple[int, str, str, str, int, int], ...] = (
    (745444, "2024-03-20", "SDP", "LAD", 2, 5),
    (746418, "2024-03-28", "HOU", "NYY", 4, 5),
    (747065, "2024-09-27", "ATL", "KCR", 3, 0),
    (746335, "2024-03-28", "KCR", "MIN", 1, 4),
    (747060, "2024-03-28", "BAL", "LAA", 11, 3),
)
