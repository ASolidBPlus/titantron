"""Shared helpers for idempotent Alembic migrations."""

from alembic import op
from sqlalchemy import inspect


def table_exists(name: str) -> bool:
    conn = op.get_bind()
    return name in inspect(conn).get_table_names()


def column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    if table not in inspect(conn).get_table_names():
        return False
    return column in {c["name"] for c in inspect(conn).get_columns(table)}
