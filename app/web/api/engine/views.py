from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.sql import get_db_session
from app.models.models import Content
from app.services.engine import get_engine_decision, run_engine_decision
from app.web.api.engine.schemas import ContentEngineStatus, EngineDecisionOut, IGRSRuleOut

router = APIRouter(prefix="/engine", tags=["engine"])

DB = Annotated[AsyncSession, Depends(get_db_session)]


@router.post(
    "/decide/{content_id}",
    response_model=EngineDecisionOut,
    status_code=status.HTTP_200_OK,
)
async def decide(content_id: int, session: DB) -> EngineDecisionOut:
    content = await session.get(Content, content_id)
    if content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Content {content_id} tidak ditemukan.",
        )
    decision = await run_engine_decision(content_id, session)
    await session.refresh(decision, ["igrs_rule"])
    return EngineDecisionOut(
        id=decision.id,
        content_id=decision.content_id,
        final_kategori=decision.final_kategori,
        final_rating=decision.final_rating,
        is_vetoed=decision.is_vetoed,
        decided_at=decision.decided_at,
        igrs_rule=IGRSRuleOut.model_validate(decision.igrs_rule)
        if decision.igrs_rule
        else None,
    )


@router.get("/{content_id}", response_model=ContentEngineStatus)
async def get_status(content_id: int, session: DB) -> ContentEngineStatus:
    content = await session.get(Content, content_id)
    if content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Content {content_id} tidak ditemukan.",
        )
    decision = await get_engine_decision(content_id, session)
    decision_out: EngineDecisionOut | None = None
    if decision:
        decision_out = EngineDecisionOut(
            id=decision.id,
            content_id=decision.content_id,
            final_kategori=decision.final_kategori,
            final_rating=decision.final_rating,
            is_vetoed=decision.is_vetoed,
            decided_at=decision.decided_at,
            igrs_rule=IGRSRuleOut.model_validate(decision.igrs_rule)
            if decision.igrs_rule
            else None,
        )
    return ContentEngineStatus(
        content_id=content_id,
        engine_status=content.engine_status,
        final_rating=content.final_rating,
        decision=decision_out,
    )
