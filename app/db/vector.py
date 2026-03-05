
from __future__ import annotations

from qdrant_client import AsyncQdrantClient

from app.settings import settings

_qdrant_client: AsyncQdrantClient | None = None


def get_qdrant_client() -> AsyncQdrantClient:
    if _qdrant_client is None:
        msg = "Qdrant client is not initialized. Call connect_qdrant() first."
        raise RuntimeError(msg)
    return _qdrant_client


async def connect_qdrant() -> None:
    global _qdrant_client  # noqa: PLW0603
    _qdrant_client = AsyncQdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        grpc_port=settings.qdrant_grpc_port,
        https=settings.qdrant_https,
    )
    await _qdrant_client.get_collections()


async def disconnect_qdrant() -> None:
    global _qdrant_client  # noqa: PLW0603
    if _qdrant_client is not None:
        await _qdrant_client.close()
        _qdrant_client = None
