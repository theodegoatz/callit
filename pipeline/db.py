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

_DEFAULT_URL = "postgresql://postgres:postgres@localhost:5432/callit"


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


_raw_database_url = _database_url_from_env_file() or os.getenv(
    "DATABASE_URL", _DEFAULT_URL
)
DATABASE_URL = resolve_database_url(_raw_database_url)

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
        _engine = create_engine(
            DATABASE_URL,
            connect_args=_connect_args(DATABASE_URL),
            pool_pre_ping=True,
        )
    return _engine


def ensure_schema(engine):
    schema_path = os.path.join(os.path.dirname(__file__), "..", "db", "schema.sql")
    schema_path = os.path.normpath(schema_path)
    if os.path.exists(schema_path):
        with open(schema_path) as f:
            sql = f.read()
        with engine.begin() as conn:
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(text(stmt))
    print("[db] schema ensured")
