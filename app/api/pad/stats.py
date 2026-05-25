from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.sql import get_db_session
from app.db.tables import Account, Content, EngineDecision, Platform, TrendingKeyword
from app.services.minio import get_presigned_url

router = APIRouter(prefix="/stats", tags=["Stats"])


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

    return {
        "total_content": total,
        "safe_content": safe,
        "unsafe_content": unsafe,
        "platforms": platforms,
        "top_keywords": top_keywords,
        "pipeline_status": {},
    }


@router.get("/content")
async def get_content_list(
    q: str = "",
    platform: str = "",
    classification: str = "",
    age_group: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
    per_page: int = 12,
    session: AsyncSession = Depends(get_db_session),
):
    from datetime import datetime

    stmt = (
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
        )
        .join(Account, Content.account_id == Account.account_id)
        .join(Platform, Account.platform_id == Platform.platform_id)
        .outerjoin(EngineDecision, EngineDecision.content_id == Content.content_id)
    )

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
            stmt = stmt.where(Content.crawl_timestamp >= datetime.fromisoformat(date_from.replace("Z", "+00:00")))
        except ValueError:
            pass
    if date_to:
        try:
            stmt = stmt.where(Content.crawl_timestamp <= datetime.fromisoformat(date_to.replace("Z", "+00:00")))
        except ValueError:
            pass

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar_one()
    max_page = max(1, (total + per_page - 1) // per_page)

    stmt = stmt.order_by(Content.crawl_timestamp.desc()).offset((page - 1) * per_page).limit(per_page)
    rows = (await session.execute(stmt)).all()

    items = []
    for row in rows:
        (cid, plat, username, desc, eng_status, rating, src_url, crawled_at, raw_meta, kategori) = row
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

        items.append({
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
            "createdAt": crawled_at.isoformat() if crawled_at else "",
        })

    return {
        "data_per_page": items,
        "meta": {"page": page, "max_page": max_page, "total": total},
    }


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
            }
            for kid, kw, src, dt in rows
        ],
        "count": len(rows),
    }
