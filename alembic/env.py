from __future__ import annotations

import asyncio
import re
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import pool, text

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from app.settings import settings  # noqa: E402
from app.db.sql import Base  # noqa: E402
from app.models import models as _  # noqa: E402, F401

target_metadata = Base.metadata

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")


def run_migrations_offline() -> None:
    url = str(settings.postgres_url)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def ensure_database_exists() -> None:
    if not settings.postgres_admin_pass:
        return

    db_name = settings.postgres_db
    db_user = settings.postgres_user

    if not _SAFE_IDENTIFIER.match(db_name) or not _SAFE_IDENTIFIER.match(db_user):
        print(f"Skipping auto-create: unsafe identifier in db_name='{db_name}'")
        return

    engine = create_async_engine(
        str(settings.postgres_admin_url), isolation_level="AUTOCOMMIT"
    )
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                {"dbname": db_name},
            )
            if not result.scalar():
                print(f"Database '{db_name}' not found — creating...")
                await conn.execute(
                    text(f"CREATE DATABASE {db_name} OWNER {db_user}")
                )
                print(f"Database '{db_name}' created.")
    except Exception as exc:
        print(f"Warning: auto-create DB skipped — {exc}")
    finally:
        await engine.dispose()


async def run_migrations_online() -> None:
    await ensure_database_exists()

    connectable = create_async_engine(
        str(settings.postgres_url),
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
