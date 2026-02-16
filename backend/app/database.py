import logging
import os

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.db_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _run_alembic_upgrade():
    """Run alembic upgrade head to apply all pending migrations.

    All migrations are idempotent (check if table/column exists before acting),
    so this safely handles:
    - Fresh DB: creates alembic_version + all tables/columns
    - Legacy DB (no alembic_version): runs all migrations, skips what exists
    - Normal upgrade: applies only new migrations
    """
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    alembic_ini = os.path.join(backend_dir, "alembic.ini")

    alembic_cfg = Config(alembic_ini)
    # Override DB URL to match runtime config (sync driver for Alembic)
    sync_url = f"sqlite:///{settings.db_path}"
    alembic_cfg.set_main_option("sqlalchemy.url", sync_url)

    command.upgrade(alembic_cfg, "head")
    logger.info("Database migrations applied successfully")


async def init_db():
    from app.models import (  # noqa: F401
        analysis_result,
        bell_sample,
        chapter,
        event,
        library,
        match,
        promotion,
        scrape_cache,
        video_item,
        wrestler,
    )

    # Ensure data directory exists
    settings.db_dir.mkdir(parents=True, exist_ok=True)

    # Run Alembic migrations (handles fresh, legacy, and normal upgrades)
    _run_alembic_upgrade()


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session
