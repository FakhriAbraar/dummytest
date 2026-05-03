from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.sql import get_db_session
from app.services.classification import (
    get_classification,
    get_classifications_for_content,
    save_classification,
)
from app.web.api.classification.schemas import (
    ClassificationDetail,
    ClassifyRequest,
    ClassifyResponse,
)

router = APIRouter(prefix="/classification", tags=["classification"])

DB = Annotated[AsyncSession, Depends(get_db_session)]


@router.post("/", response_model=ClassifyResponse, status_code=status.HTTP_201_CREATED)
async def submit_classification(payload: ClassifyRequest, session: DB) -> ClassifyResponse:
    record = await save_classification(
        content_id=payload.content_id,
        agent_id=payload.agent_id,
        kategori_tebakan_ai=payload.kategori_tebakan_ai,
        reasoning_category=payload.reasoning_category,
        unsafe_reason=payload.unsafe_reason,
        confidence_score=payload.confidence_score,
        session=session,
    )
    return ClassifyResponse.model_validate(record)


@router.get("/{classification_id}", response_model=ClassificationDetail)
async def get_classification_endpoint(
    classification_id: int, session: DB
) -> ClassificationDetail:
    record = await get_classification(classification_id, session)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Classification {classification_id} tidak ditemukan.",
        )
    return ClassificationDetail.model_validate(record)


@router.get("/content/{content_id}", response_model=list[ClassificationDetail])
async def get_content_classifications(
    content_id: int, session: DB
) -> list[ClassificationDetail]:
    records = await get_classifications_for_content(content_id, session)
    return [ClassificationDetail.model_validate(r) for r in records]
