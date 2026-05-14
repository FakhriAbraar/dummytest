from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.db.tables import AiAgent, Classification, Content, EngineDecision
from app.services.classification import get_igrs_rule_by_kategori
from app.services.resolver import resolve_ai_conflict

_TEXT_AGENT_TYPE = "keyword_model"
_VISUAL_AGENT_TYPE = "classifier"


async def run_engine_decision(
    content_id: int, session: AsyncSession
) -> EngineDecision:
    rows = (
        await session.execute(
            select(Classification, AiAgent)
            .join(AiAgent, Classification.agent_id == AiAgent.agent_id)
            .where(Classification.content_id == content_id)
        )
    ).all()

    tim1 = next((clf for clf, ag in rows if ag.agent_type == _TEXT_AGENT_TYPE), None)
    tim3 = next((clf for clf, ag in rows if ag.agent_type == _VISUAL_AGENT_TYPE), None)

    dict_tim1 = {
        "kategori": tim1.kategori_tebakan_ai or "SAFE" if tim1 else "SAFE",
        "predicted_rating": None,
        "confidence_score": float(tim1.confidence_score or 0.0) if tim1 else 0.0,
        "reason": (tim1.unsafe_reason or tim1.reasoning_category or "Tidak ada teks") if tim1 else "",
    }

    dict_tim3 = {
        "kategori": tim3.kategori_tebakan_ai or "SAFE" if tim3 else "SAFE",
        "predicted_rating": None,
        "confidence_score": float(tim3.confidence_score or 0.0) if tim3 else 0.0,
        "reason": (tim3.unsafe_reason or tim3.reasoning_category or "Tidak ada visual") if tim3 else "",
    }

    # PRE-RESOLVER: MENENTUKAN DAKWAAN UTAMA
    if dict_tim1["kategori"] == "SAFE" and dict_tim3["kategori"] == "SAFE":
        kategori_suspect = "SAFE"
    elif dict_tim1["kategori"] == "SAFE":
        kategori_suspect = str(dict_tim3["kategori"])
    elif dict_tim3["kategori"] == "SAFE":
        kategori_suspect = str(dict_tim1["kategori"])
    else:
        # Dual Violation: Adu Confidence
        tim3_conf: float = float(tim3.confidence_score or 0.0) if tim3 else 0.0
        tim1_conf: float = float(tim1.confidence_score or 0.0) if tim1 else 0.0
        kategori_suspect = str(dict_tim3["kategori"]) if tim3_conf > tim1_conf else str(dict_tim1["kategori"])

    rule_suspect = await get_igrs_rule_by_kategori(kategori_suspect, session)

    dict_rule = {
        "dominant_modality": rule_suspect.dominant_modality if rule_suspect else "EQUAL",
        "age_rating_minimal": rule_suspect.age_rating_minimal if rule_suspect else "SU",
    }

    final_decision = resolve_ai_conflict(
        text_result=dict_tim1,
        visual_result=dict_tim3,
        igrs_rule=dict_rule,
    )

    final_rule = await get_igrs_rule_by_kategori(final_decision["kategori_final"], session)

    engine_status = "NEEDS_REVIEW" if final_decision["rating_final"] == "UNRATED" else "PROCESSED"

    existing = (
        await session.execute(
            select(EngineDecision).where(EngineDecision.content_id == content_id)
        )
    ).scalars().first()

    if existing is None:
        decision = EngineDecision(
            content_id=content_id,
            igrs_rule_id=final_rule.id if final_rule else None,
            final_kategori=final_decision["kategori_final"],
            final_rating=final_decision["rating_final"],
            is_vetoed=final_decision["veto_applied"],
            decided_at=datetime.now(timezone.utc),
        )
        session.add(decision)
    else:
        existing.igrs_rule_id = final_rule.id if final_rule else None
        existing.final_kategori = final_decision["kategori_final"]
        existing.final_rating = final_decision["rating_final"]
        existing.is_vetoed = final_decision["veto_applied"]
        existing.decided_at = datetime.now(timezone.utc)
        decision = existing

    content_row = await session.get(Content, content_id)
    if content_row:
        content_row.engine_status = engine_status
        content_row.final_rating = final_decision["rating_final"]

    await session.commit()
    await session.refresh(decision)

    return decision


async def get_engine_decision(
    content_id: int, session: AsyncSession
) -> EngineDecision | None:
    result = await session.execute(
        select(EngineDecision)
        .where(EngineDecision.content_id == content_id)
        .options(joinedload(EngineDecision.igrs_rule))
    )
    return result.scalars().first()
