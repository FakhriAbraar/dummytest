from __future__ import annotations

from fastapi import APIRouter, HTTPException, status, UploadFile, File

from app.services.minio import (
    create_bucket,
    delete_bucket,
    list_buckets,
    upload_file,
    get_presigned_url,
)

from app.web.api.minio.schemas import (
    MinioUploadFileResponse,
)

router = APIRouter(prefix="/minio", tags=["minio"])
# @router.get      # READ - ambil data
# @router.post     # CREATE - buat data baru
# @router.put      # UPDATE - replace seluruh data
# @router.patch    # UPDATE - sebagian data
# @router.delete   # DELETE - hapus data
# @router.options  # META - cek allowed methods
# @router.head     # META - header saja (tanpa response body)

@router.get("/health", summary="MinIO Health Check")
def health_check() -> None:
    # """Check if MinIO is healthy"""
    pass


# @router.get("/list-bucket", summary="List all buckets")
async def list_buckets_endpoint() -> list[str]:
    return await list_buckets()


# @router.post("/create-bucket/{bucket_name}", summary="Create bucket", status_code=status.HTTP_201_CREATED)
async def create_bucket_endpoint(
    bucket_name: str,
) -> str:
    # """Create bucket"""
    response = await create_bucket(bucket_name=bucket_name)
    return str(response)
    # response = True kalau sudah ada bucketnya sebelum di create
    # response = False kalau bucket baru di buat


# @router.delete("/delete-bucket/{bucket_name}", summary="Delete bucket")
async def delete_bucket_endpoint(
    bucket_name: str,
) -> str:
    # """Delete bucket"""
    response = await delete_bucket(bucket_name=bucket_name)
    if not response:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bucket {bucket_name} tidak ditemukan.",
        )
    return str(response)
    # response = True kalau berhasil delete bucket
    # response = False kalau bucket tidak ada


@router.post("/upload", summary="Upload file", response_model=MinioUploadFileResponse)
async def upload_file_endpoint(
    file: UploadFile = File(...),
) -> MinioUploadFileResponse:
    response = await upload_file(file=file)

    if response.get("status") == "error":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=response.get("message", "Upload gagal."),
        )

    return MinioUploadFileResponse.model_validate(response)

@router.get("/images/{object_name:path}", summary="get presigned url from an object")
async def get_image_presigned_url_endpoint(
    object_name: str,
    time_to_expire: int = 3600
) -> dict:
    response = await get_presigned_url(object_name, time_to_expire)

    return response
    