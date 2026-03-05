"""MongoDB connection management using Motor (async driver)."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.settings import settings

_mongo_client: AsyncIOMotorClient | None = None  # type: ignore[type-arg]


def get_mongo_client() -> AsyncIOMotorClient:  # type: ignore[type-arg]
    """
    Return the active Motor client.

    :raises RuntimeError: if connect_mongo() was not called first.
    :return: AsyncIOMotorClient instance.
    """
    if _mongo_client is None:
        msg = "MongoDB client is not initialized. Call connect_mongo() first."
        raise RuntimeError(msg)
    return _mongo_client


def get_mongo_db() -> AsyncIOMotorDatabase:  # type: ignore[type-arg]
    """
    Return the active Motor database.

    :return: AsyncIOMotorDatabase instance.
    """
    return get_mongo_client()[settings.mongo_db]


async def connect_mongo() -> None:
    """
    Create and cache the MongoDB Motor client.

    Called once on application startup.
    """
    global _mongo_client  # noqa: PLW0603
    _mongo_client = AsyncIOMotorClient(str(settings.mongo_url))
    # Trigger a lightweight command to validate connectivity early
    await _mongo_client.admin.command("ping")


async def disconnect_mongo() -> None:
    """
    Close the MongoDB Motor client.

    Called once on application shutdown.
    """
    global _mongo_client  # noqa: PLW0603
    if _mongo_client is not None:
        _mongo_client.close()
        _mongo_client = None
