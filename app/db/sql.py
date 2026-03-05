"""SQLAlchemy async engine and session management."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.settings import settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""


def get_engine() -> AsyncEngine:
    """
    Return the active SQLAlchemy async engine.

    :raises RuntimeError: if connect_postgres() was not called first.
    :return: AsyncEngine instance.
    """
    if _engine is None:
        msg = "Database engine is not initialized. Call connect_postgres() first."
        raise RuntimeError(msg)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """
    Return the session factory.

    :raises RuntimeError: if connect_postgres() was not called first.
    :return: async_sessionmaker instance.
    """
    if _session_factory is None:
        msg = "Session factory is not initialized. Call connect_postgres() first."
        raise RuntimeError(msg)
    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession]:
    """
    FastAPI dependency that yields a database session per request.

    Usage::

        @router.get("/items")
        async def list_items(session: AsyncSession = Depends(get_db_session)):
            ...

    :yields: AsyncSession for the current request.
    """
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def connect_postgres() -> None:
    """
    Create the SQLAlchemy async engine and session factory.

    Called once on application startup.
    """
    global _engine, _session_factory  # noqa: PLW0603
    _engine = create_async_engine(
        str(settings.postgres_url),
        echo=settings.postgres_echo,
        pool_pre_ping=True,
    )
    _session_factory = async_sessionmaker(
        bind=_engine,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


async def disconnect_postgres() -> None:
    """
    Dispose the SQLAlchemy async engine.

    Called once on application shutdown.
    """
    global _engine, _session_factory  # noqa: PLW0603
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
