"""Main seeder — seeds all tables with realistic dummy data (50 records each where applicable)."""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.tables import (
    Account,
    AgentExecutionLog,
    AiAgent,
    Classification,
    Content,
    ContentKeyword,
    EngineDecision,
    IGRSRules,
    Platform,
    RagChunk,
    RegulationDocument,
    SystemUser,
    TrendingKeyword,
)
from app.seeds.igrs_seed import IGRS_DATA, seed_igrs_rules
from app.settings import settings

# ── helpers ──────────────────────────────────────────────────────────────────

def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def days_ago(n: int) -> datetime:
    return now_utc() - timedelta(days=n)


def rand_dt(start_days: int = 90, end_days: int = 0) -> datetime:
    offset = random.randint(end_days * 86400, start_days * 86400)
    return now_utc() - timedelta(seconds=offset)


# ── static data ───────────────────────────────────────────────────────────────

PLATFORMS = [
    {"platform_name": "Instagram", "base_url": "https://www.instagram.com"},
    {"platform_name": "Twitter",   "base_url": "https://www.twitter.com"},
    {"platform_name": "TikTok",    "base_url": "https://www.tiktok.com"},
]

AI_AGENTS = [
    {
        "agent_name": "Keyword Classifier v1",
        "agent_type": "keyword_model",
        "model_version": "1.0.0",
        "configuration": {"threshold": 0.75, "max_tokens": 512},
        "status": "ACTIVE",
    },
    {
        "agent_name": "Visual Classifier v1",
        "agent_type": "classifier",
        "model_version": "1.0.0",
        "configuration": {"threshold": 0.75, "image_size": 224},
        "status": "ACTIVE",
    },
]

SYSTEM_USERS = [
    {"full_name": "Admin Utama",       "email": "admin@aitf.id",       "password_hash": "$2b$12$dummy_hash_admin"},
    {"full_name": "Analis 1",          "email": "analis1@aitf.id",     "password_hash": "$2b$12$dummy_hash_a1"},
    {"full_name": "Analis 2",          "email": "analis2@aitf.id",     "password_hash": "$2b$12$dummy_hash_a2"},
    {"full_name": "Supervisor",        "email": "supervisor@aitf.id",  "password_hash": "$2b$12$dummy_hash_sv"},
    {"full_name": "Reviewer Konten",   "email": "reviewer@aitf.id",    "password_hash": "$2b$12$dummy_hash_rv"},
]

REGULATION_DOCUMENTS = [
    {
        "document_name": "Undang-Undang Nomor 44 Tahun 2008 tentang Pornografi",
        "document_type": "UU",
        "document_number": "44/2008",
        "full_text": "UU tentang Pornografi yang mengatur larangan produksi, distribusi, dan konsumsi konten pornografi di Indonesia.",
        "official_source_url": "https://peraturan.go.id/uu-44-2008.html",
        "publication_year": 2008,
    },
    {
        "document_name": "Undang-Undang Nomor 11 Tahun 2008 tentang Informasi dan Transaksi Elektronik",
        "document_type": "UU",
        "document_number": "11/2008",
        "full_text": "UU ITE yang mengatur tentang informasi dan transaksi elektronik termasuk konten ilegal.",
        "official_source_url": "https://peraturan.go.id/uu-11-2008.html",
        "publication_year": 2008,
    },
    {
        "document_name": "Peraturan Pemerintah Nomor 71 Tahun 2019 tentang Penyelenggaraan Sistem dan Transaksi Elektronik",
        "document_type": "PP",
        "document_number": "71/2019",
        "full_text": "PP tentang penyelenggaraan sistem elektronik yang mencakup kewajiban penyedia platform.",
        "official_source_url": "https://peraturan.go.id/pp-71-2019.html",
        "publication_year": 2019,
    },
    {
        "document_name": "Peraturan Menteri Kominfo Nomor 5 Tahun 2020 tentang Penyelenggara Sistem Elektronik Lingkup Privat",
        "document_type": "Permenkominfo",
        "document_number": "5/2020",
        "full_text": "Permenkominfo tentang kewajiban PSE lingkup privat untuk memblokir konten yang dilarang.",
        "official_source_url": "https://peraturan.go.id/permenkominfo-5-2020.html",
        "publication_year": 2020,
    },
    {
        "document_name": "Undang-Undang Nomor 35 Tahun 2014 tentang Perlindungan Anak",
        "document_type": "UU",
        "document_number": "35/2014",
        "full_text": "UU Perlindungan Anak yang mengatur hak-hak anak dan perlindungan dari eksploitasi termasuk di ruang digital.",
        "official_source_url": "https://peraturan.go.id/uu-35-2014.html",
        "publication_year": 2014,
    },
]

ACCOUNT_USERNAMES_INSTAGRAM = [
    "komdigi_official", "sahabat_digital", "perlindungan_anak_id", "kominfo_ri",
    "digitalhero_id", "cerdas_internet", "dunia_edukasi", "safe_kids_id",
    "parenting_digital", "literasi_digital_id", "generasi_digital", "anak_cerdas_id",
    "konten_positif", "kreator_edukasi", "indonesia_maju",
    "teen_digital", "youth_online", "netizen_positif",
]

ACCOUNT_USERNAMES_TWITTER = [
    "kominfo_ri", "kpai_official", "literasi_id", "digitalwatch_id",
    "safeinternet_id", "childprotect_id", "netsehat_id", "stophoaks_id",
    "medsos_baik", "konten_sehat", "protect_kids_tw", "online_safe_tw",
    "cek_fakta_id", "siberkreasi", "berani_lapor",
    "edukasi_digital", "guru_digital_id",
]

ACCOUNT_USERNAMES_TIKTOK = [
    "edukasi_tiktok", "kids_zone_id", "safe_content_tk", "literasi_tk",
    "kreasi_positif", "konten_baik_tk", "parenting_tiktok", "anak_indonesia",
    "digital_smart_tk", "cerdas_bermedia", "proteksi_anak_tk", "konten_aman",
    "youth_digital_tk", "generasi_z_id", "tiktok_edukasi",
]

KEYWORD_LIST = [
    "perlindungan anak", "keamanan internet", "konten berbahaya", "pornografi anak",
    "bullying online", "grooming digital", "eksploitasi anak", "kekerasan siber",
    "literasi digital", "parenting digital", "safe browsing", "filter konten",
    "radikalisasi online", "hate speech", "ujaran kebencian", "hoaks anak",
    "predator online", "sexting remaja", "cyberbullying", "body shaming",
    "konten kekerasan", "game berbahaya", "adiksi internet", "screen time anak",
    "privasi anak", "data anak", "foto anak", "video anak", "medsos anak",
    "tiktok anak", "instagram anak", "youtube anak", "twitch anak",
    "gaming anak", "live streaming", "donasi online anak", "judi online anak",
    "narkoba digital", "obat terlarang", "senjata ilegal", "terorisme online",
    "propaganda ekstrem", "self harm remaja", "bunuh diri online", "depresi remaja",
    "kecemasan digital", "trauma siber", "pemulihan korban", "rehabilitasi digital",
    "edukasi seksual", "kesehatan reproduksi remaja",
]

CAPTIONS = [
    "Yuk, bijak menggunakan internet untuk masa depan yang lebih baik!",
    "Mari bersama lindungi anak-anak kita dari konten berbahaya di dunia maya.",
    "Konten ini melanggar aturan perlindungan anak. Segera laporkan!",
    "Program literasi digital untuk generasi muda Indonesia.",
    "Bahaya grooming online mengancam anak-anak kita. Waspada selalu!",
    "Edukasi digital: Cara aman bermedia sosial untuk remaja.",
    "Konten promosi obat terlarang yang ditargetkan kepada remaja.",
    "Stop cyberbullying! Jadilah pengguna internet yang bertanggung jawab.",
    "Tutorial penggunaan internet sehat untuk keluarga Indonesia.",
    "Konten dewasa yang tidak sesuai untuk anak-anak di bawah umur.",
    "Cara melaporkan konten berbahaya di platform digital.",
    "Perlindungan data pribadi anak di era digital modern.",
    "Konten kekerasan yang memperlihatkan tindak kriminal secara eksplisit.",
    "Belajar coding gratis untuk anak-anak Indonesia!",
    "Konten propaganda yang mencoba merekrut remaja.",
    "Tips parenting digital untuk orang tua masa kini.",
    "Video tutorial kesehatan untuk remaja yang informatif.",
    "Konten yang mengandung ujaran kebencian terhadap kelompok tertentu.",
    "Platform edukasi interaktif untuk anak usia dini.",
    "Informasi bahaya rokok dan narkoba untuk remaja.",
    "Konten promosi self-harm yang berbahaya bagi remaja.",
    "Program beasiswa digital untuk anak-anak kurang mampu.",
    "Siaran langsung yang berisi konten tidak pantas untuk anak.",
    "Tips menjaga privasi anak di media sosial.",
    "Konten pornografi ringan yang tersembunyi dalam video gaming.",
    "Gerakan bersama melawan kekerasan seksual di dunia maya.",
    "Konten ekstremis yang berpotensi meradikalisasi remaja.",
    "Workshop keamanan digital gratis untuk pelajar SMP-SMA.",
    "Konten perdagangan senjata ilegal yang ditemukan di platform.",
    "Kampanye anti-bullying untuk pelajar Indonesia.",
    "Konten yang mempertontonkan tindakan berbahaya kepada anak.",
    "Panduan orang tua mengawasi aktivitas online anak.",
    "Konten game dengan unsur kekerasan berlebihan.",
    "Program mentoring digital untuk remaja Indonesia.",
    "Konten pornografi keras yang ditemukan di platform.",
    "Edukasi kesehatan reproduksi yang sesuai usia untuk remaja.",
    "Konten yang menghasut perpecahan dan intoleransi.",
    "Aplikasi pengawasan konten untuk orang tua.",
    "Video animasi edukasi untuk anak usia 3-6 tahun.",
    "Konten yang mengandung iklan rokok yang ditargetkan pada remaja.",
    "Siaran langsung game dengan konten kekerasan berlebihan.",
    "Tips mengajarkan anak tentang privasi online.",
    "Konten yang mempromosikan body shaming terhadap remaja.",
    "Program internet sehat untuk sekolah dasar.",
    "Konten perjudian online yang ditargetkan kepada anak muda.",
    "Cara melindungi anak dari predator online.",
    "Konten hoaks tentang vaksin yang menargetkan orang tua.",
    "Festival film edukasi untuk anak Indonesia.",
    "Konten yang mengandung unsur terorisme dan radikalisme.",
    "Membangun budaya internet sehat di keluarga Indonesia.",
]

CATEGORIES_BY_STATUS = {
    "safe": ["SAFE", "Animasi_Ringan", "Sport_Ringan", "Medicine_Ringan", "Toy_Ringan"],
    "unsafe": [
        "Pornography_Keras", "Pornography_Ringan", "Violence", "Drug",
        "Terrorism", "SelfHarm", "Weapon_Keras", "Addictive Substances",
        "Medical_Keras", "Military_Keras", "Sport_Keras", "Animasi_Keras",
    ],
}

AGE_RATING_MAP = {
    "SAFE": "SU", "Animasi_Ringan": "SU", "Sport_Ringan": "SU",
    "Medicine_Ringan": "SU", "Toy_Ringan": "7+",
    "Animasi_Keras": "13+", "Military_Keras": "13+", "Sport_Keras": "13+",
    "Toy_Keras": "13+", "Medical_Ringan": "7+", "Military_Ringan": "7+",
    "Weapon_Ringan": "17+", "Medical_Keras": "17+", "Pornography_Ringan": "PRC",
    "Pornography_Keras": "PRC", "Violence": "PRC", "Drug": "PRC",
    "Terrorism": "PRC", "SelfHarm": "PRC", "Weapon_Keras": "PRC",
    "Addictive Substances": "PRC",
}

ENGINE_STATUS_MAP = {
    "SU": "SAFE", "7+": "SAFE",
    "13+": "NEEDS_REVIEW", "17+": "VIOLATION", "PRC": "VIOLATION",
}

CONTENT_TYPES = ["image", "video", "text", "reel", "story"]
ACCOUNT_CATEGORIES = ["public_figure", "organisasi", "media", "individu", "anonim"]
KEYWORD_SOURCES = ["google_trend", "trends24", "manual"]
TREND_STATUSES = ["active", "rising", "declining", "expired"]
LOG_STATUSES = ["success", "failed", "running"]

RAG_CHUNK_TEMPLATES = [
    "Pasal {n} ayat (1): Setiap orang dilarang memproduksi, membuat, memperbanyak, menggandakan, menyebarluaskan, menyiarkan, mengimpor, mengekspor, menawarkan, memperjualbelikan, menyewakan, atau menyediakan pornografi.",
    "Pasal {n} ayat (2): Konten yang mengandung unsur kekerasan terhadap anak wajib diblokir dan pelakunya dapat dipidana dengan pidana penjara.",
    "Pasal {n}: Penyelenggara sistem elektronik wajib memastikan konten yang beredar di platformnya tidak melanggar peraturan perundang-undangan yang berlaku.",
    "Pasal {n} ayat (1): Pemerintah berhak memblokir akses terhadap informasi elektronik yang dianggap melanggar ketentuan peraturan perundang-undangan.",
    "Pasal {n}: Setiap anak berhak atas perlindungan dari eksploitasi seksual dan kekerasan, termasuk di ruang digital dan platform online.",
    "Pasal {n} ayat (3): Orang tua, wali, pengasuh anak, pendidik, dan tenaga kependidikan wajib melindungi anak dari informasi yang merusak moral anak.",
    "Pasal {n}: Penyelenggara jasa internet wajib menyediakan fitur penyaringan konten untuk melindungi anak dari konten berbahaya.",
    "Pasal {n} ayat (1): Setiap orang yang memiliki, menyimpan, atau mengakses pornografi anak dapat dipidana dengan pidana penjara maksimal 10 tahun.",
    "Pasal {n}: Konten yang mengandung unsur radikalisme, terorisme, dan separatisme dilarang disebarluaskan melalui media elektronik apapun.",
    "Pasal {n} ayat (2): Platform digital wajib melaporkan kepada pihak berwenang apabila menemukan konten yang diduga melanggar hukum dalam 24 jam.",
]


# ── seeders ───────────────────────────────────────────────────────────────────

async def seed_system_users(session: AsyncSession) -> list[SystemUser]:
    inserted: list[SystemUser] = []
    for u in SYSTEM_USERS:
        existing = await session.execute(
            select(SystemUser).where(SystemUser.email == u["email"])
        )
        if existing.scalars().first():
            continue
        user = SystemUser(**u, registered_at=rand_dt(365, 30), is_active=True)
        session.add(user)
        inserted.append(user)
    await session.commit()
    for u in inserted:
        await session.refresh(u)
    all_users = (await session.execute(select(SystemUser))).scalars().all()
    print(f"app_user seeder: {len(inserted)} inserted, {len(SYSTEM_USERS) - len(inserted)} skipped.")  # noqa: T201
    return list(all_users)


async def seed_platforms(session: AsyncSession) -> list[Platform]:
    inserted: list[Platform] = []
    for p in PLATFORMS:
        existing = await session.execute(
            select(Platform).where(Platform.platform_name == p["platform_name"])
        )
        if existing.scalars().first():
            continue
        plat = Platform(**p, is_active=True, created_at=rand_dt(365, 180))
        session.add(plat)
        inserted.append(plat)
    await session.commit()
    for p in inserted:
        await session.refresh(p)
    all_platforms = (await session.execute(select(Platform))).scalars().all()
    print(f"platform seeder: {len(inserted)} inserted, {len(PLATFORMS) - len(inserted)} skipped.")  # noqa: T201
    return list(all_platforms)


async def seed_ai_agents(session: AsyncSession) -> list[AiAgent]:
    inserted: list[AiAgent] = []
    for a in AI_AGENTS:
        existing = await session.execute(
            select(AiAgent).where(AiAgent.agent_name == a["agent_name"])
        )
        if existing.scalars().first():
            continue
        agent = AiAgent(**a, deployed_at=rand_dt(180, 30))
        session.add(agent)
        inserted.append(agent)
    await session.commit()
    for a in inserted:
        await session.refresh(a)
    all_agents = (await session.execute(select(AiAgent))).scalars().all()
    print(f"ai_agent seeder: {len(inserted)} inserted, {len(AI_AGENTS) - len(inserted)} skipped.")  # noqa: T201
    return list(all_agents)


async def seed_regulation_documents(session: AsyncSession) -> list[RegulationDocument]:
    inserted: list[RegulationDocument] = []
    for r in REGULATION_DOCUMENTS:
        existing = await session.execute(
            select(RegulationDocument).where(RegulationDocument.document_number == r["document_number"])
        )
        if existing.scalars().first():
            continue
        doc = RegulationDocument(**r, uploaded_at=rand_dt(365, 60))
        session.add(doc)
        inserted.append(doc)
    await session.commit()
    for r in inserted:
        await session.refresh(r)
    all_docs = (await session.execute(select(RegulationDocument))).scalars().all()
    print(f"regulation_document seeder: {len(inserted)} inserted, {len(REGULATION_DOCUMENTS) - len(inserted)} skipped.")  # noqa: T201
    return list(all_docs)


async def seed_rag_chunks(session: AsyncSession, regulations: list[RegulationDocument]) -> None:
    existing_count = (await session.execute(select(RagChunk))).scalars().all()
    if len(existing_count) >= 50:
        print(f"rag_chunk seeder: 0 inserted, {len(existing_count)} already exist.")  # noqa: T201
        return
    count = 0
    for i in range(50):
        reg = regulations[i % len(regulations)]
        template = RAG_CHUNK_TEMPLATES[i % len(RAG_CHUNK_TEMPLATES)]
        chunk = RagChunk(
            regulation_id=reg.regulation_id,
            vector_id=f"vec_{reg.regulation_id}_{i:03d}",
            chunk_content=template.format(n=random.randint(1, 50)),
            chunk_index=i % 10,
            article_reference=f"Pasal {random.randint(1, 50)} ayat {random.randint(1, 5)}",
            processed_at=rand_dt(30),
        )
        session.add(chunk)
        count += 1
    await session.commit()
    print(f"rag_chunk seeder: {count} inserted.")  # noqa: T201


async def seed_accounts(session: AsyncSession, platforms: list[Platform]) -> list[Account]:
    existing = (await session.execute(select(Account))).scalars().all()
    if len(existing) >= 50:
        print(f"account seeder: 0 inserted, {len(existing)} already exist.")  # noqa: T201
        return list(existing)

    platform_map = {p.platform_name.lower(): p for p in platforms}
    ig = platform_map.get("instagram")
    tw = platform_map.get("twitter")
    tk = platform_map.get("tiktok")

    accounts_data: list[tuple[Platform | None, str]] = []
    for u in ACCOUNT_USERNAMES_INSTAGRAM[:17]:
        accounts_data.append((ig, u))
    for u in ACCOUNT_USERNAMES_TWITTER[:17]:
        accounts_data.append((tw, u))
    for u in ACCOUNT_USERNAMES_TIKTOK[:16]:
        accounts_data.append((tk, u))

    inserted: list[Account] = []
    for plat, username in accounts_data[:50]:
        if plat is None:
            continue
        acc = Account(
            platform_id=plat.platform_id,
            username=f"@{username}",
            profile_url=f"{plat.base_url}/{username}",
            account_category=random.choice(ACCOUNT_CATEGORIES),
            risk_score=round(random.uniform(0.0, 1.0), 2),
            content_count=random.randint(10, 500),
            last_updated_at=rand_dt(7),
        )
        session.add(acc)
        inserted.append(acc)

    await session.commit()
    for a in inserted:
        await session.refresh(a)
    all_accounts = (await session.execute(select(Account))).scalars().all()
    print(f"account seeder: {len(inserted)} inserted, {len(existing)} already existed.")  # noqa: T201
    return list(all_accounts)


async def seed_trending_keywords(session: AsyncSession, agents: list[AiAgent]) -> list[TrendingKeyword]:
    existing = (await session.execute(select(TrendingKeyword))).scalars().all()
    if len(existing) >= 50:
        print(f"trending_keyword seeder: 0 inserted, {len(existing)} already exist.")  # noqa: T201
        return list(existing)

    kw_agent = next((a for a in agents if a.agent_type == "keyword_model"), agents[0])
    inserted: list[TrendingKeyword] = []
    for i, kw in enumerate(KEYWORD_LIST[:50]):
        detected = rand_dt(30)
        tk = TrendingKeyword(
            agent_id=kw_agent.agent_id,
            keyword=kw,
            source=random.choice(KEYWORD_SOURCES),
            trend_score=round(random.uniform(0.3, 1.0), 3),
            trend_status=random.choice(TREND_STATUSES),
            detected_at=detected,
            expires_at=detected + timedelta(days=random.randint(7, 30)),
        )
        session.add(tk)
        inserted.append(tk)

    await session.commit()
    for k in inserted:
        await session.refresh(k)
    all_kw = (await session.execute(select(TrendingKeyword))).scalars().all()
    print(f"trending_keyword seeder: {len(inserted)} inserted, {len(existing)} already existed.")  # noqa: T201
    return list(all_kw)


async def seed_contents(session: AsyncSession, accounts: list[Account]) -> list[Content]:
    existing = (await session.execute(select(Content))).scalars().all()
    if len(existing) >= 50:
        print(f"content seeder: 0 inserted, {len(existing)} already exist.")  # noqa: T201
        return list(existing)

    all_categories = list(AGE_RATING_MAP.keys())
    inserted: list[Content] = []

    for i in range(50):
        acc = accounts[i % len(accounts)]
        kategori = random.choice(all_categories)
        rating = AGE_RATING_MAP[kategori]
        engine_status = ENGINE_STATUS_MAP.get(rating, "NEEDS_REVIEW")
        is_safe = kategori in CATEGORIES_BY_STATUS["safe"]
        platform_name = ""
        for plat in ["instagram", "twitter", "tiktok"]:
            if plat in (acc.profile_url or "").lower():
                platform_name = plat
                break

        content_type = random.choice(CONTENT_TYPES)
        caption = CAPTIONS[i % len(CAPTIONS)]

        if "instagram" in (acc.profile_url or ""):
            src_url = f"https://www.instagram.com/p/seed{i:04d}/"
        elif "twitter" in (acc.profile_url or ""):
            src_url = f"https://twitter.com/{acc.username}/status/{random.randint(10**17, 10**18 - 1)}"
        else:
            src_url = f"https://www.tiktok.com/@{acc.username}/video/{random.randint(10**17, 10**18 - 1)}"

        publish_ts = rand_dt(90, 1)
        crawl_ts = publish_ts + timedelta(hours=random.randint(1, 48))

        c = Content(
            account_id=acc.account_id,
            source_url=src_url,
            content_type=content_type,
            title=caption[:80],
            description=caption,
            crawl_timestamp=crawl_ts,
            publish_timestamp=publish_ts,
            raw_metadata={
                "likes": random.randint(0, 10000),
                "comments": random.randint(0, 1000),
                "shares": random.randint(0, 500),
                "platform": platform_name,
            },
            engine_status=engine_status,
            final_rating=rating,
        )
        session.add(c)
        inserted.append(c)

    await session.commit()
    for c in inserted:
        await session.refresh(c)
    all_contents = (await session.execute(select(Content))).scalars().all()
    print(f"content seeder: {len(inserted)} inserted, {len(existing)} already existed.")  # noqa: T201
    return list(all_contents)


async def seed_classifications(
    session: AsyncSession,
    contents: list[Content],
    agents: list[AiAgent],
) -> None:
    existing = (await session.execute(select(Classification))).scalars().all()
    if len(existing) >= 50:
        print(f"classification seeder: 0 inserted, {len(existing)} already exist.")  # noqa: T201
        return

    kw_agent = next((a for a in agents if a.agent_type == "keyword_model"), agents[0])
    vis_agent = next((a for a in agents if a.agent_type == "classifier"), agents[-1])
    all_categories = list(AGE_RATING_MAP.keys())
    count = 0

    for content in contents:
        rating = content.final_rating or "SU"
        base_kategori = next(
            (k for k, v in AGE_RATING_MAP.items() if v == rating),
            random.choice(all_categories),
        )

        # Keyword agent classification
        session.add(Classification(
            content_id=content.content_id,
            agent_id=kw_agent.agent_id,
            kategori_tebakan_ai=base_kategori,
            reasoning_category=f"Keyword analysis mendeteksi konten {base_kategori}",
            unsafe_reason=None if base_kategori == "SAFE" else f"Ditemukan indikasi {base_kategori} dalam teks konten",
            confidence_score=round(random.uniform(0.6, 0.99), 3),
            classification_timestamp=now_utc() - timedelta(hours=random.randint(1, 72)),
        ))
        count += 1

        # Visual agent classification
        session.add(Classification(
            content_id=content.content_id,
            agent_id=vis_agent.agent_id,
            kategori_tebakan_ai=base_kategori,
            reasoning_category=f"Visual analysis mendeteksi konten {base_kategori}",
            unsafe_reason=None if base_kategori == "SAFE" else f"Ditemukan indikasi {base_kategori} dalam visual konten",
            confidence_score=round(random.uniform(0.6, 0.99), 3),
            classification_timestamp=now_utc() - timedelta(hours=random.randint(1, 72)),
        ))
        count += 1

    await session.commit()
    print(f"classification seeder: {count} inserted.")  # noqa: T201


async def seed_agent_execution_logs(
    session: AsyncSession, agents: list[AiAgent]
) -> None:
    existing = (await session.execute(select(AgentExecutionLog))).scalars().all()
    if len(existing) >= 50:
        print(f"agent_execution_log seeder: 0 inserted, {len(existing)} already exist.")  # noqa: T201
        return

    count = 0
    for i in range(50):
        agent = agents[i % len(agents)]
        start = rand_dt(30)
        duration = timedelta(seconds=random.randint(5, 300))
        status = random.choice(LOG_STATUSES)
        log = AgentExecutionLog(
            agent_id=agent.agent_id,
            execution_start=start,
            execution_end=start + duration if status != "running" else None,
            status=status,
            input_payload={"batch_size": random.randint(10, 100), "content_ids": list(range(i * 10, i * 10 + 10))},
            output_result={"processed": random.randint(5, 50), "errors": random.randint(0, 3)} if status == "success" else None,
        )
        session.add(log)
        count += 1

    await session.commit()
    print(f"agent_execution_log seeder: {count} inserted.")  # noqa: T201


async def seed_engine_decisions(
    session: AsyncSession,
    contents: list[Content],
    regulations: list[RegulationDocument],
) -> None:
    existing = (await session.execute(select(EngineDecision))).scalars().all()
    if len(existing) >= 50:
        print(f"engine_decision seeder: 0 inserted, {len(existing)} already exist.")  # noqa: T201
        return

    all_igrs = (await session.execute(select(IGRSRules))).scalars().all()
    igrs_map: dict[str, IGRSRules] = {r.kategori_ai: r for r in all_igrs}

    count = 0
    for content in contents:
        rating = content.final_rating or "SU"
        kategori = next(
            (k for k, v in AGE_RATING_MAP.items() if v == rating),
            "SAFE",
        )
        igrs_rule = igrs_map.get(kategori)
        regulation = random.choice(regulations)

        decision = EngineDecision(
            content_id=content.content_id,
            igrs_rule_id=igrs_rule.id if igrs_rule else None,
            regulation_id=regulation.regulation_id,
            final_kategori=kategori,
            final_rating=rating,
            is_vetoed=random.random() < 0.05,
            decided_at=now_utc() - timedelta(hours=random.randint(1, 48)),
        )
        session.add(decision)
        count += 1

    await session.commit()
    print(f"engine_decision seeder: {count} inserted.")  # noqa: T201


async def seed_content_keywords(
    session: AsyncSession,
    contents: list[Content],
    keywords: list[TrendingKeyword],
) -> None:
    existing = (await session.execute(select(ContentKeyword))).scalars().all()
    if len(existing) >= 50:
        print(f"content_keyword seeder: 0 inserted, {len(existing)} already exist.")  # noqa: T201
        return

    used: set[tuple[int, int]] = set()
    count = 0
    for content in contents:
        n_keywords = random.randint(1, 3)
        for kw in random.sample(keywords, min(n_keywords, len(keywords))):
            pair = (content.content_id, kw.keyword_id)
            if pair in used:
                continue
            used.add(pair)
            session.add(ContentKeyword(content_id=content.content_id, keyword_id=kw.keyword_id))
            count += 1

    await session.commit()
    print(f"content_keyword seeder: {count} inserted.")  # noqa: T201


# ── main ──────────────────────────────────────────────────────────────────────

async def seed_all() -> None:
    engine = create_async_engine(str(settings.postgres_url), echo=False)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    # Create all tables first
    async with engine.begin() as conn:
        from app.db.sql import Base
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        print("\n=== AITF Main Seeder ===")  # noqa: T201

        await seed_igrs_rules(session)
        users = await seed_system_users(session)
        platforms = await seed_platforms(session)
        agents = await seed_ai_agents(session)
        regulations = await seed_regulation_documents(session)
        await seed_rag_chunks(session, regulations)
        accounts = await seed_accounts(session, platforms)
        keywords = await seed_trending_keywords(session, agents)
        contents = await seed_contents(session, accounts)
        await seed_classifications(session, contents, agents)
        await seed_agent_execution_logs(session, agents)
        await seed_engine_decisions(session, contents, regulations)
        await seed_content_keywords(session, contents, keywords)

        print("\n=== Seeding selesai! ===")  # noqa: T201

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_all())