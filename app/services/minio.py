from __future__ import annotations

import asyncio
import io
from datetime import timedelta

from fastapi import UploadFile
from minio.commonconfig import CopySource
from minio.error import S3Error

from app.db.minio import get_minio_client
from app.settings import settings


async def create_bucket(*, bucket_name: str) -> bool:
    minio_client = get_minio_client()
    found = await asyncio.to_thread(minio_client.bucket_exists, bucket_name)
    if not found:
        await asyncio.to_thread(minio_client.make_bucket, bucket_name)
    return found


async def list_buckets() -> list[str]:
    minio_client = get_minio_client()
    buckets = await asyncio.to_thread(minio_client.list_buckets)
    return [bucket.name for bucket in buckets]


async def upload_file(*, file: UploadFile) -> dict:
    if not file.filename:
        return {"status": "error", "message": "Nama file tidak boleh kosong."}

    minio_client = get_minio_client()
    file_bytes = await file.read()
    stream = io.BytesIO(file_bytes)
    object_name = f"uploads/{file.filename}"

    try:
        await asyncio.to_thread(
            minio_client.put_object,
            bucket_name=settings.minio_bucket,
            object_name=object_name,
            data=stream,
            length=len(file_bytes),
        )
        return {
            "status": "success",
            "message": "upload berhasil",
            "file": file.filename,
            "path": object_name,
        }
    except S3Error as e:
        print("Upload stream gagal:", e)
        return {"status": "error", "message": str(e)}


async def delete_bucket(*, bucket_name: str) -> bool:
    minio_client = get_minio_client()
    found = await asyncio.to_thread(minio_client.bucket_exists, bucket_name)
    if found:
        await asyncio.to_thread(minio_client.remove_bucket, bucket_name)
    return found


async def save_from_local(*, source: str, destination: str) -> dict:
    minio_client = get_minio_client()
    try:
        await asyncio.to_thread(
            minio_client.fput_object,
            bucket_name=settings.minio_bucket,
            object_name=destination,
            file_path=source,
        )
        return {
            "status": "success",
            "message": "save from local berhasil",
            "file": source,
            "path": destination,
        }
    except S3Error as e:
        print("Upload local gagal:", e)
        return {"status": "error", "message": str(e)}


async def move_file(*, source: str, destination: str) -> dict:
    minio_client = get_minio_client()
    bucket = settings.minio_bucket
    try:
        await asyncio.to_thread(
            minio_client.copy_object,
            bucket_name=bucket,
            object_name=destination,
            source=CopySource(bucket, source),
        )
        await asyncio.to_thread(
            minio_client.remove_object,
            bucket_name=bucket,
            object_name=source,
        )
        return {"status": "success", "source": source, "destination": destination, "bucket": bucket}
    except S3Error as e:
        return {"status": "error", "message": str(e)}


async def get_presigned_url(object_name: str, time_to_expire: int = 3600) -> dict:
    minio_client = get_minio_client()
    try:
        url = await asyncio.to_thread(
            minio_client.presigned_get_object,
            bucket_name=settings.minio_bucket,
            object_name=object_name,
            expires=timedelta(seconds=time_to_expire),
        )
        return {"status": "success", "message": "object berhasil ditemukan", "url": url}
    except S3Error as e:
        return {"status": "error", "message": str(e)}
