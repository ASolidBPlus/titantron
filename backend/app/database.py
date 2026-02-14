import logging

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.db_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _migrate_schema(conn):
    """Apply schema migrations for columns that create_all can't handle.

    SQLAlchemy's create_all only creates new tables — it won't add columns
    to existing tables. This function checks for missing columns and adds
    them via ALTER TABLE. Safe to run repeatedly (idempotent).
    """
    inspector = inspect(conn)

    migrations = [
        # (table, column, sql_type)
        ("libraries", "jellyfin_path", "VARCHAR"),
        ("libraries", "local_path", "VARCHAR"),
    ]

    for table_name, column, sql_type in migrations:
        if table_name not in inspector.get_table_names():
            continue
        existing = {c["name"] for c in inspector.get_columns(table_name)}
        if column not in existing:
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column} {sql_type}"))
            logger.info("Added column %s.%s", table_name, column)


async def init_db():
    from app.models import (  # noqa: F401
        analysis_result,
        chapter,
        event,
        library,
        match,
        promotion,
        scrape_cache,
        video_item,
        wrestler,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_schema)


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session
