from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.mongo import connect_mongo, disconnect_mongo
from app.db.sql import connect_postgres, disconnect_postgres


@asynccontextmanager
async def lifespan_setup(
    app: FastAPI,
) -> AsyncGenerator[None]:  # pragma: no cover
    await connect_postgres()
    await connect_mongo()

    app.middleware_stack = None
    app.middleware_stack = app.build_middleware_stack()

    yield

    await disconnect_mongo()
    await disconnect_postgres()
