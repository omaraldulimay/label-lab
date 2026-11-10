"""PostgreSQL: Produkte und Ergebnisse (Docker, Port 5442)."""
import os

import psycopg
from psycopg.types.json import Jsonb

DSN = os.environ.get("DATABASE_URL", "postgresql://labellab:labellab@localhost:5442/labellab")

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    code text PRIMARY KEY,
    data jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS results (
    code text PRIMARY KEY REFERENCES products(code) ON DELETE CASCADE,
    status text NOT NULL,
    result jsonb NOT NULL,
    checked_at timestamptz NOT NULL DEFAULT now()
);
"""


def connect():
    return psycopg.connect(DSN)


def init_db() -> None:
    with connect() as conn:
        conn.execute(SCHEMA)


def save_products(products: list[dict]) -> int:
    with connect() as conn:
        for p in products:
            conn.execute("INSERT INTO products (code, data) VALUES (%s, %s) "
                         "ON CONFLICT (code) DO UPDATE SET data = EXCLUDED.data",
                         (p["code"], Jsonb(p)))
    return len(products)


def get_product(code: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT data FROM products WHERE code = %s", (code,)).fetchone()
    return row[0] if row else None


def all_products() -> list[dict]:
    with connect() as conn:
        return [r[0] for r in conn.execute("SELECT data FROM products ORDER BY code")]


def save_result(result: dict) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO results (code, status, result) VALUES (%s, %s, %s) "
                     "ON CONFLICT (code) DO UPDATE SET status = EXCLUDED.status, "
                     "result = EXCLUDED.result, checked_at = now()",
                     (result["code"], result["status"], Jsonb(result)))


def get_result(code: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT result FROM results WHERE code = %s", (code,)).fetchone()
    return row[0] if row else None


def all_results() -> list[dict]:
    with connect() as conn:
        return [r[0] for r in conn.execute("SELECT result FROM results ORDER BY code")]
