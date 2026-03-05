"""Qdrant vector database connection management."""

from __future__ import annotations

from qdrant_client import AsyncQdrantClient

from app.settings import settings

_qdrant_client: AsyncQdrantClient | None = None


def get_qdrant_client() -> AsyncQdrantClient:
    """
    Return the active Qdrant async client.

    :raises RuntimeError: if connect_qdrant() was not called first.
    :return: AsyncQdrantClient instance.
    """
    if _qdrant_client is None:
        msg = "Qdrant client is not initialized. Call connect_qdrant() first."
        raise RuntimeError(msg)
    return _qdrant_client


async def connect_qdrant() -> None:
    """
    Create and cache the Qdrant async client.

    Called once on application startup.
    """
    global _qdrant_client  # noqa: PLW0603
    _qdrant_client = AsyncQdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        grpc_port=settings.qdrant_grpc_port,
        https=settings.qdrant_https,
    )
    # Validate the connection early
    await _qdrant_client.get_collections()


async def disconnect_qdrant() -> None:
    """
    Close the Qdrant async client.

    Called once on application shutdown.
    """
    global _qdrant_client  # noqa: PLW0603
    if _qdrant_client is not None:
        await _qdrant_client.close()
        _qdrant_client = None
