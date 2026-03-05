from collections.abc import AsyncGenerator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.web.application import get_app


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def fastapi_app() -> FastAPI:
    application = get_app()
    return application  # noqa: RET504


@pytest.fixture
async def client(
    fastapi_app: FastAPI, anyio_backend: Any
) -> AsyncGenerator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(fastapi_app), base_url="http://test", timeout=2.0
    ) as ac:
        yield ac
