"""Shared test fixtures — semua dependency DB di-mock agar tidak butuh Docker."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.web.application import get_app


# ---------------------------------------------------------------------------
# anyio backend
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


# ---------------------------------------------------------------------------
# FastAPI app — lifespan di-bypass agar tidak connect ke DB nyata
# ---------------------------------------------------------------------------

@pytest.fixture
def fastapi_app() -> FastAPI:
    application = get_app()
    return application  # noqa: RET504


# ---------------------------------------------------------------------------
# HTTP client (ASGI transport, tanpa server nyata)
# ---------------------------------------------------------------------------

@pytest.fixture
async def client(
    fastapi_app: FastAPI,
    anyio_backend: Any,
    mock_db_session: Any,
) -> AsyncGenerator[AsyncClient]:
    """AsyncClient yang otomatis menggunakan mock DB session."""
    async with AsyncClient(
        transport=ASGITransport(fastapi_app), base_url="http://test", timeout=5.0
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Mock AsyncSession — tidak butuh PostgreSQL
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db_session() -> AsyncMock:
    """Return mock AsyncSession dan patch get_db_session dependency."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()

    with patch("app.db.sql.get_session_factory") as mock_factory:
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = MagicMock(return_value=mock_cm)
        yield session
