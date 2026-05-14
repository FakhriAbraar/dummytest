"""Create all database tables from SQLAlchemy models."""
from __future__ import annotations

import asyncio

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.sql import Base
from app.settings import settings


def create_all_tables_sync() -> None:
    """Create all tables synchronously."""
    # Create sync engine by replacing asyncpg with psycopg
    sync_url = str(settings.postgres_url).replace("postgresql+asyncpg://", "postgresql+psycopg://")
    engine = create_engine(sync_url, echo=False)
    Base.metadata.create_all(engine)
    engine.dispose()
    print("[OK] All tables created successfully!")  # noqa: T201


async def create_all_tables_async() -> None:
    """Create all tables asynchronously."""
    engine = create_async_engine(str(settings.postgres_url), echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("[OK] All tables created successfully!")  # noqa: T201


if __name__ == "__main__":
    try:
        create_all_tables_sync()
    except Exception as e:
        print(f"[ERROR] {e}")  # noqa: T201