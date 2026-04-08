-- db/schema_sqlite.sql — SQLite schema for local development (no Postgres required)

CREATE TABLE IF NOT EXISTS games (
    game_id        TEXT PRIMARY KEY,
    game_date      TEXT NOT NULL,
    home_team      TEXT NOT NULL,
    away_team      TEXT NOT NULL,
    home_score     INTEGER,
    away_score     INTEGER,
    season         INTEGER NOT NULL,
    venue          TEXT,
    winning_team   TEXT,
    losing_team    TEXT,
    data_source    TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS decision_moments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id         TEXT NOT NULL REFERENCES games(game_id),
    inning          INTEGER NOT NULL,
    half            TEXT NOT NULL CHECK (half IN ('top', 'bottom')),
    decision_type   TEXT NOT NULL,
    manager_name    TEXT,
    team            TEXT NOT NULL,
    description     TEXT,
    wpa_actual      REAL,
    wpa_optimal     REAL,
    decision_value  REAL,
    is_optimal      INTEGER,
    is_ambiguous    INTEGER DEFAULT 0,
    context         TEXT,
    scored          INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS managers (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    team              TEXT NOT NULL,
    season            INTEGER NOT NULL,
    total_decisions   INTEGER DEFAULT 0,
    optimal_decisions INTEGER DEFAULT 0,
    ambiguous_count   INTEGER DEFAULT 0,
    total_wpa         REAL DEFAULT 0.0,
    avg_decision_val  REAL DEFAULT 0.0,
    grade             TEXT,
    score             REAL DEFAULT 0.0,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (name, team, season)
);

CREATE INDEX IF NOT EXISTS idx_dm_game_id ON decision_moments(game_id);
CREATE INDEX IF NOT EXISTS idx_dm_manager ON decision_moments(manager_name);
CREATE INDEX IF NOT EXISTS idx_dm_team ON decision_moments(team);
CREATE INDEX IF NOT EXISTS idx_managers_season ON managers(season);
CREATE INDEX IF NOT EXISTS idx_games_season ON games(season);
