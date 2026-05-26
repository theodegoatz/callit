# pipeline/db.py — Shared database connection helper
import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _REPO_ROOT / ".env"


def _database_url_from_env_file():
    """If .env exists and defines DATABASE_URL, use it (overrides process env).

    Cloud agents often inject DATABASE_URL; a checked-out .env may be the
    intended source of truth for local runs when both are present.
    """
    if not _ENV_FILE.is_file():
        return None
    vals = dotenv_values(_ENV_FILE)
    url = vals.get("DATABASE_URL")
    if url:
        return url.strip().strip('"').strip("'")
    return None


load_dotenv()

_LOCAL_SQLITE = _REPO_ROOT / "data" / "callit_local.db"
# When DATABASE_URL is unset (no env, no .env entry), use a file SQLite DB so
# `uvicorn api.main:app` works on localhost without installing Postgres.
_DEFAULT_SQLITE_URL = f"sqlite:///{_LOCAL_SQLITE.resolve().as_posix()}"


def _raw_database_url() -> str | None:
    # Local-only: on Vercel always use DATABASE_URL from project env (never SQLite).
    if not _running_on_vercel() and os.getenv("CALLIT_USE_SQLITE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return None

    from_file = None if _running_on_vercel() else _database_url_from_env_file()
    for candidate in (from_file, os.getenv("DATABASE_URL")):
        if not candidate or not str(candidate).strip():
            continue
        url = str(candidate).strip().strip('"').strip("'")
        if not url:
            continue
        # Copied-from-example placeholder — use local SQLite instead
        if "[YOUR-PASSWORD]" in url or "[PASSWORD]" in url:
            continue
        return url
    return None


def resolve_database_url(raw: str) -> str:
    """
    Supabase direct host (db.<ref>.supabase.co) often resolves to IPv6 only.
    Session pooler (aws-0-<region>.pooler.supabase.com:5432) has IPv4 and works
    on networks without IPv6 routing. Set CALLIT_USE_SESSION_POOLER=0 to skip.
    """
    if os.getenv("CALLIT_USE_SESSION_POOLER", "1").lower() in ("0", "false", "no"):
        return raw
    u = make_url(raw)
    host = (u.host or "").lower()
    if "pooler.supabase.com" in host:
        return raw
    if (
        host.startswith("db.")
        and host.endswith(".supabase.co")
        and (u.port in (5432, None))
        and (u.username or "") == "postgres"
    ):
        ref = host.removeprefix("db.").removesuffix(".supabase.co")
        region = os.getenv("SUPABASE_POOLER_REGION", "us-west-2")
        pool_host = f"aws-0-{region}.pooler.supabase.com"
        return str(
            u.set(host=pool_host, port=5432, username=f"postgres.{ref}")
        )
    return raw


def _running_on_vercel() -> bool:
    return bool(os.getenv("VERCEL") or os.getenv("VERCEL_ENV"))


_resolved_raw = _raw_database_url()
if _resolved_raw is None:
    if _running_on_vercel():
        # Serverless has no writable data/ dir; require Supabase URL in project env.
        DATABASE_URL = None
    else:
        _LOCAL_SQLITE.parent.mkdir(parents=True, exist_ok=True)
        DATABASE_URL = _DEFAULT_SQLITE_URL
else:
    DATABASE_URL = resolve_database_url(_resolved_raw)

_engine = None


def _connect_args(url: str):
    u = make_url(url)
    host = (u.host or "").lower()
    args = {"connect_timeout": 10}
    if "supabase" in host:
        args["sslmode"] = "require"
    return args


def get_engine():
    global _engine
    if _engine is None:
        if DATABASE_URL is None:
            raise RuntimeError(
                "DATABASE_URL is not set. In Vercel: Project → Settings → "
                "Environment Variables → add DATABASE_URL (Supabase pooler URI)."
            )
        url = DATABASE_URL
        if str(url).startswith("sqlite"):
            _engine = create_engine(
                url,
                connect_args={"check_same_thread": False},
                pool_pre_ping=True,
            )
        else:
            _engine = create_engine(
                url,
                connect_args=_connect_args(url),
                pool_pre_ping=True,
            )
    return _engine


def _sql_chunk_executable(chunk: str) -> bool:
    for line in chunk.splitlines():
        s = line.strip()
        if s and not s.startswith("--"):
            return True
    return False


def should_run_ensure_schema() -> bool:
    if _running_on_vercel():
        return False
    if os.getenv("CALLIT_SKIP_ENSURE_SCHEMA", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return False
    return True


def ensure_schema(engine):
    dialect = engine.dialect.name
    if dialect == "sqlite":
        name = "schema_sqlite.sql"
    else:
        name = "schema.sql"
    schema_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "db", name)
    )
    if os.path.exists(schema_path):
        with open(schema_path) as f:
            sql = f.read()
        with engine.begin() as conn:
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                if stmt and _sql_chunk_executable(stmt):
                    conn.execute(text(stmt))
    print(f"[db] schema ensured ({dialect})")
