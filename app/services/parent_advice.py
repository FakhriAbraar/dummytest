"""Lookup saran orang tua berdasarkan rating final Content Checker.

Data ``parent_advice`` bersifat statis (hasil seed) sehingga di-cache di memori
sekali, lalu pemilihan acak dilakukan in-process tanpa query DB tiap request.
"""
from __future__ import annotations

import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import ParentAdvice

# rating(system) -> daftar saran
_advice_cache: dict[str, list[str]] = {}
_loaded = False

# Rating final yang butuh peninjauan manual / tak dikenal -> jatuhkan ke SU.
_FALLBACK_RATING = "SU"


async def _ensure_cache(session: AsyncSession) -> None:
    global _loaded
    if _loaded and _advice_cache:
        return
    rows = (await session.execute(select(ParentAdvice))).scalars().all()
    _advice_cache.clear()
    for r in rows:
        if r.rating and r.saran:
            _advice_cache.setdefault(r.rating, []).append(r.saran)
    _loaded = True


def _pick(rating: str | None) -> str | None:
    pool = _advice_cache.get((rating or "").strip()) or _advice_cache.get(_FALLBACK_RATING)
    return random.choice(pool) if pool else None


async def get_random_parent_advice(rating: str | None, session: AsyncSession) -> str | None:
    """Satu saran acak untuk ``rating`` (skala sistem). None bila tabel kosong."""
    await _ensure_cache(session)
    return _pick(rating)
