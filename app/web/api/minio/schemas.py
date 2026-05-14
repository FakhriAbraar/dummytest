from __future__ import annotations

from pydantic import BaseModel, Field


class MinioUploadFileResponse(BaseModel):
    message: str
    file: str
    path: str = Field(..., description="Path to the uploaded file in MinIO bucket")