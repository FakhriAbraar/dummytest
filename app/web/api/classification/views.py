from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.sql import get_db_session
from app.services.classification import (
    classify_content,
    get_classification,
    get_classifications_for_content,
)
from app.web.api.classification.schemas import (
    ClassificationDetail,
    ClassifyRequest,
    ClassifyResponse,
    IGRSRuleOut,
)

router = APIRouter(prefix="/classification", tags=["classification"])

DB = Annotated[AsyncSession, Depends(get_db_session)]


@router.post(
    "/classify",
    response_model=ClassifyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def classify_content_endpoint(
    payload: ClassifyRequest,
    session: DB,
) -> ClassifyResponse:
    try:
        record = await classify_content(
            content_id=payload.content_id,
            agent_id=payload.agent_id,
            kategori_ai=payload.kategori_ai,
            confidence_score=payload.confidence_score,
            unsafe_reason=payload.unsafe_reason,
            regulation_id=payload.regulation_id,
            session=session,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    await session.refresh(record, ["igrs_rule"])
    return ClassifyResponse(
        classification_id=record.classification_id,
        content_id=record.content_id,
        category=record.category or "",
        reasoning_category=record.reasoning_category,
        unsafe_reason=record.unsafe_reason,
        igrs_rule=IGRSRuleOut.model_validate(record.igrs_rule),
        confidence_score=record.confidence_score,
        classification_timestamp=record.classification_timestamp,
    )


@router.get("/{classification_id}", response_model=ClassificationDetail)
async def get_classification_endpoint(
    classification_id: int,
    session: DB,
) -> ClassificationDetail:
    record = await get_classification(classification_id, session)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Classification {classification_id} tidak ditemukan.",
        )
    await session.refresh(record, ["igrs_rule"])
    return ClassificationDetail(
        classification_id=record.classification_id,
        content_id=record.content_id,
        agent_id=record.agent_id,
        category=record.category,
        reasoning_category=record.reasoning_category,
        unsafe_reason=record.unsafe_reason,
        igrs_rule=IGRSRuleOut.model_validate(record.igrs_rule),
        confidence_score=record.confidence_score,
        classification_timestamp=record.classification_timestamp,
    )


@router.get("/content/{content_id}", response_model=list[ClassificationDetail])
async def get_content_classifications(
    content_id: int,
    session: DB,
) -> list[ClassificationDetail]:
    records = await get_classifications_for_content(content_id, session)
    result = []
    for record in records:
        await session.refresh(record, ["igrs_rule"])
        result.append(
            ClassificationDetail(
                classification_id=record.classification_id,
                content_id=record.content_id,
                agent_id=record.agent_id,
                category=record.category,
                reasoning_category=record.reasoning_category,
                unsafe_reason=record.unsafe_reason,
                igrs_rule=IGRSRuleOut.model_validate(record.igrs_rule),
                confidence_score=record.confidence_score,
                classification_timestamp=record.classification_timestamp,
            )
        )
    return result
