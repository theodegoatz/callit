# MLB schedule ingest

## Root cause (historical)

1. **Random sample fallback**: `ingest.py` called `_generate_sample_schedule()` on any pybaseball failure, writing fake matchups keyed by `game_id`.
2. **Wrong parser branch**: `load_games()` routed any parquet with a `game_id` column to the sample processor, so real data shapes that included `game_id` could be mis-parsed.
3. **Wrong season / future rows**: Sample data used a fixed date window on the requested season; mixed or cached parquets could surface inconsistent years.

## Current behavior

- **Primary**: [MLB Stats API](https://statsapi.mlb.com/) (`pipeline/mlb_schedule.py`) — regular season, completed games only (`Final` / `Completed Early` by `detailedState`, not postponed games that look “Final” in `abstractGameState`).
- **Backup**: pybaseball / Baseball Reference scrape (`_download_pybaseball_schedule`), tagged `data_source=pybaseball`.
- **Sample**: Only if `USE_SAMPLE_SCHEDULE=true`. Otherwise ingest **exits non-zero** and does not write random schedules.

`game_id` for MLB rows is `{season}_{gamePk}` (e.g. `2024_747065`). Legacy pybaseball-derived IDs remain `{season}_{date}_{home}_{away}` until re-ingested.

## Regenerate parquet (no sample)

```bash
rm -f data/schedule_2024.parquet
python3 -m pipeline.ingest --season 2024 --force-refresh
python3 scripts/verify_schedule.py --season 2024
python3 -c "from pipeline.games import load_games; load_games(2024)"
```

## One-shot: fill Supabase for localhost testing

With a working `DATABASE_URL` in `.env` (Session pooler URI + database password):

```bash
python3 scripts/setup_supabase_demo.py --season 2024 --force-schedule
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

## Verification

```bash
pytest tests/
python3 scripts/verify_schedule.py --season 2024 --api-smoke   # needs DATABASE_URL for API/DB checks
```

## SQL: clear a season before reload (FK order)

Run against your DB when you need a clean reload for one season (`:season` = e.g. `2024`):

```sql
DELETE FROM decision_moments
WHERE game_id IN (SELECT game_id FROM games WHERE season = :season);

DELETE FROM games WHERE season = :season;
```

If you use optional tables (scorecards, lineups), delete children that reference `games` or `decision_moments` **before** `decision_moments`, e.g.:

```sql
-- Example pattern — adjust table names to match your schema
DELETE FROM scorecards WHERE game_id IN (SELECT game_id FROM games WHERE season = :season);
DELETE FROM game_lineups WHERE game_id IN (SELECT game_id FROM games WHERE season = :season);
```

Then re-run `load_games` / `extract` / downstream pipeline steps.

## Local API

```bash
export DATABASE_URL=postgresql://...
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```
