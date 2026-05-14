from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.tables import IGRSRules
from app.settings import settings

IGRS_DATA: list[dict[str, str]] = [
    {"kategori_ai": "Pornography_Keras",    "age_rating_minimal": "PRC", "dominant_modality": "VISUAL"},
    {"kategori_ai": "Pornography_Ringan",   "age_rating_minimal": "17+", "dominant_modality": "VISUAL"},
    {"kategori_ai": "Animasi_Ringan",       "age_rating_minimal": "SU",  "dominant_modality": "VISUAL"},
    {"kategori_ai": "Animasi_Keras",        "age_rating_minimal": "13+", "dominant_modality": "VISUAL"},
    {"kategori_ai": "SAFE",                 "age_rating_minimal": "SU",  "dominant_modality": "VISUAL"},
    {"kategori_ai": "Drug",                 "age_rating_minimal": "PRC", "dominant_modality": "VISUAL"},
    {"kategori_ai": "Addictive Substances", "age_rating_minimal": "PRC", "dominant_modality": "VISUAL"},
    {"kategori_ai": "Medicine_Ringan",      "age_rating_minimal": "SU",  "dominant_modality": "VISUAL"},
    {"kategori_ai": "Medical_Ringan",       "age_rating_minimal": "7+",  "dominant_modality": "VISUAL"},
    {"kategori_ai": "Weapon_Ringan",        "age_rating_minimal": "17+", "dominant_modality": "VISUAL"},
    {"kategori_ai": "Weapon_Keras",         "age_rating_minimal": "PRC", "dominant_modality": "VISUAL"},
    {"kategori_ai": "Toy_Ringan",           "age_rating_minimal": "7+",  "dominant_modality": "VISUAL"},
    {"kategori_ai": "Toy_Keras",            "age_rating_minimal": "13+", "dominant_modality": "VISUAL"},
    {"kategori_ai": "Terrorism",            "age_rating_minimal": "PRC", "dominant_modality": "VISUAL"},
    {"kategori_ai": "Military_Ringan",      "age_rating_minimal": "7+",  "dominant_modality": "VISUAL"},
    {"kategori_ai": "Military_Keras",       "age_rating_minimal": "13+", "dominant_modality": "VISUAL"},
    {"kategori_ai": "Violence",             "age_rating_minimal": "PRC", "dominant_modality": "VISUAL"},
    {"kategori_ai": "Sport_Ringan",         "age_rating_minimal": "SU",  "dominant_modality": "VISUAL"},
    {"kategori_ai": "Sport_Keras",          "age_rating_minimal": "13+", "dominant_modality": "VISUAL"},
    {"kategori_ai": "SelfHarm",             "age_rating_minimal": "PRC", "dominant_modality": "VISUAL"},
    {"kategori_ai": "Medical_Keras",        "age_rating_minimal": "17+", "dominant_modality": "VISUAL"},
]


async def seed_igrs_rules(session: AsyncSession) -> None:
    inserted = skipped = 0
    for row in IGRS_DATA:
        existing = await session.execute(
            select(IGRSRules).where(
                IGRSRules.kategori_ai == row["kategori_ai"],
                IGRSRules.age_rating_minimal == row["age_rating_minimal"],
                IGRSRules.dominant_modality == row["dominant_modality"],
            )
        )
        if existing.scalars().first() is not None:
            skipped += 1
            continue
        session.add(IGRSRules(**row))
        inserted += 1
    await session.commit()
    print(f"igrs_rules seeder: {inserted} inserted, {skipped} skipped.")  # noqa: T201


async def main() -> None:
    engine = create_async_engine(str(settings.postgres_url), echo=False)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        await seed_igrs_rules(session)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())