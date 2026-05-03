from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.settings import settings

_mongo_client: AsyncIOMotorClient | None = None  # type: ignore[type-arg]


def get_mongo_client() -> AsyncIOMotorClient:  # type: ignore[type-arg]
    if _mongo_client is None:
        msg = "MongoDB client is not initialized. Call connect_mongo() first."
        raise RuntimeError(msg)
    return _mongo_client


def get_mongo_db() -> AsyncIOMotorDatabase:  # type: ignore[type-arg]
    return get_mongo_client()[settings.mongo_db]


async def connect_mongo() -> None:
    global _mongo_client  # noqa: PLW0603
    if settings.mongo_user and settings.mongo_pass:
        _mongo_client = AsyncIOMotorClient(
            host=settings.mongo_host,
            port=settings.mongo_port,
            username=settings.mongo_user,
            password=settings.mongo_pass,
            authSource="admin",
        )
    else:
        _mongo_client = AsyncIOMotorClient(
            host=settings.mongo_host,
            port=settings.mongo_port,
        )
    await _mongo_client.admin.command("ping")


async def disconnect_mongo() -> None:
    global _mongo_client  # noqa: PLW0603
    if _mongo_client is not None:
        _mongo_client.close()
        _mongo_client = None
