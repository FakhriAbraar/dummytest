from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class IGRSRuleOut(BaseModel):
    id: int
    kategori_ai: str
    age_rating_minimal: str
    dominant_modality: str

    model_config = {"from_attributes": True}


class ClassifyRequest(BaseModel):
    content_id: int
    agent_id: int
    kategori_ai: str = Field(
        ...,
        description="Kategori hasil AI: SAFE / Pornography_Ringan / Violence / dll",
    )
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    unsafe_reason: str | None = None
    regulation_id: int | None = None


class ClassifyResponse(BaseModel):
    classification_id: int
    content_id: int
    category: str = Field(..., description="SAFE / UNSAFE")
    reasoning_category: str | None
    unsafe_reason: str | None
    igrs_rule: IGRSRuleOut
    confidence_score: float | None
    classification_timestamp: datetime | None

    model_config = {"from_attributes": True}


class ClassificationDetail(BaseModel):
    classification_id: int
    content_id: int
    agent_id: int
    category: str | None
    reasoning_category: str | None
    unsafe_reason: str | None
    igrs_rule: IGRSRuleOut
    confidence_score: float | None
    classification_timestamp: datetime | None

    model_config = {"from_attributes": True}
