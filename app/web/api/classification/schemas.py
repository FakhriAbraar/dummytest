from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ClassifyRequest(BaseModel):
    content_id: int
    agent_id: int
    kategori_tebakan_ai: str = Field(
        ..., description="Kategori mentah dari AI: SAFE / Pornography_Ringan / Violence / dll"
    )
    reasoning_category: str | None = None
    unsafe_reason: str | None = None
    confidence_score: float = Field(..., ge=0.0, le=1.0)


class ClassifyResponse(BaseModel):
    classification_id: int
    content_id: int
    agent_id: int
    kategori_tebakan_ai: str | None
    reasoning_category: str | None
    unsafe_reason: str | None
    confidence_score: float | None
    classification_timestamp: datetime | None

    model_config = {"from_attributes": True}


class ClassificationDetail(BaseModel):
    classification_id: int
    content_id: int
    agent_id: int
    kategori_tebakan_ai: str | None
    reasoning_category: str | None
    unsafe_reason: str | None
    confidence_score: float | None
    classification_timestamp: datetime | None

    model_config = {"from_attributes": True}
