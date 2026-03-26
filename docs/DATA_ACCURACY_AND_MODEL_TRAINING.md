# Data accuracy and WPA model training

This guide explains how to keep CallIt’s pipeline data trustworthy and how to train the season WPA model that `score_all` expects on disk.

## What “accurate data” means here

1. **Real schedules, not samples**  
   Ingest uses the MLB Stats API first; pybaseball / Baseball Reference is a fallback. Random sample schedules are used **only** when `USE_SAMPLE_SCHEDULE=true`. For production-like data, keep that unset so ingest fails loudly instead of writing fake games. See [SCHEDULE.md](./SCHEDULE.md) for root causes and regeneration steps.

2. **Tagged source**  
   Games rows carry `data_source` (`mlb_api`, `pybaseball`, `sample`, etc.). Prefer `mlb_api` when you care about stable IDs (`{season}_{gamePk}`).

3. **Verify after ingest**  
   Run `python3 scripts/verify_schedule.py --season <YEAR>` after refreshing parquet. Use `--api-smoke` when you have `DATABASE_URL` set to cross-check the API/DB path.

4. **Validate coverage**  
   `python3 -m pipeline.validate` prints counts (games, decision moments, scored rows, manager grades) and simple scoring metrics. Use it after a full pipeline run to confirm nothing is empty or stuck.

5. **Clean reload**  
   If you mixed sample and real data, delete the season’s rows in FK-safe order (see SQL in [SCHEDULE.md](./SCHEDULE.md)), remove stale `data/schedule_<season>.parquet`, then re-ingest.

## Prerequisites

- Python venv with dependencies (`python3 verify_env.py` should pass).
- `DATABASE_URL` in `.env` (or env) pointing at your Postgres/Supabase database. The pipeline uses SQLAlchemy via `pipeline/db.py`.

## End-to-end pipeline (recommended)

Run everything for a season in order (idempotent steps):

```bash
python3 -m pipeline.nightly
```

Default season is `2024`. To use another year you would adjust the module’s `main(season=...)` or invoke the same steps from a small script; the important part is **order**: ingest → load games → extract decisions → managers → attribute → **build model** → score → grades → validate.

### Run individual steps

| Step | Command |
|------|---------|
| Download schedule parquet | `python3 -m pipeline.ingest --season 2024` |
| Load `games` table | `python3 -c "from pipeline.games import load_games; load_games(2024)"` |
| Extract decision moments | `python3 -c "from pipeline.extract import extract_decisions; extract_decisions(2024)"` |
| (Managers / attribution as needed) | `load_managers`, `attribute_managers` via `pipeline.nightly` imports |
| **Train model** | `python3 -c "from pipeline.build_model import build_model; build_model(2024)"` |
| Score decisions | `python3 -c "from pipeline.score_all import score_all; score_all(2024)"` |
| Manager grades | `python3 -c "from pipeline.manager_grades import compute_grades; compute_grades(2024)"` |
| Validation report | `python3 -m pipeline.validate` |

## Training the WPA model

**Script:** `pipeline/build_model.py`  
**Output:** `models/wpa_model_<season>.json`

### What it does

1. Loads `decision_moments` joined with `games` for the requested `season`.
2. Parses `context` JSON for `leverage_index` and `run_differential`; adds `late_inning` from `inning`.
3. Standardizes features and fits a **logistic regression** on whether `wpa_actual > 0`.
4. Writes metadata: scaler mean/scale, coefficients, intercept, `wpa_mean`, `wpa_std`, and `optimal_baseline` (75th percentile of absolute WPA).

### How to train

```bash
python3 -c "from pipeline.build_model import build_model; build_model(2024)"
```

Or run the module (defaults to 2024 in `main()`):

```bash
python3 -m pipeline.build_model
```

You need enough rows in `decision_moments` for that season; otherwise the script prints that no data was found and exits without writing a file.

### After training

`score_all` **requires** `models/wpa_model_<season>.json`. If the file is missing, scoring raises `FileNotFoundError`. Re-run `build_model` whenever you refresh a large slice of decision data or change seasons.

### Implementation note (for contributors)

`build_model` computes `wpa_optimal_est` in a DataFrame for analysis, but **`score_all` currently sets `wpa_optimal` using synthetic noise around `wpa_actual`**, not that estimate. Improving “accuracy” of optimal WPA in the product may mean wiring `wpa_optimal_est` (or a richer model) into `score_all` and validating against real counterfactual WPA when available.

## Quick checklist

- [ ] `USE_SAMPLE_SCHEDULE` unset or `false` for real data  
- [ ] Ingest completed; `verify_schedule.py` clean  
- [ ] `load_games` / `extract_decisions` run without errors  
- [ ] `build_model(<season>)` produced `models/wpa_model_<season>.json`  
- [ ] `score_all` then `compute_grades`  
- [ ] `python3 -m pipeline.validate` passes your expectations  

## Tests

```bash
pytest tests/
```

Use `scripts/verify_schedule.py --season 2024 --api-smoke` when the database is available.
