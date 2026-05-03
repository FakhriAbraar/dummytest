from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class IGRSRuleOut(BaseModel):
    id: int
    kategori_ai: str
    age_rating_minimal: str
    dominant_modality: str

    model_config = {"from_attributes": True}


class EngineDecisionOut(BaseModel):
    id: int
    content_id: int
    final_kategori: str | None
    final_rating: str | None
    is_vetoed: bool
    decided_at: datetime | None
    igrs_rule: IGRSRuleOut | None

    model_config = {"from_attributes": True}


class ContentEngineStatus(BaseModel):
    content_id: int
    engine_status: str | None
    final_rating: str | None
    decision: EngineDecisionOut | None
