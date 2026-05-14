"""Extended seeder — adds 500 content items with realistic 30-day distribution for chart data."""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.tables import (
    Account,
    AiAgent,
    Classification,
    Content,
    ContentKeyword,
    EngineDecision,
    IGRSRules,
    Platform,
    RegulationDocument,
    TrendingKeyword,
)
from app.settings import settings

TOTAL_CONTENT = 500

AGE_RATING_MAP = {
    "SAFE": "SU",
    "Animasi_Ringan": "SU",
    "Sport_Ringan": "SU",
    "Medicine_Ringan": "SU",
    "Toy_Ringan": "7+",
    "Animasi_Keras": "13+",
    "Military_Keras": "13+",
    "Sport_Keras": "13+",
    "Toy_Keras": "13+",
    "Medical_Ringan": "7+",
    "Military_Ringan": "7+",
    "Weapon_Ringan": "17+",
    "Medical_Keras": "17+",
    "Pornography_Ringan": "PRC",
    "Pornography_Keras": "PRC",
    "Violence": "PRC",
    "Drug": "PRC",
    "Terrorism": "PRC",
    "SelfHarm": "PRC",
    "Weapon_Keras": "PRC",
    "Addictive Substances": "PRC",
}

ENGINE_STATUS_MAP = {
    "SU": "SAFE",
    "7+": "SAFE",
    "13+": "NEEDS_REVIEW",
    "17+": "VIOLATION",
    "PRC": "VIOLATION",
}

# Weighted distribution for more realistic data
KATEGORI_WEIGHTS = {
    "SAFE": 18,
    "Animasi_Ringan": 12,
    "Sport_Ringan": 10,
    "Medicine_Ringan": 6,
    "Toy_Ringan": 5,
    "Animasi_Keras": 8,
    "Military_Keras": 4,
    "Sport_Keras": 5,
    "Toy_Keras": 3,
    "Medical_Ringan": 4,
    "Military_Ringan": 3,
    "Weapon_Ringan": 2,
    "Medical_Keras": 2,
    "Pornography_Ringan": 4,
    "Pornography_Keras": 3,
    "Violence": 4,
    "Drug": 3,
    "Terrorism": 1,
    "SelfHarm": 2,
    "Weapon_Keras": 1,
    "Addictive Substances": 2,
}

CONTENT_TYPES = ["image", "video", "text", "reel", "story"]

CAPTIONS = [
    "Konten edukasi digital untuk anak Indonesia. Yuk belajar bersama!",
    "Bahaya grooming online yang mengancam generasi muda. Waspada selalu!",
    "Tutorial aman bermedia sosial untuk remaja. Penting diketahui!",
    "Konten tidak pantas yang ditemukan beredar di platform ini.",
    "Gerakan literasi digital nasional untuk keluarga Indonesia.",
    "Konten promosi obat terlarang yang ditargetkan pada remaja.",
    "Stop cyberbullying! Mari jadi pengguna internet bertanggung jawab.",
    "Workshop keamanan digital gratis untuk pelajar SMP-SMA.",
    "Konten kekerasan yang memperlihatkan tindak kriminal eksplisit.",
    "Program internet sehat untuk sekolah dasar seluruh Indonesia.",
    "Konten yang mengandung ujaran kebencian terhadap kelompok tertentu.",
    "Video edukasi kesehatan reproduksi yang sesuai usia untuk remaja.",
    "Konten pornografi keras yang ditemukan di platform ini.",
    "Tips parenting digital untuk orang tua di era modern.",
    "Konten propaganda yang mencoba merekrut remaja Indonesia.",
    "Panduan melindungi anak dari predator online di media sosial.",
    "Konten perjudian online yang menargetkan anak muda.",
    "Siaran langsung dengan konten tidak pantas untuk anak.",
    "Belajar coding gratis untuk anak-anak Indonesia tercinta!",
    "Konten yang mengandung unsur terorisme dan radikalisme.",
    "Festival film edukasi anak Indonesia yang menginspirasi.",
    "Konten narkoba yang mempengaruhi keputusan remaja.",
    "Tips mengajarkan privasi online kepada anak sejak dini.",
    "Konten body shaming yang menargetkan remaja perempuan.",
    "Animasi edukasi berkualitas untuk anak usia 3-6 tahun.",
    "Konten hoaks kesehatan yang menargetkan komunitas sekolah.",
    "Program beasiswa digital untuk anak-anak kurang mampu.",
    "Konten senjata ilegal yang beredar di platform gaming.",
    "Gerakan bersama melawan kekerasan seksual di dunia maya.",
    "Konten ekstremis yang berpotensi meradikalisasi remaja.",
    "Konten sport keras yang tidak sesuai untuk anak kecil.",
    "Animasi keras dengan konten tidak sesuai usia.",
    "Informasi kesehatan ringan untuk semua kalangan.",
    "Konten mainan edukatif untuk perkembangan anak.",
    "Olahraga ringan yang aman dan menyenangkan untuk semua umur.",
    "Konten militer ringan dengan nilai edukasi patriotisme.",
    "Konten medis berat yang membutuhkan pendampingan orang dewasa.",
    "Konten senjata ringan dalam konteks sejarah dan edukasi.",
    "Konten self-harm yang harus segera dihapus dari platform.",
    "Konten militer keras dengan unsur kekerasan berlebihan.",
]


def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def day_offset_dt(days_ago: int, hour: int = 12, minute: int = 0) -> datetime:
    base = now_utc().replace(hour=hour, minute=minute, second=0, microsecond=0)
    return base - timedelta(days=days_ago)


def weighted_choice(weights: dict[str, int]) -> str:
    population = list(weights.keys())
    w = list(weights.values())
    return random.choices(population, weights=w, k=1)[0]


async def run_extended_seed() -> None:
    engine = create_async_engine(str(settings.postgres_url), echo=False)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    async with factory() as session:
        existing_count = len((await session.execute(select(Content))).scalars().all())
        if existing_count >= TOTAL_CONTENT:
            print(f"extended_seed: skipped — {existing_count} content rows already exist.")
            await engine.dispose()
            return

        print(f"\n=== Extended Seeder (target: {TOTAL_CONTENT} content rows) ===")

        platforms = list((await session.execute(select(Platform))).scalars().all())
        agents = list((await session.execute(select(AiAgent))).scalars().all())
        regulations = list((await session.execute(select(RegulationDocument))).scalars().all())
        all_accounts = list((await session.execute(select(Account))).scalars().all())
        all_keywords = list((await session.execute(select(TrendingKeyword))).scalars().all())
        all_igrs = {r.kategori_ai: r for r in (await session.execute(select(IGRSRules))).scalars().all()}

        platform_map = {p.platform_name.lower(): p for p in platforms}
        ig = platform_map.get("instagram")
        tw = platform_map.get("twitter")
        tk = platform_map.get("tiktok")

        ig_accounts = [a for a in all_accounts if ig and a.platform_id == ig.platform_id]
        tw_accounts = [a for a in all_accounts if tw and a.platform_id == tw.platform_id]
        tk_accounts = [a for a in all_accounts if tk and a.platform_id == tk.platform_id]

        kw_agent = next((a for a in agents if a.agent_type == "keyword_model"), agents[0])
        vis_agent = next((a for a in agents if a.agent_type == "classifier"), agents[-1])

        need = TOTAL_CONTENT - existing_count
        inserted_contents: list[Content] = []

        for i in range(need):
            # Distribute evenly over 30 days with some noise
            day_ago = random.randint(0, 29)
            hour = random.randint(6, 23)
            publish_ts = day_offset_dt(day_ago, hour, random.randint(0, 59))
            crawl_ts = publish_ts + timedelta(hours=random.randint(1, 6))

            # Assign platform in round-robin with slight imbalance for realism
            plat_choice = random.choices(["instagram", "twitter", "tiktok"], weights=[35, 35, 30])[0]
            if plat_choice == "instagram" and ig_accounts:
                acc = random.choice(ig_accounts)
                src_url = f"https://www.instagram.com/p/ext{i:05d}/"
            elif plat_choice == "twitter" and tw_accounts:
                acc = random.choice(tw_accounts)
                src_url = f"https://twitter.com/{acc.username}/status/{random.randint(10**17, 10**18-1)}"
            elif tk_accounts:
                acc = random.choice(tk_accounts)
                src_url = f"https://www.tiktok.com/@{acc.username}/video/{random.randint(10**17, 10**18-1)}"
            else:
                acc = random.choice(all_accounts)
                src_url = f"https://example.com/content/{i}"

            kategori = weighted_choice(KATEGORI_WEIGHTS)
            rating = AGE_RATING_MAP[kategori]
            engine_status = ENGINE_STATUS_MAP.get(rating, "NEEDS_REVIEW")
            caption = CAPTIONS[i % len(CAPTIONS)]

            content = Content(
                account_id=acc.account_id,
                source_url=src_url,
                content_type=random.choice(CONTENT_TYPES),
                title=caption[:80],
                description=caption,
                crawl_timestamp=crawl_ts,
                publish_timestamp=publish_ts,
                raw_metadata={
                    "likes": random.randint(0, 50000),
                    "comments": random.randint(0, 5000),
                    "shares": random.randint(0, 2000),
                },
                engine_status=engine_status,
                final_rating=rating,
            )
            session.add(content)
            inserted_contents.append(content)

        await session.commit()
        for c in inserted_contents:
            await session.refresh(c)
        print(f"content: {len(inserted_contents)} inserted.")

        # Classifications
        clf_count = 0
        for content in inserted_contents:
            rating = content.final_rating or "SU"
            base_kategori = next((k for k, v in AGE_RATING_MAP.items() if v == rating), "SAFE")
            for agent in [kw_agent, vis_agent]:
                session.add(Classification(
                    content_id=content.content_id,
                    agent_id=agent.agent_id,
                    kategori_tebakan_ai=base_kategori,
                    reasoning_category=f"Analysis: {base_kategori}",
                    unsafe_reason=None if base_kategori == "SAFE" else f"Indikasi {base_kategori}",
                    confidence_score=round(random.uniform(0.65, 0.99), 3),
                    classification_timestamp=now_utc() - timedelta(hours=random.randint(1, 72)),
                ))
                clf_count += 1
        await session.commit()
        print(f"classification: {clf_count} inserted.")

        # Engine decisions
        ed_count = 0
        for content in inserted_contents:
            rating = content.final_rating or "SU"
            kategori = next((k for k, v in AGE_RATING_MAP.items() if v == rating), "SAFE")
            igrs_rule = all_igrs.get(kategori)
            regulation = random.choice(regulations) if regulations else None
            session.add(EngineDecision(
                content_id=content.content_id,
                igrs_rule_id=igrs_rule.id if igrs_rule else None,
                regulation_id=regulation.regulation_id if regulation else None,
                final_kategori=kategori,
                final_rating=rating,
                is_vetoed=random.random() < 0.03,
                decided_at=now_utc() - timedelta(hours=random.randint(1, 48)),
            ))
            ed_count += 1
        await session.commit()
        print(f"engine_decision: {ed_count} inserted.")

        # Content keywords
        ck_count = 0
        if all_keywords:
            existing_pairs = set(
                (r.content_id, r.keyword_id)
                for r in (await session.execute(select(ContentKeyword))).scalars().all()
            )
            for content in inserted_contents:
                n = random.randint(1, 3)
                for kw in random.sample(all_keywords, min(n, len(all_keywords))):
                    pair = (content.content_id, kw.keyword_id)
                    if pair not in existing_pairs:
                        session.add(ContentKeyword(content_id=content.content_id, keyword_id=kw.keyword_id))
                        existing_pairs.add(pair)
                        ck_count += 1
        await session.commit()
        print(f"content_keyword: {ck_count} inserted.")

        total = len((await session.execute(select(Content))).scalars().all())
        print(f"\n=== Extended seeding done. Total content: {total} ===")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_extended_seed())