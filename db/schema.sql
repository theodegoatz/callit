-- db/schema.sql — Database table definitions for CallIt

CREATE TABLE IF NOT EXISTS games (
    game_id        TEXT PRIMARY KEY,
    game_date      DATE NOT NULL,
    home_team      TEXT NOT NULL,
    away_team      TEXT NOT NULL,
    home_score     INTEGER,
    away_score     INTEGER,
    season         INTEGER NOT NULL,
    venue          TEXT,
    winning_team   TEXT,
    losing_team    TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS decision_moments (
    id              SERIAL PRIMARY KEY,
    game_id         TEXT NOT NULL REFERENCES games(game_id),
    inning          INTEGER NOT NULL,
    half            TEXT NOT NULL CHECK (half IN ('top', 'bottom')),
    decision_type   TEXT NOT NULL,
    manager_name    TEXT,
    team            TEXT NOT NULL,
    description     TEXT,
    wpa_actual      DOUBLE PRECISION,
    wpa_optimal     DOUBLE PRECISION,
    decision_value  DOUBLE PRECISION,
    is_optimal      BOOLEAN,
    is_ambiguous    BOOLEAN DEFAULT FALSE,
    context         JSONB,
    scored          BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS managers (
    id                SERIAL PRIMARY KEY,
    name              TEXT NOT NULL,
    team              TEXT NOT NULL,
    season            INTEGER NOT NULL,
    total_decisions   INTEGER DEFAULT 0,
    optimal_decisions INTEGER DEFAULT 0,
    ambiguous_count   INTEGER DEFAULT 0,
    total_wpa         DOUBLE PRECISION DEFAULT 0.0,
    avg_decision_val  DOUBLE PRECISION DEFAULT 0.0,
    grade             TEXT,
    score             DOUBLE PRECISION DEFAULT 0.0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (name, team, season)
);

CREATE INDEX IF NOT EXISTS idx_dm_game_id ON decision_moments(game_id);
CREATE INDEX IF NOT EXISTS idx_dm_manager ON decision_moments(manager_name);
CREATE INDEX IF NOT EXISTS idx_dm_team ON decision_moments(team);
CREATE INDEX IF NOT EXISTS idx_managers_season ON managers(season);
CREATE INDEX IF NOT EXISTS idx_games_season ON games(season);
