from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Classification, IGRSRules

_igrs_cache: dict[str, IGRSRules] = {}


async def load_igrs_cache(session: AsyncSession) -> None:
    result = await session.execute(select(IGRSRules))
    rules = result.scalars().all()
    _igrs_cache.clear()
    for rule in rules:
        _igrs_cache[rule.kategori_ai] = rule


async def get_igrs_rule_by_kategori(
    kategori_ai: str, session: AsyncSession
) -> IGRSRules | None:
    if kategori_ai in _igrs_cache:
        return _igrs_cache[kategori_ai]
    result = await session.execute(
        select(IGRSRules).where(IGRSRules.kategori_ai == kategori_ai)
    )
    rule = result.scalars().first()
    if rule:
        _igrs_cache[kategori_ai] = rule
    return rule


async def save_classification(
    *,
    content_id: int,
    agent_id: int,
    kategori_tebakan_ai: str,
    reasoning_category: str | None = None,
    unsafe_reason: str | None = None,
    confidence_score: float,
    session: AsyncSession,
) -> Classification:
    record = Classification(
        content_id=content_id,
        agent_id=agent_id,
        kategori_tebakan_ai=kategori_tebakan_ai,
        reasoning_category=reasoning_category,
        unsafe_reason=unsafe_reason,
        confidence_score=confidence_score,
        classification_timestamp=datetime.now(timezone.utc),
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def get_classification(
    classification_id: int, session: AsyncSession
) -> Classification | None:
    result = await session.execute(
        select(Classification).where(
            Classification.classification_id == classification_id
        )
    )
    return result.scalars().first()


async def get_classifications_for_content(
    content_id: int, session: AsyncSession
) -> list[Classification]:
    result = await session.execute(
        select(Classification).where(Classification.content_id == content_id)
    )
    return list(result.scalars().all())
