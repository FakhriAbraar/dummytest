from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.models import AiAgent, Classification, Content, EngineDecision, IGRSRules
from app.services.classification import get_igrs_rule_by_kategori

CONFIDENCE_THRESHOLD = 0.75

_TEXT_AGENT_TYPE = "keyword_model"
_VISUAL_AGENT_TYPE = "classifier"

_SAFE_RATINGS: frozenset[str] = frozenset({"SU"})


def _engine_status_from_rule(rule: IGRSRules | None) -> str:
    if rule is None:
        return "ANOMALY"
    if rule.kategori_ai == "SAFE" or rule.age_rating_minimal in _SAFE_RATINGS:
        return "SAFE"
    return "VIOLATION"


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

    tim1 = next(
        (clf for clf, ag in rows if ag.agent_type == _TEXT_AGENT_TYPE), None
    )
    tim3 = next(
        (clf for clf, ag in rows if ag.agent_type == _VISUAL_AGENT_TYPE), None
    )

    tim1_ok = tim1 is not None and (tim1.confidence_score or 0.0) >= CONFIDENCE_THRESHOLD
    tim3_ok = tim3 is not None and (tim3.confidence_score or 0.0) >= CONFIDENCE_THRESHOLD

    winning_clf: Classification | None = None
    engine_status: str

    if not tim1_ok and not tim3_ok:
        engine_status = "NEEDS_REVIEW"
    else:
        if tim1_ok and tim3_ok:
            rule3 = await get_igrs_rule_by_kategori(
                tim3.kategori_tebakan_ai or "", session
            )
            rule1 = await get_igrs_rule_by_kategori(
                tim1.kategori_tebakan_ai or "", session
            )
            mod3 = rule3.dominant_modality if rule3 else "VISUAL"
            mod1 = rule1.dominant_modality if rule1 else "TEXT"

            if mod3 == "VISUAL" and mod1 != "VISUAL":
                winning_clf = tim3
            elif mod1 == "TEXT" and mod3 != "TEXT":
                winning_clf = tim1
            else:
                winning_clf = (
                    tim3
                    if (tim3.confidence_score or 0.0) >= (tim1.confidence_score or 0.0)
                    else tim1
                )
        elif tim3_ok:
            winning_clf = tim3
        else:
            winning_clf = tim1

        rule = await get_igrs_rule_by_kategori(
            winning_clf.kategori_tebakan_ai or "", session  # type: ignore[union-attr]
        )
        engine_status = _engine_status_from_rule(rule)

    rule = (
        await get_igrs_rule_by_kategori(
            winning_clf.kategori_tebakan_ai or "", session
        )
        if winning_clf
        else None
    )
    final_rating = rule.age_rating_minimal if rule else None
    final_kategori = winning_clf.kategori_tebakan_ai if winning_clf else None

    existing = (
        await session.execute(
            select(EngineDecision).where(EngineDecision.content_id == content_id)
        )
    ).scalars().first()

    if existing is None:
        decision = EngineDecision(
            content_id=content_id,
            igrs_rule_id=rule.id if rule else None,
            final_kategori=final_kategori,
            final_rating=final_rating,
            is_vetoed=False,
            decided_at=datetime.now(timezone.utc),
        )
        session.add(decision)
    else:
        existing.igrs_rule_id = rule.id if rule else None
        existing.final_kategori = final_kategori
        existing.final_rating = final_rating
        existing.decided_at = datetime.now(timezone.utc)
        decision = existing

    content_row = await session.get(Content, content_id)
    if content_row:
        content_row.engine_status = engine_status
        content_row.final_rating = final_rating

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
