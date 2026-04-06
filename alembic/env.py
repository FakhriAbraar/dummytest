from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from app.settings import settings  # noqa: E402
from app.db.sql import Base  # noqa: E402
import app.db.models  # noqa: E402, F401 – registers all ORM models with Base.metadata

target_metadata = Base.metadata


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


from sqlalchemy import text

def do_run_migrations(connection):  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def ensure_database_exists() -> None:
    """Check if the database exists and automatically create it if it doesn't."""
    db_url = str(settings.postgres_url)
    db_name = settings.postgres_db
    
    # Use the postgres superuser (as provided by the user) to have CREATEDB privileges
    admin_url = "postgresql+asyncpg://postgres:12345678@localhost:5432/postgres"

    # CREATE DATABASE cannot run inside a transaction block, hence AUTOCOMMIT
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'")
            )
            if not result.scalar():
                print(f"Database '{db_name}' not found. Auto-creating using postgres superuser...")
                await conn.execute(
                    text(f"CREATE DATABASE {db_name} OWNER {settings.postgres_user}")
                )
                print(f"Database '{db_name}' created successfully.")
    except Exception as e:
        print(f"Warning during auto-create DB: {e}")
    finally:
        await engine.dispose()


async def run_migrations_online() -> None:
    # Attempt to auto-create the database if missing
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
