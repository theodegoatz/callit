# pipeline/mlb_win_probability.py — Win-probability feed for manager decisions (MLB Stats API)
"""
Fetches `/api/v1/game/{gamePk}/winProbability`, which enriches each play with
`homeTeamWinProbabilityAdded` (percentage points). Substitution actions are in
`playEvents` with `isSubstitution` / `eventType`.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Iterator

logger = logging.getLogger(__name__)

WIN_PROBABILITY_URL = "https://statsapi.mlb.com/api/v1/game/{game_pk}/winProbability"
USER_AGENT = "CallItPipeline/1.0"

# Polite pacing when bulk-downloading many games
DEFAULT_REQUEST_SLEEP_SEC = 0.12

SUBSTITUTION_EVENT_TYPES = frozenset(
    {
        "pitching_substitution",
        "offensive_substitution",
        "defensive_substitution",
        "mound_visit",
    }
)


def fetch_win_probability_plays(
    game_pk: int,
    *,
    timeout: int = 90,
) -> list[dict[str, Any]]:
    url = WIN_PROBABILITY_URL.format(game_pk=game_pk)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.URLError as e:
        logger.error("winProbability request failed for gamePk=%s: %s", game_pk, e)
        raise
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError(f"winProbability: expected list, got {type(data)}")
    return data


def _batting_team(half: str, home_team: str, away_team: str) -> str:
    return away_team if half == "top" else home_team


def _fielding_team(half: str, home_team: str, away_team: str) -> str:
    return home_team if half == "top" else away_team


def _team_wpa_from_home_added(
    home_team_win_prob_added: float | None,
    *,
    decision_team: str,
    home_team: str,
) -> float | None:
    if home_team_win_prob_added is None:
        return None
    ha = float(home_team_win_prob_added) / 100.0
    return ha if decision_team == home_team else -ha


def _classify_substitution(
    event_type: str, description: str
) -> tuple[str, str]:
    desc = (description or "").strip()
    et = (event_type or "").strip().lower()

    if et == "pitching_substitution":
        return "pitching_change", desc or "Pitching change"

    if et == "mound_visit":
        return "mound_visit", desc or "Mound visit"

    if et == "defensive_substitution":
        return "defensive_substitution", desc or "Defensive substitution"

    if et == "offensive_substitution":
        dl = desc.lower()
        if "pinch-hitter" in dl or "pinch hitter" in dl:
            return "pinch_hitter", desc
        if "pinch-runner" in dl or "pinch runner" in dl:
            return "pinch_runner", desc
        return "offensive_substitution", desc

    return "substitution_other", desc or et or "Substitution"


def _leverage_from_win_pct(home_win_pct: float | None) -> float:
    if home_win_pct is None:
        return 1.0
    try:
        p = float(home_win_pct)
    except (TypeError, ValueError):
        return 1.0
    # 50% = toss-up; scale distance from 50 into ~0.7–2.5
    return round(0.7 + min(abs(p - 50.0) / 25.0, 1.8), 2)


def iter_decision_rows_from_plays(
    plays: list[dict[str, Any]],
    *,
    game_id: str,
    home_team: str,
    away_team: str,
    home_score: int,
    away_score: int,
) -> Iterator[dict[str, Any]]:
    """
    Yield decision_moments-shaped dicts (without DB id) for substitution-style
    playEvents. WPA is from the team's perspective (positive = helped that team).
    """
    for play in plays:
        about = play.get("about") or {}
        half = str(about.get("halfInning") or "top")
        inning = int(about.get("inning") or 1)
        home_wp = play.get("homeTeamWinProbability")
        home_added = play.get("homeTeamWinProbabilityAdded")

        for ev in play.get("playEvents") or []:
            if not isinstance(ev, dict):
                continue
            if not ev.get("isSubstitution"):
                continue
            det = ev.get("details") or {}
            et = str(det.get("eventType") or "").strip().lower()
            if et not in SUBSTITUTION_EVENT_TYPES:
                continue

            desc = str(det.get("description") or "").strip()
            dtype, description = _classify_substitution(et, desc)

            hs = det.get("homeScore")
            aw = det.get("awayScore")
            try:
                hs_i = int(hs) if hs is not None else int(home_score)
            except (TypeError, ValueError):
                hs_i = int(home_score)
            try:
                aw_i = int(aw) if aw is not None else int(away_score)
            except (TypeError, ValueError):
                aw_i = int(away_score)
            run_diff = abs(hs_i - aw_i)
            is_close = run_diff <= 3
            leverage = _leverage_from_win_pct(
                float(home_wp) if home_wp is not None else None
            )
            if is_close and inning >= 7:
                leverage = round(leverage * 1.15, 2)

            if et == "offensive_substitution":
                team = _batting_team(half, home_team, away_team)
            else:
                team = _fielding_team(half, home_team, away_team)

            wpa = _team_wpa_from_home_added(
                home_added, decision_team=team, home_team=home_team
            )
            if wpa is None:
                continue

            context: dict[str, Any] = {
                "inning": inning,
                "half": half,
                "run_differential": run_diff,
                "leverage_index": leverage,
                "decision_type": dtype,
                "home_win_prob_pct": home_wp,
                "home_win_prob_added_pct": home_added,
                "source": "mlb_win_probability",
            }

            yield {
                "game_id": game_id,
                "inning": inning,
                "half": half,
                "decision_type": dtype,
                "team": team,
                "description": description[:500] if description else dtype,
                "wpa_actual": round(float(wpa), 5),
                "context": context,
            }


def game_pk_from_game_id(game_id: str) -> int | None:
    parts = str(game_id).split("_", 1)
    if len(parts) != 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None
