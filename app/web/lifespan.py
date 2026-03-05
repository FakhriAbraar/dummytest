"""Application lifespan: startup and shutdown hooks."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.mongo import connect_mongo, disconnect_mongo
from app.db.sql import connect_postgres, disconnect_postgres
from app.db.vector import connect_qdrant, disconnect_qdrant


@asynccontextmanager
async def lifespan_setup(
    app: FastAPI,
) -> AsyncGenerator[None]:  # pragma: no cover
    """
    Actions to run on application startup and shutdown.

    Connects to PostgreSQL (SQLAlchemy), MongoDB (Motor),
    and Qdrant on startup; closes all connections on shutdown.

    :param app: the fastAPI application.
    :return: async context manager controlling the lifespan.
    """
    # ── Startup ──────────────────────────────────────────────────
    await connect_postgres()
    await connect_mongo()
    await connect_qdrant()

    app.middleware_stack = None
    app.middleware_stack = app.build_middleware_stack()

    yield

    # ── Shutdown ─────────────────────────────────────────────────
    await disconnect_qdrant()
    await disconnect_mongo()
    await disconnect_postgres()
