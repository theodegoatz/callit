# CallIt

Baseball analytics that scores MLB manager decisions against win-probability–optimal choices. Fans can see when a skipper made the right call at the moment—not with hindsight—and compare manager grades across the season.

## Features

- **Schedule ingest** — Pulls completed regular-season games from the MLB Stats API (pybaseball as fallback); refuses random sample data unless explicitly enabled.
- **Decision moments** — Detects pitching changes, pinch hitters, IBBs, bunts, steals, and related in-game calls from play-by-play data.
- **WPA scoring** — Ridge regression model estimates expected win probability for each decision; flags optimal vs suboptimal and ambiguous calls (small WPA delta).
- **Manager grades** — Aggregates decisions into per-manager scores, letter grades, and a leaderboard.
- **Web dashboard** — FastAPI + Jinja2 UI for games, decision timelines, manager profiles, admin health, and a daily-game view.
- **JSON API** — REST endpoints for games, decisions, managers, and leaderboard (same backend as the dashboard).
- **Flexible database** — PostgreSQL on Supabase for production; SQLite at `data/callit_local.db` for local dev without cloud credentials.

## Tech stack

| Layer | Tools |
|--------|--------|
| Language | Python 3.12+ |
| API & UI | FastAPI, Jinja2, Uvicorn |
| Data & ORM | SQLAlchemy, pandas, pybaseball |
| ML | scikit-learn (WPA regression) |
| Database | PostgreSQL (Supabase) or SQLite |
| Deploy | Vercel (serverless API); full pipeline runs locally or on a long-lived host |

## Screenshots

_Add captures under `docs/screenshots/` and uncomment the table below._

<!--
| Dashboard | Manager profile | Game decisions |
|-----------|-----------------|------------------|
| ![Dashboard](docs/screenshots/dashboard.png) | ![Manager](docs/screenshots/manager.png) | ![Game](docs/screenshots/game.png) |
-->

| View | File |
|------|------|
| Home dashboard | `docs/screenshots/dashboard.png` |
| Manager profile | `docs/screenshots/manager.png` |
| Game decision timeline | `docs/screenshots/game.png` |

## Local setup

### Prerequisites

- Python 3.12+
- Git

### 1. Clone and install

```bash
git clone https://github.com/<your-org>/callit.git
cd callit
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python verify_env.py
```

### 2. Environment

```bash
cp .env.example .env
```

For quick local dev **without** Postgres, leave `DATABASE_URL` unset (or set `CALLIT_USE_SQLITE=1`). The app uses SQLite automatically.

For Supabase, fill in `DATABASE_URL` and the Supabase API keys (see [Environment variables](#environment-variables)).

### 3. Bootstrap data

**Option A — one-shot demo (recommended)**

```bash
python scripts/setup_supabase_demo.py --season 2024
```

**Option B — full pipeline**

```bash
python -m pipeline.nightly --season 2024
```

### 4. Run the API

```bash
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) for the dashboard. Useful routes: `/games`, `/managers`, `/leaderboard`, `/admin`, `/health`.

### Tests

```bash
pytest
```

Schedule verification (optional, needs a populated DB):

```bash
python scripts/verify_schedule.py --season 2024
python scripts/verify_schedule.py --season 2024 --api-smoke
```

## Environment variables

Copy `.env.example` to `.env` and set values as needed. Variables from the example file:

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | No* | PostgreSQL connection URI (Supabase direct or session pooler). Omit for local SQLite. |
| `SUPABASE_URL` | For Supabase client features | Project URL (`Settings → API`). |
| `SUPABASE_KEY` | For Supabase client features | Anon/public API key. |

\* Local dev defaults to SQLite when `DATABASE_URL` is unset.

**Optional (documented in `.env.example` or used by the app):**

| Variable | Description |
|----------|-------------|
| `CALLIT_USE_SQLITE` | Force SQLite even if `DATABASE_URL` is set (`1` / `true`). |
| `CALLIT_USE_SESSION_POOLER` | Auto-rewrite direct Supabase host to IPv4 session pooler (default `1`; set `0` to disable). |
| `SUPABASE_POOLER_REGION` | Pooler region when auto-rewriting (default `us-west-2`). |
| `SUPABASE_POOLER_HOST` | Override pooler hostname from the dashboard. |
| `USE_SAMPLE_SCHEDULE` | Generate synthetic schedules for dev only (`true`); never used in production ingest. |
| `CALLIT_SKIP_ENSURE_SCHEMA` | Skip automatic schema migration on startup. |

`.env` overrides process-level `DATABASE_URL` when both are present (useful when a host also injects database config).

## Deployment

### Vercel (API & dashboard)

The repo is configured for Vercel serverless via `vercel.json` and `api/index.py`. Production installs use the slim `requirements-vercel.txt` bundle (FastAPI + DB only).

1. Connect the GitHub repo in the Vercel dashboard.
2. Set **Environment variables** in the project: at minimum `DATABASE_URL` (and `SUPABASE_*` if used).
3. Deploy; the entrypoint is `api.main:app`.

The Vercel build excludes the full ML pipeline, `data/`, and `models/` (see `.vercelignore`). Run ingest, scoring, and model training on a machine or job runner with `requirements.txt`, then point the deployed API at the same database.

### Database

Apply or sync schema with:

```bash
# Uses SQLAlchemy ensure_schema on startup, or run db/schema.sql against Supabase
```

For a clean season reload, see [docs/SCHEDULE.md](docs/SCHEDULE.md).

### Full pipeline on a host

For nightly or batch jobs (`pipeline/nightly.py`), use any Python 3.12 host (VM, Railway, Render, GitHub Actions, etc.) with `requirements.txt`, the same `DATABASE_URL`, and a cron or scheduler. Example:

```bash
python -m pipeline.nightly --season 2024
```

## Project layout

```
api/           FastAPI app, templates, Vercel entrypoint
pipeline/      Ingest, extract, model, scoring, grades
db/            PostgreSQL & SQLite schema
models/        Trained WPA model artifacts
scripts/       Bootstrap and verification utilities
tests/         Pytest suite
```

## Current status

**CallIt is actively in development.** Core ingest, decision extraction, WPA scoring, and the web dashboard are in place; mobile apps and fan-facing “make the call” flows are planned. APIs and schema may change between releases—pin deployments to a commit or tag for production use.

## License

License TBD. Add a `LICENSE` file when you choose one.
