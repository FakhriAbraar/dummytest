from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Classification, IGRSRules

_SAFE_RATINGS: frozenset[str] = frozenset({"SU", "7+"})

_igrs_cache: dict[str, IGRSRules] = {}


def _determine_category(rule: IGRSRules) -> str:
    if rule.kategori_ai == "SAFE":
        return "SAFE"
    return "SAFE" if rule.age_rating_minimal in _SAFE_RATINGS else "UNSAFE"


async def load_igrs_cache(session: AsyncSession) -> None:
    result = await session.execute(select(IGRSRules))
    rules = result.scalars().all()
    _igrs_cache.clear()
    for rule in rules:
        _igrs_cache[rule.kategori_ai] = rule


async def _get_igrs_rule(kategori_ai: str, session: AsyncSession) -> IGRSRules | None:
    if kategori_ai in _igrs_cache:
        return _igrs_cache[kategori_ai]
    result = await session.execute(
        select(IGRSRules).where(IGRSRules.kategori_ai == kategori_ai)
    )
    rule = result.scalars().first()
    if rule:
        _igrs_cache[kategori_ai] = rule
    return rule


async def classify_content(
    *,
    content_id: int,
    agent_id: int,
    kategori_ai: str,
    confidence_score: float,
    unsafe_reason: str | None,
    regulation_id: int | None = None,
    session: AsyncSession,
) -> Classification:
    rule = await _get_igrs_rule(kategori_ai, session)
    if rule is None:
        raise ValueError(
            f"kategori_ai '{kategori_ai}' tidak ditemukan di igrs_rules."
        )

    category = _determine_category(rule)
    record = Classification(
        content_id=content_id,
        agent_id=agent_id,
        igrs_rule_id=rule.id,
        regulation_id=regulation_id,
        category=category,
        reasoning_category=kategori_ai,
        unsafe_reason=unsafe_reason if category == "UNSAFE" else None,
        confidence_score=confidence_score,
        classification_timestamp=datetime.now(timezone.utc),
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def get_classification(
    classification_id: int,
    session: AsyncSession,
) -> Classification | None:
    result = await session.execute(
        select(Classification).where(
            Classification.classification_id == classification_id
        )
    )
    return result.scalars().first()


async def get_classifications_for_content(
    content_id: int,
    session: AsyncSession,
) -> list[Classification]:
    result = await session.execute(
        select(Classification).where(Classification.content_id == content_id)
    )
    return list(result.scalars().all())
