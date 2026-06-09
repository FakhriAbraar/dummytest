"""Seeder tabel ``parent_advice`` (saran untuk orang tua per rating usia).

Sumber data: ``app/seeds/data/parent_advice.json`` (dummysaran.json dari tim konten).
Rating pada file sumber memakai skala 0-18 (Semua Umur / 3+ / 7+ / 13+ / 15+ / 18+),
sedangkan sistem PAD memakai skala SU / 7+ / 13+ / 17+ / PRC. Mapping di bawah
menormalisasi skala sumber ke skala sistem agar lookup-nya cukup
``WHERE rating = <rating_final>``.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.tables import ParentAdvice
from app.settings import settings

# Skala dummysaran -> skala rating sistem (SU/7+/13+/17+/PRC).
RATING_MAP: dict[str, str] = {
    "Semua Umur": "SU",
    "3+": "SU",
    "7+": "7+",
    "13+": "13+",
    "15+": "17+",
    "18+": "PRC",
}

_DATA_PATH = Path(__file__).resolve().parent / "data" / "parent_advice.json"


def _load_rows() -> list[dict[str, str]]:
    """Baca JSON sumber -> list {rating(system), saran}. Rating tak dikenal dilewati."""
    raw = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    rows: list[dict[str, str]] = []
    for item in raw:
        saran = (item.get("saran") or "").strip()
        src_rating = (item.get("rating umur") or item.get("rating") or "").strip()
        if not saran:
            continue
        system_rating = RATING_MAP.get(src_rating)
        if not system_rating:
            print(f"parent_advice seeder: rating tidak dikenal '{src_rating}', dilewati.")  # noqa: T201
            continue
        rows.append({"rating": system_rating, "saran": saran})
    return rows


async def seed_parent_advice(session: AsyncSession) -> None:
    rows = _load_rows()
    inserted = skipped = 0
    for row in rows:
        existing = await session.execute(
            select(ParentAdvice).where(ParentAdvice.saran == row["saran"])
        )
        if existing.scalars().first() is not None:
            skipped += 1
            continue
        session.add(ParentAdvice(rating=row["rating"], saran=row["saran"]))
        inserted += 1
    await session.commit()
    print(f"parent_advice seeder: {inserted} inserted, {skipped} skipped.")  # noqa: T201


async def main() -> None:
    engine = create_async_engine(str(settings.postgres_url), echo=False)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    # create_all idempoten — bikin tabel parent_advice bila belum ada.
    async with engine.begin() as conn:
        from app.db.sql import Base

        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        await seed_parent_advice(session)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
