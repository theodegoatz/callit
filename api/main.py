# api/main.py — FastAPI analytics API + dashboard
import os
import sys
import time
from urllib.parse import quote

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from pipeline.db import format_db_error, get_engine, ensure_schema

app = FastAPI(title="CallIt Analytics API", version="1.0.0")

BASE_DIR = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
templates.env.filters["pathquote"] = lambda s: quote(str(s), safe="")

static_dir = os.path.join(BASE_DIR, "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

_ADMIN_CACHE_TTL_SEC = 60.0
_admin_cache: dict = {"t_mono": 0.0, "ctx": None}


@app.on_event("startup")
def startup():
    from pipeline.db import should_run_ensure_schema

    try:
        engine = get_engine()
        if should_run_ensure_schema():
            ensure_schema(engine)
    except Exception as exc:
        # Log for Vercel function logs; avoid crashing import if DB misconfigured.
        print(f"[startup] database init skipped or failed: {exc}")


def _db_error_page(request: Request, exc: Exception) -> HTMLResponse:
    return templates.TemplateResponse(
        "db_error.html",
        {"request": request, "message": format_db_error(exc)},
        status_code=503,
    )


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    try:
        engine = get_engine()
    except Exception as exc:
        return _db_error_page(request, exc)

    try:
        with engine.connect() as conn:
            managers = conn.execute(
                text(
                    "SELECT name, team, season, total_decisions, optimal_decisions, "
                    "grade, score FROM managers WHERE grade IS NOT NULL "
                    "ORDER BY score DESC"
                )
            ).mappings().all()

            summary = conn.execute(
                text("SELECT COUNT(*) as n_games FROM games")
            ).mappings().first()

            dm_count = conn.execute(
                text("SELECT COUNT(*) as n FROM decision_moments")
            ).scalar()

            recent_games = conn.execute(
                text(
                    "SELECT game_id, game_date, home_team, away_team, home_score, away_score, "
                    "data_source "
                    "FROM games ORDER BY game_date DESC NULLS LAST, game_id DESC LIMIT 12"
                )
            ).mappings().all()

            recent_decisions = conn.execute(
                text(
                    "SELECT dm.id, dm.game_id, dm.decision_type, dm.manager_name, "
                    "dm.team, dm.description, dm.decision_value, dm.is_optimal, "
                    "g.game_date, g.home_team, g.away_team "
                    "FROM decision_moments dm "
                    "JOIN games g ON dm.game_id = g.game_id "
                    "ORDER BY g.game_date DESC NULLS LAST, dm.id DESC LIMIT 15"
                )
            ).mappings().all()
    except Exception as exc:
        return _db_error_page(request, exc)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "managers": [dict(m) for m in managers],
            "n_games": summary["n_games"] if summary else 0,
            "n_decisions": dm_count or 0,
            "recent_games": [dict(r) for r in recent_games],
            "recent_decisions": [dict(r) for r in recent_decisions],
        },
    )


def _fetch_admin_rows(conn):
    if conn.engine.dialect.name == "postgresql":
        conn.execute(text("SET LOCAL statement_timeout = '10s'"))

    health = conn.execute(
        text(
            "SELECT "
            "(SELECT COUNT(*) FROM games) AS n_games, "
            "(SELECT COUNT(*) FROM decision_moments) AS n_decisions, "
            "(SELECT COUNT(*) FROM managers) AS n_managers, "
            "(SELECT MAX(game_date) FROM games) AS latest_game_date"
        )
    ).mappings().first()

    anomalies = conn.execute(
        text(
            "SELECT "
            "(SELECT COUNT(*) FROM decision_moments WHERE manager_name IS NULL) "
            "AS dm_null_manager, "
            "(SELECT COUNT(*) FROM decision_moments WHERE is_optimal IS NULL) "
            "AS dm_null_optimal, "
            "(SELECT COUNT(*) FROM games g WHERE NOT EXISTS "
            "(SELECT 1 FROM decision_moments dm WHERE dm.game_id = g.game_id)) "
            "AS games_no_decisions, "
            "(SELECT COUNT(*) FROM games WHERE data_source = 'sample') "
            "AS games_sample_source, "
            "(SELECT COUNT(*) FROM games WHERE data_source IS NULL OR data_source = 'legacy') "
            "AS games_legacy_source"
        )
    ).mappings().first()

    mgr_qa = conn.execute(
        text(
            "SELECT name, team, season, total_decisions, grade "
            "FROM managers "
            "WHERE total_decisions < 50 AND grade IS NOT NULL "
            "ORDER BY season DESC, name LIMIT 25"
        )
    ).mappings().all()

    if conn.engine.dialect.name == "sqlite":
        avg_expr = "ROUND(AVG(decision_value), 4)"
    else:
        avg_expr = "ROUND(AVG(decision_value)::numeric, 4)"
    quality_by_type = conn.execute(
        text(
            "SELECT decision_type, COUNT(*) AS n, "
            f"{avg_expr} AS avg_dv, "
            "SUM(CASE WHEN is_optimal THEN 1 ELSE 0 END) AS n_optimal "
            "FROM decision_moments "
            "GROUP BY decision_type "
            "ORDER BY n DESC"
        )
    ).mappings().all()

    high_impact = conn.execute(
        text(
            "SELECT dm.id, dm.game_id, dm.decision_type, dm.manager_name, "
            "dm.team, dm.description, dm.decision_value, dm.is_optimal, "
            "g.game_date, g.home_team, g.away_team "
            "FROM decision_moments dm "
            "JOIN games g ON dm.game_id = g.game_id "
            "WHERE dm.decision_value IS NOT NULL "
            "ORDER BY ABS(dm.decision_value) DESC "
            "LIMIT 25"
        )
    ).mappings().all()

    return {
        "health": dict(health) if health else {},
        "anomalies": dict(anomalies) if anomalies else {},
        "mgr_qa": [dict(r) for r in mgr_qa],
        "quality_by_type": [dict(r) for r in quality_by_type],
        "high_impact": [dict(r) for r in high_impact],
    }


@app.get("/admin", response_class=HTMLResponse)
def admin_console(request: Request):
    now = time.monotonic()
    if (
        _admin_cache["ctx"] is not None
        and now - _admin_cache["t_mono"] < _ADMIN_CACHE_TTL_SEC
    ):
        ctx = dict(_admin_cache["ctx"])
        ctx["request"] = request
        ctx["cached"] = True
        return templates.TemplateResponse("admin.html", ctx)

    engine = get_engine()
    with engine.begin() as conn:
        data = _fetch_admin_rows(conn)

    ctx = {
        "request": request,
        "cached": False,
        **data,
    }
    _admin_cache["t_mono"] = now
    _admin_cache["ctx"] = {k: v for k, v in ctx.items() if k != "request"}
    return templates.TemplateResponse("admin.html", ctx)


@app.get("/games")
def list_games(
    limit: int = Query(50, le=500),
    season: int = Query(None),
):
    engine = get_engine()
    params = {"limit": limit}
    where = ""
    if season is not None:
        where = "WHERE season = :season"
        params["season"] = season

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT game_id, game_date, home_team, away_team, "
                f"home_score, away_score, season, venue, winning_team, data_source "
                f"FROM games {where} "
                f"ORDER BY game_date DESC NULLS LAST, game_id DESC "
                f"LIMIT :limit"
            ),
            params,
        ).mappings().all()

    return JSONResponse({"games": [_serialize_row(r) for r in rows]})


@app.get("/games/{game_id}", response_class=HTMLResponse)
def game_scorecard(request: Request, game_id: str):
    engine = get_engine()
    with engine.connect() as conn:
        game = conn.execute(
            text("SELECT * FROM games WHERE game_id = :gid"),
            {"gid": game_id},
        ).mappings().first()
        if not game:
            raise HTTPException(status_code=404, detail="Game not found")

        decisions = conn.execute(
            text(
                "SELECT * FROM decision_moments WHERE game_id = :gid "
                "ORDER BY inning, half, id"
            ),
            {"gid": game_id},
        ).mappings().all()

    return templates.TemplateResponse(
        "game.html",
        {
            "request": request,
            "game": dict(game),
            "decisions": [dict(d) for d in decisions],
        },
    )


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


@app.get("/managers/{name}", response_class=HTMLResponse)
def manager_profile(request: Request, name: str, season: int = Query(2024)):
    engine = get_engine()
    with engine.connect() as conn:
        mgr = conn.execute(
            text(
                "SELECT * FROM managers WHERE name = :n AND season = :s "
                "ORDER BY team LIMIT 1"
            ),
            {"n": name, "s": season},
        ).mappings().first()
        if not mgr:
            raise HTTPException(status_code=404, detail="Manager not found")

        recent = conn.execute(
            text(
                "SELECT dm.id, dm.game_id, dm.inning, dm.half, "
                "dm.decision_type, dm.description, dm.decision_value, "
                "dm.is_optimal, g.game_date, g.home_team, g.away_team "
                "FROM decision_moments dm "
                "JOIN games g ON dm.game_id = g.game_id "
                "WHERE dm.manager_name = :n AND g.season = :s "
                "ORDER BY g.game_date DESC, dm.id DESC LIMIT 30"
            ),
            {"n": name, "s": season},
        ).mappings().all()

    return templates.TemplateResponse(
        "manager.html",
        {
            "request": request,
            "manager": dict(mgr),
            "recent_decisions": [dict(r) for r in recent],
            "season": season,
        },
    )


@app.get("/leaderboard")
def leaderboard(season: int = Query(2024), limit: int = Query(100, le=500)):
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT name, team, season, total_decisions, optimal_decisions, "
                "ambiguous_count, grade, score "
                "FROM managers WHERE season = :s AND grade IS NOT NULL "
                "ORDER BY score DESC LIMIT :lim"
            ),
            {"s": season, "lim": limit},
        ).mappings().all()

    return JSONResponse({
        "season": season,
        "leaderboard": [_serialize_row(r) for r in rows],
    })


@app.get("/daily-game")
def daily_game():
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT g.game_id, g.game_date, g.home_team, g.away_team, "
                "g.home_score, g.away_score, g.season, "
                "(SELECT COUNT(*) FROM decision_moments dm "
                "WHERE dm.game_id = g.game_id) AS n_decisions "
                "FROM games g "
                "WHERE EXISTS (SELECT 1 FROM decision_moments dm "
                "WHERE dm.game_id = g.game_id) "
                "ORDER BY g.game_date DESC NULLS LAST, g.game_id DESC LIMIT 1"
            )
        ).mappings().first()

    if not row:
        return JSONResponse({"game": None})
    return JSONResponse({"game": _serialize_row(row)})


@app.get("/health")
def health():
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "detail": format_db_error(exc),
                "hint": (
                    "Copy Session pooler URI from Supabase → Database → "
                    "Connection string into Vercel DATABASE_URL."
                ),
            },
        )


def _serialize_row(row):
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d
