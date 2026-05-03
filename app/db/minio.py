from __future__ import annotations

from minio import Minio

from app.settings import settings

_minio_client: Minio | None = None


def get_minio_client() -> Minio:
    """Mengambil instance MinIO client."""
    if _minio_client is None:
        msg = "MinIO client is not initialized. Call connect_minio() first."
        raise RuntimeError(msg)
    return _minio_client


async def connect_minio() -> None:
    """Menginisialisasi MinIO client dan memastikan default bucket tersedia."""
    global _minio_client

    _minio_client = Minio(
        endpoint=f"{settings.minio_host}:{settings.minio_port}",
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_use_ssl,
    )

    found = _minio_client.bucket_exists(settings.minio_bucket)
    if not found:
        _minio_client.make_bucket(settings.minio_bucket)


async def disconnect_minio() -> None:
    """Membersihkan instance MinIO client."""
    global _minio_client
    
    _minio_client = None