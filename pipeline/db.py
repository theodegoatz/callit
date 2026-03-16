# pipeline/db.py — Shared database connection helper
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/callit",
)


def get_engine():
    return create_engine(DATABASE_URL)


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
