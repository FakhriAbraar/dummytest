from __future__ import annotations

from fastapi import UploadFile
import io
import asyncio
from datetime import timedelta

from minio.error import S3Error
from minio.commonconfig import CopySource

from app.settings import settings

from app.db.minio import get_minio_client

async def create_bucket(
    *,
    bucket_name: str,
)->bool:
    """Create a new bucket"""
    minio_client = get_minio_client()
    found = await asyncio.to_thread(minio_client.bucket_exists, bucket_name)
    if not found:
        await asyncio.to_thread(minio_client.make_bucket, bucket_name)
    return found

async def list_buckets()->list[str]:
    """List all buckets"""
    minio_client = get_minio_client()
    buckets = await asyncio.to_thread(minio_client.list_buckets)
    return [bucket.name for bucket in buckets]

async def upload_file(
    *,
    file: UploadFile
) -> dict:
    """Upload file"""
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
            "path": object_name
        }
    except S3Error as e:
        print("Upload stream gagal:", e)
        return {
            "status": "error",
            "message": str(e),
        }


async def delete_bucket(
    *,
    bucket_name: str
):
    """Delete bucket"""
    minio_client = get_minio_client()

    found = await asyncio.to_thread(minio_client.bucket_exists, bucket_name)
    if found:
        await asyncio.to_thread(minio_client.remove_bucket, bucket_name)
    return found

async def save_from_local(
    *,
    source: str,
    destination: str
)-> dict:
    """Save to minio from local path for crawler"""
    minio_client = get_minio_client()

    try: 
        await asyncio.to_thread(
            minio_client.fput_object,
            bucket_name=settings.minio_bucket,
            object_name=destination,
            file_path=source
        )
        return {
            "status": "success",
            "message": "save from local berhasil",
            "file": source,
            "path": destination
        }
    except S3Error as e:
        print("Upload local gagal:", e)
        return {
            "status": "error",
            "message": str(e)
        }
    

async def move_file(*, source: str, destination: str)->dict:
    minio_client = get_minio_client()
    bucket = settings.minio_bucket

    try:
        # copy object (clone)
        await asyncio.to_thread(
            minio_client.copy_object,
            bucket_name=bucket,
            object_name=destination,
            source=CopySource(bucket, source)
        )

        # delete source object
        await asyncio.to_thread(
            minio_client.remove_object,
            bucket_name=bucket,
            object_name=source
        )

        return {
            "status": "success",
            "source": source,
            "destination": destination,
            "bucket": bucket
        }

    except S3Error as e:
        return {
            "status": "error",
            "message": str(e)
        }
    

async def get_presigned_url(object_name: str, time_to_expire: int=3600)->dict:
    minio_client = get_minio_client()

    try:
        url = minio_client.presigned_get_object(
            bucket_name=settings.minio_bucket,
            object_name=object_name,
            expires=timedelta(seconds=time_to_expire)  # 1 jam
        )
        return {
            "status": "success",
            "message": "object berhasil ditemukan",
            "url": url
        }
    
    except S3Error as e:
        return {
            "status": "error",
            "message": str(e)
        }