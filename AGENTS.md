# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

CallIt is an early-stage baseball analytics app. See `.cursorrules` for full project context. Currently only the **Python pipeline** component exists with real dependencies; the `api/` (TypeScript/Node) and `app/` (React Native Expo) directories are empty stubs.

### Development environment

- **Python 3.12** with a virtual environment at `venv/`.
- Activate with: `source venv/bin/activate`
- Install/update deps: `pip install -r requirements.txt`
- Verify environment: `python verify_env.py` (checks venv is active + all key packages import)

### Environment variables

- Copy `.env.example` to `.env` and fill in Supabase credentials (`DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_KEY`).
- `.env` is gitignored. The pipeline code uses `python-dotenv` to load it.
- Pipeline scripts can run without real Supabase credentials (they are stubs), but any database-connected work will need valid credentials.

### Key caveats

- `python3.12-venv` system package is required to create the virtualenv (not installed by default on the VM — the update script handles this).
- `pybaseball` makes network requests to Baseball Savant/Statcast. First calls may be slow (~6s); `pybaseball.cache.enable()` caches results locally.
- **Direct PostgreSQL connections (port 5432) to Supabase are blocked** from the Cloud VM. Use the Supabase REST API client (`create_client(url, key)`) or the PostgREST HTTP endpoints instead of SQLAlchemy `create_engine(DATABASE_URL)` for database operations in this environment.
- There are no automated tests, linting config, or build steps in the repo yet. The only verification is `python verify_env.py`.
- The `api/` and `app/` directories contain only `.gitkeep` files — no Node.js or Expo setup is needed until those are scaffolded.
