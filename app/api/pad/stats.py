from __future__ import annotations

import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.sql import get_db_session
from app.db.tables import Account, Content, EngineDecision, Platform, TrendingKeyword
from app.services.export_service import generate_content_csv, generate_content_pdf
from app.services.minio import get_presigned_url

router = APIRouter(prefix="/stats", tags=["Stats"])

_AGE_ORDER = ["SU", "7+", "13+", "17+", "PRC"]

# ── Penilaian Risiko Akun ────────────────────────────────────────────────────
# Metodologi (transparan, tiap angka punya alasan jelas). Mengacu praktik umum
# Trust & Safety + risk-scoring: Risiko = Dampak (severity) × Prevalensi, lalu
# dinormalisasi ke indeks 0–100 dengan worst-case floor untuk konten berat.
#
# Bobot DAMPAK per kategori umur = perkiraan potensi bahaya bila seorang ANAK
# terpapar konten tsb. Skala non-linear: lompatan makin besar di tingkat berat
# karena bahayanya tidak proporsional (PRC = pelanggaran/ilegal).
#   SU  = 0  → aman untuk semua umur, tidak menambah risiko
#   7+  = 1  → konten ringan, risiko minimal
#   13+ = 3  → mulai tak sesuai anak, perlu pendampingan
#   17+ = 6  → konten dewasa, jelas bukan untuk anak (±2× dari 13+)
#   PRC = 10 → konten terlarang/ilegal, bahaya tertinggi
# Bobot = bilangan segitiga T(level) dari level keparahan ordinal 0..4
# (T(n)=n(n+1)/2 → 0,1,3,6,10): eskalasi konveks/super-linear, sesuai prinsip
# disutility bahaya yang naik tak proporsional. Lihat docs/penilaian-akun-berisiko.md.
_AGE_POINTS = {"SU": 0, "7+": 1, "13+": 3, "17+": 6, "PRC": 10}
_MAX_AGE_POINT = 10  # bobot PRC — dipakai untuk normalisasi indeks 0–100
# Prior (Laplace smoothing) untuk densitas: seolah ada N konten "netral" semu.
# Mencegah akun ber-konten sedikit (mis. 1 post PRC) langsung 100%/Kritis —
# bukti sedikit = kurang yakin. Makin banyak konten, efek prior makin hilang.
_PRIOR_SAFE = 5

# Konten "tidak layak untuk anak" (untuk hitung prevalensi). Sejalan dengan
# pemisahan SAFE/UNSAFE di engine (SAFE = SU/7+).
_UNSAFE_RATINGS = ("13+", "17+", "PRC")

# Ambang level risiko pada indeks 0–100 (risk-tiering, urut dari tertinggi).
_RISK_LEVELS = [(90, "Kritis"), (70, "Tinggi"), (40, "Sedang"), (1, "Rendah"), (0, "Aman")]
# Akun "berisiko" (warning) = minimal level Sedang (indeks >= 40).
_WARNING_INDEX_THRESHOLD = 40


def _compute_account_risk(age_groups: dict[str, int], total: int) -> dict:
    """Hitung indeks risiko 0–100, level, poin per-kategori, dan ALASAN satu akun.

    Langkah (semua dapat dijelaskan ke pengguna):
    1. Severity points: tiap konten dapat bobot _AGE_POINTS sesuai rating-nya.
    2. Harm density (Dampak × Prevalensi) + Laplace smoothing:
       (Σ bobot) / ((total + _PRIOR_SAFE) × _MAX_AGE_POINT) × 100. Menangkap
       SEBERAPA KONSISTEN akun memposting konten berbahaya (prevalensi = tolok
       ukur utama Trust & Safety). Prior _PRIOR_SAFE mencegah akun ber-konten
       sedikit (mis. 1 post) langsung 100% — bukti sedikit = belum yakin.
    3. Severity floor (worst-case): konten berat tak bisa "diencerkan" oleh
       banyaknya konten aman — sedikit saja sudah tidak dapat ditoleransi.
         • ada PRC             → minimal Tinggi; >=3 PRC → Kritis
         • ada 17+ (tanpa PRC) → minimal Sedang
    Indeks akhir = max(harm_density, floor); level diturunkan dari indeks.
    """
    age_points = {r: _AGE_POINTS.get(r, 0) * c for r, c in age_groups.items()}
    severity_sum = sum(age_points.values())
    unsafe = sum(age_groups.get(r, 0) for r in _UNSAFE_RATINGS)

    density_index = severity_sum / ((total + _PRIOR_SAFE) * _MAX_AGE_POINT) * 100

    prc = age_groups.get("PRC", 0)
    p17 = age_groups.get("17+", 0)
    p13 = age_groups.get("13+", 0)

    floor = 0
    if prc > 0:
        floor = 90 if prc >= 3 else 70
    elif p17 > 0:
        floor = 40

    risk_index = round(min(100.0, max(density_index, float(floor))))
    if unsafe == 0:  # tak ada konten "tidak layak anak" → aman, apa pun volumenya
        risk_index = 0

    level = "Aman"
    for thr, name in _RISK_LEVELS:
        if risk_index >= thr:
            level = name
            break

    reasons: list[str] = []
    if prc > 0:
        reasons.append(f"{prc} konten Konten Terlarang/PRC — pelanggaran berat, berpotensi ilegal.")
    if p17 > 0:
        reasons.append(f"{p17} konten kategori 17+ — khusus dewasa, tidak layak untuk anak.")
    if p13 > 0:
        reasons.append(f"{p13} konten kategori 13+ — belum sepenuhnya sesuai untuk anak.")
    if total > 0 and unsafe > 0:
        reasons.append(
            f"{round(unsafe / total * 100)}% konten tidak layak untuk anak ({unsafe} dari {total})."
        )
    if not reasons:
        reasons.append("Mayoritas konten tergolong aman untuk anak.")

    return {
        "score": severity_sum,
        "age_points": age_points,
        "risk_index": risk_index,
        "risk_level": level,
        "unsafe_count": unsafe,
        "unsafe_ratio": round(unsafe / total, 3) if total else 0.0,
        "reasons": reasons,
        "is_warning": risk_index >= _WARNING_INDEX_THRESHOLD,
    }


@router.get("/dashboard")
async def get_dashboard_stats(
    date_from: str = "",
    date_to: str = "",
    session: AsyncSession = Depends(get_db_session),
):
    from datetime import datetime, timezone as tz

    time_filters = []
    if date_from:
        try:
            time_filters.append(Content.crawl_timestamp >= datetime.fromisoformat(date_from.replace("Z", "+00:00")))
        except ValueError:
            pass
    if date_to:
        try:
            time_filters.append(Content.crawl_timestamp <= datetime.fromisoformat(date_to.replace("Z", "+00:00")))
        except ValueError:
            pass

    # Total counts
    total = (await session.execute(select(func.count()).select_from(Content).where(*time_filters))).scalar_one()
    safe = (await session.execute(
        select(func.count()).select_from(Content).where(Content.engine_status == "SAFE", *time_filters)
    )).scalar_one()
    unsafe = (await session.execute(
        select(func.count()).select_from(Content).where(Content.engine_status.in_(["VIOLATION", "NEEDS_REVIEW"]), *time_filters)
    )).scalar_one()

    # Per-platform stats: join content → account → platform
    rows = (await session.execute(
        select(
            Platform.platform_name,
            Content.engine_status,
            Content.final_rating,
            func.count().label("cnt"),
        )
        .join(Account, Content.account_id == Account.account_id)
        .join(Platform, Account.platform_id == Platform.platform_id)
        .where(*time_filters)
        .group_by(Platform.platform_name, Content.engine_status, Content.final_rating)
    )).all()

    _PLATFORM_NORM = {"instagram": "Instagram", "tiktok": "TikTok", "twitter": "Twitter", "youtube": "YouTube"}
    platforms: dict = {}
    for platform_name, engine_status, final_rating, cnt in rows:
        normalized = _PLATFORM_NORM.get((platform_name or "").lower(), platform_name or "Unknown")
        p = platforms.setdefault(normalized, {
            "count": 0, "safe": 0, "unsafe": 0,
            "age_groups": {"SU": 0, "7+": 0, "13+": 0, "17+": 0, "PRC": 0},
        })
        p["count"] += cnt
        if engine_status == "SAFE":
            p["safe"] += cnt
        else:
            p["unsafe"] += cnt
        if final_rating in p["age_groups"]:
            p["age_groups"][final_rating] += cnt

    # Top keywords
    kw_rows = (await session.execute(
        select(TrendingKeyword.keyword, func.count().label("cnt"))
        .group_by(TrendingKeyword.keyword)
        .order_by(func.count().desc())
        .limit(10)
    )).all()
    top_keywords = [{"keyword": kw, "count": cnt} for kw, cnt in kw_rows]

    keyword_stats = {}
    for norm_source, raw_source in [("Google Trend", "google_trend"), ("Trends24", "trends24")]:
        total_kws = (await session.execute(
            select(func.count(func.distinct(TrendingKeyword.keyword)))
            .where(TrendingKeyword.source == raw_source)
        )).scalar() or 0
        
        top_kws = (await session.execute(
            select(TrendingKeyword.keyword, func.count().label("cnt"))
            .where(TrendingKeyword.source == raw_source)
            .group_by(TrendingKeyword.keyword)
            .order_by(func.count().desc())
            .limit(5)
        )).all()
        
        keyword_stats[norm_source] = {
            "total": total_kws,
            "top": [{"keyword": kw, "count": cnt} for kw, cnt in top_kws]
        }

    return {
        "total_content": total,
        "safe_content": safe,
        "unsafe_content": unsafe,
        "platforms": platforms,
        "top_keywords": top_keywords,
        "keyword_stats": keyword_stats,
        "pipeline_status": {},
    }


def _content_base_select():
    """Shared select (content + account/platform/decision joins) for the content
    list and the single-content detail endpoint, so both build identical rows."""
    return (
        select(
            Content.content_id,
            Platform.platform_name,
            Account.username,
            Content.description,
            Content.engine_status,
            Content.final_rating,
            Content.source_url,
            Content.crawl_timestamp,
            Content.raw_metadata,
            EngineDecision.final_kategori,
            Content.reviewed_by,
            Content.reviewed_at,
        )
        .join(Account, Content.account_id == Account.account_id)
        .join(Platform, Account.platform_id == Platform.platform_id)
        .outerjoin(EngineDecision, EngineDecision.content_id == Content.content_id)
    )


async def _row_to_item(row) -> dict:
    """Map a content row (see `_content_base_select`) into the ContentItem shape
    the frontend expects, resolving a presigned screenshot URL when available."""
    (cid, plat, username, desc, eng_status, rating, src_url, crawled_at, raw_meta, kategori, reviewed_by, reviewed_at) = row
    meta = raw_meta or {}

    # Prefer real screenshot (MinIO) over CDN thumbnail.
    # Frontend pakai URL ini langsung di <img src>; presigned URL valid 1 jam.
    screenshot_path = meta.get("screenshot_path", "")
    thumbnail = ""
    if screenshot_path:
        pres = await get_presigned_url(screenshot_path, time_to_expire=3600)
        if pres.get("status") == "success":
            thumbnail = pres.get("url", "")
    if not thumbnail:
        thumbnail = meta.get("thumbnail_url", "")

    return {
        "id": cid,
        "platform": (plat or "").lower(),
        "username": username or "",
        "caption": desc or "",
        "classification": "safe" if eng_status == "SAFE" else "unsafe",
        "ageGroup": rating or "SU",
        "category": (kategori or "").lower(),
        "contentUrl": src_url or "",
        "keyword": meta.get("seed_trend", ""),
        "thumbnailUrl": thumbnail,
        "reasonAi": meta.get("reason", ""),
        "classifications": meta.get("classifications_json", None),
        "createdAt": crawled_at.isoformat() if crawled_at else "",
        "reviewedBy": reviewed_by or "",
        "reviewedAt": reviewed_at.isoformat() if reviewed_at else "",
    }


@router.get("/content")
async def get_content_list(
    q: str = "",
    platform: str = "",
    classification: str = "",
    age_group: str = "",
    mission_id: str = "",
    date_from: str = "",
    date_to: str = "",
    reviewed: str = "",
    page: int = 1,
    per_page: int = 12,
    session: AsyncSession = Depends(get_db_session),
):
    from datetime import datetime

    stmt = _content_base_select()

    if mission_id:
        # Konten satu sesi crawl (dipakai daftar konten di halaman laporan).
        stmt = stmt.where(Content.raw_metadata["mission_id"].astext == mission_id)
    if q:
        stmt = stmt.where(Content.description.ilike(f"%{q}%"))
    if platform:
        stmt = stmt.where(Platform.platform_name.ilike(platform))
    if classification == "safe":
        stmt = stmt.where(Content.engine_status == "SAFE")
    elif classification == "unsafe":
        stmt = stmt.where(Content.engine_status.in_(["VIOLATION", "NEEDS_REVIEW"]))
    if age_group:
        stmt = stmt.where(Content.final_rating == age_group)
    if reviewed == "yes":
        stmt = stmt.where(Content.reviewed_by.isnot(None))
    elif reviewed == "no":
        stmt = stmt.where(Content.reviewed_by.is_(None))
    if date_from:
        try:
            # Support both "YYYY-MM-DD" and full ISO "YYYY-MM-DDTHH:MM:SSZ".
            cleaned = date_from.replace("Z", "+00:00")
            if "T" not in cleaned:
                # Plain date → start of that day
                cleaned += "T00:00:00"
            stmt = stmt.where(
                Content.crawl_timestamp >= datetime.fromisoformat(cleaned)
            )
        except ValueError:
            pass
    if date_to:
        try:
            cleaned = date_to.replace("Z", "+00:00")
            if "T" not in cleaned:
                # Plain date → end of that day
                cleaned += "T23:59:59"
            stmt = stmt.where(
                Content.crawl_timestamp <= datetime.fromisoformat(cleaned)
            )
        except ValueError:
            pass

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar_one()
    max_page = max(1, (total + per_page - 1) // per_page)

    stmt = stmt.order_by(Content.crawl_timestamp.desc()).offset((page - 1) * per_page).limit(per_page)
    rows = (await session.execute(stmt)).all()

    items = [await _row_to_item(row) for row in rows]

    return {
        "data_per_page": items,
        "meta": {"page": page, "max_page": max_page, "total": total},
    }


# NOTE: /content/export/csv registered BEFORE /content/{content_id} to avoid
# FastAPI matching "export" against the int path param.
@router.get("/content/export/csv")
async def download_content_csv(
    q: str = "",
    platform: str = "",
    classification: str = "",
    age_group: str = "",
    mission_id: str = "",
    date_from: str = "",
    date_to: str = "",
    session: AsyncSession = Depends(get_db_session),
):
    """Download crawl results as a CSV file with optional filters.

    Supports filtering by: platform, classification (safe/unsafe), age_group
    (SU/7+/13+/17+/PRC), mission_id, and date range (date_from / date_to).
    Returns ALL matching rows (no pagination) for a full export.
    """
    from datetime import datetime

    stmt = _content_base_select()

    if mission_id:
        stmt = stmt.where(Content.raw_metadata["mission_id"].astext == mission_id)
    if q:
        stmt = stmt.where(Content.description.ilike(f"%{q}%"))
    if platform:
        stmt = stmt.where(Platform.platform_name.ilike(platform))
    if classification == "safe":
        stmt = stmt.where(Content.engine_status == "SAFE")
    elif classification == "unsafe":
        stmt = stmt.where(Content.engine_status.in_(["VIOLATION", "NEEDS_REVIEW"]))
    if age_group:
        stmt = stmt.where(Content.final_rating == age_group)
    if date_from:
        try:
            cleaned = date_from.replace("Z", "+00:00")
            if "T" not in cleaned:
                cleaned += "T00:00:00"
            stmt = stmt.where(
                Content.crawl_timestamp >= datetime.fromisoformat(cleaned)
            )
        except ValueError:
            pass
    if date_to:
        try:
            cleaned = date_to.replace("Z", "+00:00")
            if "T" not in cleaned:
                cleaned += "T23:59:59"
            stmt = stmt.where(
                Content.crawl_timestamp <= datetime.fromisoformat(cleaned)
            )
        except ValueError:
            pass

    # Cap at 10 000 rows to avoid OOM on huge datasets.
    stmt = stmt.order_by(Content.crawl_timestamp.desc()).limit(10_000)
    rows = (await session.execute(stmt)).all()
    items = [await _row_to_item(row) for row in rows]

    csv_bytes = generate_content_csv(items)

    # Generate a descriptive filename.
    now_str = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"laporan_crawl_{now_str}"
    if date_from or date_to:
        filename += f"_{date_from or 'awal'}_{date_to or 'akhir'}"
    if age_group:
        filename += f"_{age_group}"
    filename += ".csv"

    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/content/{content_id}")
async def get_content_detail(
    content_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Single content item for the detail-konten page (/admin/content/[id])."""
    row = (
        await session.execute(
            _content_base_select().where(Content.content_id == content_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Content not found")
    return await _row_to_item(row)


class UpdateClassificationRequest(BaseModel):
    classification: str  # "safe" | "unsafe"
    category: str  # e.g. "violence", "bullying"
    age_group: str  # SU | 7+ | 13+ | 17+ | PRC


@router.patch("/content/{content_id}")
async def update_content_classification(
    content_id: int,
    payload: UpdateClassificationRequest,
    session: AsyncSession = Depends(get_db_session),
):
    content = (await session.execute(
        select(Content).where(Content.content_id == content_id)
    )).scalars().first()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    content.engine_status = "SAFE" if payload.classification == "safe" else "VIOLATION"
    content.final_rating = payload.age_group

    decision = (await session.execute(
        select(EngineDecision).where(EngineDecision.content_id == content_id)
    )).scalars().first()
    if decision:
        decision.final_kategori = payload.category
        decision.final_rating = payload.age_group

    await session.commit()
    return {"status": "ok", "content_id": content_id}


class ReviewContentRequest(BaseModel):
    reviewed_by: str


@router.patch("/content/{content_id}/review")
async def review_content(
    content_id: int,
    payload: ReviewContentRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Mark a content item as reviewed by an admin."""
    from datetime import datetime, timezone as tz

    content = (await session.execute(
        select(Content).where(Content.content_id == content_id)
    )).scalars().first()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    content.reviewed_by = payload.reviewed_by
    content.reviewed_at = datetime.now(tz.utc)
    await session.commit()
    return {
        "status": "ok",
        "content_id": content_id,
        "reviewed_by": content.reviewed_by,
        "reviewed_at": content.reviewed_at.isoformat(),
    }


@router.delete("/content/{content_id}/review")
async def unreview_content(
    content_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Remove the reviewed flag from a content item."""
    content = (await session.execute(
        select(Content).where(Content.content_id == content_id)
    )).scalars().first()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    content.reviewed_by = None
    content.reviewed_at = None
    await session.commit()
    return {"status": "ok", "content_id": content_id}


@router.delete("/content/{content_id}")
async def delete_content(
    content_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    # Pakai DELETE SQL langsung supaya PG ON DELETE CASCADE bersihkan engine_decision/classification.
    # Hindari session.delete() yang bikin SQLAlchemy ORM coba set FK ke NULL dulu.
    exists = (await session.execute(
        select(Content.content_id).where(Content.content_id == content_id)
    )).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="Content not found")
    await session.execute(delete(Content).where(Content.content_id == content_id))
    await session.commit()
    return {"status": "ok", "content_id": content_id}


@router.get("/chart")
async def get_platform_chart(
    platform: str,
    category: str = "",
    date_from: str = "",
    date_to: str = "",
    session: AsyncSession = Depends(get_db_session),
):
    """Data Statistik Detail per platform: distribusi kategori umur + distribusi
    kategori IGRS (data nyata), bisa difilter kategori IGRS & rentang tanggal."""
    from datetime import datetime

    filters: list = [Platform.platform_name.ilike(platform)]
    if date_from:
        try:
            filters.append(Content.crawl_timestamp >= datetime.fromisoformat(date_from.replace("Z", "+00:00")))
        except ValueError:
            pass
    if date_to:
        try:
            filters.append(Content.crawl_timestamp <= datetime.fromisoformat(date_to.replace("Z", "+00:00")))
        except ValueError:
            pass

    cat = category.strip()
    cat_filter = []
    if cat and cat.lower() != "semua":
        cat_filter.append(EngineDecision.final_kategori == cat)

    # Distribusi kategori umur (ikut filter kategori IGRS bila dipilih).
    age_rows = (await session.execute(
        select(Content.final_rating, func.count().label("cnt"))
        .join(Account, Content.account_id == Account.account_id)
        .join(Platform, Account.platform_id == Platform.platform_id)
        .outerjoin(EngineDecision, EngineDecision.content_id == Content.content_id)
        .where(*filters, *cat_filter)
        .group_by(Content.final_rating)
    )).all()
    age_map = {r: c for r, c in age_rows if r in _AGE_ORDER}
    age_group_dist = [{"age_group": a, "count": age_map.get(a, 0)} for a in _AGE_ORDER]

    # Distribusi kategori IGRS (selalu ikut filter tanggal/platform; tidak
    # disempitkan oleh filter kategori agar breakdown penuh tetap terlihat).
    cat_rows = (await session.execute(
        select(EngineDecision.final_kategori, func.count().label("cnt"))
        .join(Content, EngineDecision.content_id == Content.content_id)
        .join(Account, Content.account_id == Account.account_id)
        .join(Platform, Account.platform_id == Platform.platform_id)
        .where(*filters)
        .group_by(EngineDecision.final_kategori)
        .order_by(func.count().desc())
    )).all()
    category_dist = [{"category": k, "count": c} for k, c in cat_rows if k]

    total = sum(d["count"] for d in age_group_dist)
    return {
        "platform": platform,
        "total": total,
        "age_group_dist": age_group_dist,
        "category_dist": category_dist,
    }


@router.get("/accounts/risky")
async def get_risky_accounts(
    limit: int = 50,
    date_from: str = "",
    date_to: str = "",
    only_warning: bool = False,
    session: AsyncSession = Depends(get_db_session),
):
    """Daftar akun berisiko dengan penilaian transparan (lihat _compute_account_risk).

    Tiap akun mendapat indeks risiko 0–100, level (Aman/Rendah/Sedang/Tinggi/
    Kritis), dan daftar `reasons` (alasan jelas) berdasarkan dampak (bobot per
    rating) × prevalensi konten tidak layak + worst-case floor untuk 17+/PRC.
    Ditandai 'berisiko' bila indeks >= ambang (Sedang).
    """
    from datetime import datetime

    filters: list = []
    if date_from:
        try:
            filters.append(Content.crawl_timestamp >= datetime.fromisoformat(date_from.replace("Z", "+00:00")))
        except ValueError:
            pass
    if date_to:
        try:
            filters.append(Content.crawl_timestamp <= datetime.fromisoformat(date_to.replace("Z", "+00:00")))
        except ValueError:
            pass

    rows = (await session.execute(
        select(
            Account.account_id,
            Account.username,
            Platform.platform_name,
            Content.final_rating,
            func.count().label("cnt"),
        )
        .join(Platform, Account.platform_id == Platform.platform_id)
        .join(Content, Content.account_id == Account.account_id)
        .where(*filters)
        .group_by(
            Account.account_id,
            Account.username,
            Platform.platform_name,
            Content.final_rating,
        )
    )).all()

    accounts: dict = {}
    for acc_id, username, plat, rating, cnt in rows:
        a = accounts.setdefault(acc_id, {
            "account_id": acc_id,
            "username": username or "",
            "platform": (plat or "").lower(),
            "total_content": 0,
            "age_groups": {k: 0 for k in _AGE_ORDER},
        })
        a["total_content"] += cnt
        # UNRATED & rating tak dikenal tetap dihitung di total (sebagai pembagi
        # prevalensi) tapi tidak diberi bobot bahaya (belum terkonfirmasi).
        if rating in a["age_groups"]:
            a["age_groups"][rating] += cnt

    result = []
    for a in accounts.values():
        a.update(_compute_account_risk(a["age_groups"], a["total_content"]))
        if only_warning and not a["is_warning"]:
            continue
        result.append(a)

    # Urutkan: yang warning dulu, lalu indeks risiko tertinggi.
    result.sort(key=lambda x: (x["is_warning"], x["risk_index"]), reverse=True)
    result = result[:limit]

    return {
        "accounts": result,
        "count": len(result),
        "threshold": _WARNING_INDEX_THRESHOLD,
        "weights": _AGE_POINTS,
        "levels": [name for _, name in reversed(_RISK_LEVELS)],
    }


@router.get("/keywords")
async def get_keyword_list(
    limit: int = 50,
    date_from: str = "",
    date_to: str = "",
    session: AsyncSession = Depends(get_db_session),
):
    from datetime import datetime

    stmt = (
        select(
            TrendingKeyword.keyword_id,
            TrendingKeyword.keyword,
            TrendingKeyword.source,
            TrendingKeyword.detected_at,
            TrendingKeyword.trend_score,
        )
        .order_by(TrendingKeyword.detected_at.desc())
    )
    if date_from:
        try:
            stmt = stmt.where(TrendingKeyword.detected_at >= datetime.fromisoformat(date_from.replace("Z", "+00:00")))
        except ValueError:
            pass
    if date_to:
        try:
            stmt = stmt.where(TrendingKeyword.detected_at <= datetime.fromisoformat(date_to.replace("Z", "+00:00")))
        except ValueError:
            pass
    stmt = stmt.limit(limit)
    rows = (await session.execute(stmt)).all()

    return {
        "keywords": [
            {
                "id": kid,
                "keyword": kw,
                "source": src or "trending",
                "detected_at": dt.isoformat() if dt else "",
                "score": score,
            }
            for kid, kw, src, dt, score in rows
        ],
        "count": len(rows),
    }


# ─── Export endpoints: PDF & CSV ─────────────────────────────────────────────


@router.get("/content/{content_id}/pdf")
async def download_content_pdf(
    content_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Download a single content classification result as a PDF report."""
    row = (
        await session.execute(
            _content_base_select().where(Content.content_id == content_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Content not found")

    item = await _row_to_item(row)
    pdf_bytes = generate_content_pdf(item)

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="klasifikasi_konten_{content_id}.pdf"',
        },
    )

