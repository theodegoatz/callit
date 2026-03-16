# api/main.py — FastAPI analytics API + dashboard
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from pipeline.db import get_engine, ensure_schema

app = FastAPI(title="CallIt Analytics API", version="1.0.0")

BASE_DIR = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
static_dir = os.path.join(BASE_DIR, "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.on_event("startup")
def startup():
    engine = get_engine()
    ensure_schema(engine)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    engine = get_engine()
    with engine.connect() as conn:
        managers = conn.execute(
            text(
                "SELECT name, team, season, total_decisions, optimal_decisions, "
                "grade, score FROM managers WHERE grade IS NOT NULL "
                "ORDER BY score DESC"
            )
        ).mappings().all()

        summary = conn.execute(
            text(
                "SELECT COUNT(*) as n_games FROM games"
            )
        ).mappings().first()

        dm_count = conn.execute(
            text("SELECT COUNT(*) as n FROM decision_moments")
        ).scalar()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "managers": [dict(m) for m in managers],
        "n_games": summary["n_games"] if summary else 0,
        "n_decisions": dm_count or 0,
    })


@app.get("/decisions")
def get_decisions(
    season: int = Query(2024),
    team: str = Query(None),
    manager: str = Query(None),
    decision_type: str = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
):
    engine = get_engine()
    conditions = ["g.season = :season"]
    params = {"season": season, "limit": limit, "offset": offset}

    if team:
        conditions.append("dm.team = :team")
        params["team"] = team
    if manager:
        conditions.append("dm.manager_name = :manager")
        params["manager"] = manager
    if decision_type:
        conditions.append("dm.decision_type = :dtype")
        params["dtype"] = decision_type

    where = " AND ".join(conditions)

    with engine.connect() as conn:
        total = conn.execute(
            text(
                f"SELECT COUNT(*) FROM decision_moments dm "
                f"JOIN games g ON dm.game_id = g.game_id "
                f"WHERE {where}"
            ),
            params,
        ).scalar()

        rows = conn.execute(
            text(
                f"SELECT dm.id, dm.game_id, dm.inning, dm.half, "
                f"dm.decision_type, dm.manager_name, dm.team, dm.description, "
                f"dm.wpa_actual, dm.wpa_optimal, dm.decision_value, "
                f"dm.is_optimal, dm.is_ambiguous, dm.scored, "
                f"g.game_date, g.home_team, g.away_team "
                f"FROM decision_moments dm "
                f"JOIN games g ON dm.game_id = g.game_id "
                f"WHERE {where} "
                f"ORDER BY g.game_date DESC, dm.id "
                f"LIMIT :limit OFFSET :offset"
            ),
            params,
        ).mappings().all()

    return JSONResponse({
        "total": total,
        "limit": limit,
        "offset": offset,
        "decisions": [_serialize_row(r) for r in rows],
    })


@app.get("/managers")
def get_managers(season: int = Query(2024)):
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, name, team, season, total_decisions, "
                "optimal_decisions, ambiguous_count, total_wpa, "
                "avg_decision_val, grade, score "
                "FROM managers WHERE season = :s "
                "ORDER BY score DESC"
            ),
            {"s": season},
        ).mappings().all()

    return JSONResponse({
        "season": season,
        "managers": [_serialize_row(r) for r in rows],
    })


@app.get("/health")
def health():
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


def _serialize_row(row):
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d
