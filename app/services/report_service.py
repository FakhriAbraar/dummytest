"""
Report Service — persists mission results to PostgreSQL after agentic pipeline completes.
Saves: AgentExecutionLog (mission summary) + Content + EngineDecision per entity.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import (
    Account,
    AgentExecutionLog,
    AiAgent,
    Content,
    EngineDecision,
    IGRSRules,
    Platform,
    TrendingKeyword,
)
from app.services.screenshot_service import take_screenshots_for_urls

_PLATFORM_URL_MAP = {
    "instagram": "https://www.instagram.com",
    "tiktok": "https://www.tiktok.com",
    "twitter": "https://www.twitter.com",
    "youtube": "https://www.youtube.com",
}

_PLATFORM_DISPLAY = {
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "twitter": "Twitter",
    "youtube": "YouTube",
}

_ENGINE_STATUS_BY_RATING = {
    "SU": "SAFE",
    "7+": "SAFE",
    "13+": "NEEDS_REVIEW",
    "17+": "VIOLATION",
    "PRC": "VIOLATION",
}


async def _get_or_create_crawler_agent(session: AsyncSession) -> AiAgent:
    result = await session.execute(
        select(AiAgent).where(AiAgent.agent_name == "PAD Crawler Agent")
    )
    agent = result.scalars().first()
    if agent:
        return agent

    agent = AiAgent(
        agent_name="PAD Crawler Agent",
        agent_type="crawler",
        model_version="1.0.0",
        configuration={"pipeline": "langgraph", "crawlers": ["instagram", "tiktok"]},
        status="ACTIVE",
        deployed_at=datetime.now(tz=timezone.utc),
    )
    session.add(agent)
    await session.flush()
    return agent


async def _get_or_create_platform(session: AsyncSession, name: str) -> Platform:
    canonical = name.strip().lower()
    display = _PLATFORM_DISPLAY.get(canonical, canonical.capitalize())
    result = await session.execute(
        select(Platform).where(Platform.platform_name.ilike(canonical))
    )
    platform = result.scalars().first()
    if platform:
        return platform

    platform = Platform(
        platform_name=display,
        base_url=_PLATFORM_URL_MAP.get(canonical, f"https://www.{canonical}.com"),
        is_active=True,
        created_at=datetime.now(tz=timezone.utc),
    )
    session.add(platform)
    await session.flush()
    return platform


_USERNAME_FROM_URL_PATTERNS = [
    re.compile(r"tiktok\.com/@([\w.\-]+)/", re.IGNORECASE),
    re.compile(r"instagram\.com/([\w.\-]+)/", re.IGNORECASE),
    re.compile(r"(?:twitter|x)\.com/([\w.\-]+)/status/", re.IGNORECASE),
    re.compile(r"youtube\.com/(?:@|c/|user/)([\w.\-]+)", re.IGNORECASE),
]


def _extract_username_from_url(url: str) -> str:
    if not url:
        return ""
    for pat in _USERNAME_FROM_URL_PATTERNS:
        m = pat.search(url)
        if m:
            return m.group(1).strip("@/")
    return ""


def _normalize_username(raw: str) -> str:
    return "@" + raw.lstrip("@").strip()


async def _get_or_create_crawler_account(session: AsyncSession, platform: Platform) -> Account:
    """Legacy: bikin satu Account generic per-platform (@pad_crawler_{platform}).
    Dipertahankan untuk kompatibilitas; flow utama sekarang pakai _get_or_create_account
    dengan real username dari scraper.
    """
    crawler_username = f"@pad_crawler_{(platform.platform_name or 'unknown').lower()}"
    result = await session.execute(
        select(Account).where(
            Account.platform_id == platform.platform_id,
            Account.username == crawler_username,
        )
    )
    account = result.scalars().first()
    if account:
        return account

    account = Account(
        platform_id=platform.platform_id,
        username=crawler_username,
        profile_url=f"{platform.base_url}/pad_crawler",
        account_category="anonim",
        risk_score=0.0,
        content_count=0,
        last_updated_at=datetime.now(tz=timezone.utc),
    )
    session.add(account)
    await session.flush()
    return account


async def _get_or_create_account(
    session: AsyncSession,
    platform: Platform,
    username: str,
    profile_url: str = "",
) -> Account:
    platform_slug = (platform.platform_name or "unknown").lower()
    canonical = _normalize_username(username) if username else f"@unknown_{platform_slug}"

    result = await session.execute(
        select(Account).where(
            Account.platform_id == platform.platform_id,
            Account.username == canonical,
        )
    )
    account = result.scalars().first()
    if account:
        return account

    account = Account(
        platform_id=platform.platform_id,
        username=canonical,
        profile_url=profile_url or f"{platform.base_url}/{canonical.lstrip('@')}",
        account_category="anonim",
        risk_score=0.0,
        content_count=0,
        last_updated_at=datetime.now(tz=timezone.utc),
    )
    session.add(account)
    await session.flush()
    return account


async def _get_igrs_rule(session: AsyncSession, kategori: str) -> IGRSRules | None:
    result = await session.execute(
        select(IGRSRules).where(IGRSRules.kategori_ai == kategori)
    )
    return result.scalars().first()


def _compute_stats(entities: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(entities)
    by_platform: dict[str, int] = {}
    by_age_group: dict[str, int] = {}
    unsafe_count = 0

    for e in entities:
        vonis = e.get("vonis_hukum", {})
        raw_plat = (e.get("platform") or "unknown").lower()
        platform = _PLATFORM_DISPLAY.get(raw_plat, raw_plat.capitalize())
        rating = vonis.get("rating", "SU")

        by_platform[platform] = by_platform.get(platform, 0) + 1
        by_age_group[rating] = by_age_group.get(rating, 0) + 1

        if rating in {"13+", "17+", "PRC"}:
            unsafe_count += 1

    return {
        "total": total,
        "unsafe": unsafe_count,
        "safe": total - unsafe_count,
        "by_platform": by_platform,
        "by_age_group": by_age_group,
    }


async def save_mission_report(
    session: AsyncSession,
    *,
    mission_id: str,
    seed_trend: str,
    max_depth: int,
    depth_reached: int,
    extracted_entities: list[dict[str, Any]],
    history_keywords: list[str],
    started_at: datetime,
    finished_at: datetime,
) -> dict[str, Any]:
    stats = _compute_stats(extracted_entities)

    agent = await _get_or_create_crawler_agent(session)

    log = AgentExecutionLog(
        agent_id=agent.agent_id,
        execution_start=started_at,
        execution_end=finished_at,
        status="success",
        input_payload={
            "mission_id": mission_id,
            "seed_trend": seed_trend,
            "max_depth": max_depth,
            "depth_reached": depth_reached,
        },
        output_result={
            "mission_id": mission_id,
            "total_created": stats["total"],
            "safe": stats["safe"],
            "unsafe": stats["unsafe"],
            "by_platform": stats["by_platform"],
            "by_age_group": stats["by_age_group"],
            "entities_preview": [
                {
                    "platform": e.get("platform"),
                    "url": e.get("url"),
                    "kategori": e.get("vonis_hukum", {}).get("kategori"),
                    "rating": e.get("vonis_hukum", {}).get("rating"),
                }
                for e in extracted_entities[:50]
            ],
        },
    )
    session.add(log)
    await session.flush()

    # Batch screenshot evidence: ambil 1x untuk semua URL agar tidak bolak-balik buka browser.
    # Hasil dict: {url: minio_path}. Best-effort — kalau gagal → mapping kosong.
    all_urls = [e.get("url", "") for e in extracted_entities if e.get("url")]
    screenshot_map = await take_screenshots_for_urls(all_urls) if all_urls else {}

    platform_cache: dict[str, Platform] = {}
    account_cache: dict[tuple[str, str], Account] = {}

    for entity in extracted_entities:
        raw_platform = (entity.get("platform") or "unknown").lower()
        if raw_platform not in platform_cache:
            platform_cache[raw_platform] = await _get_or_create_platform(session, raw_platform)
        platform = platform_cache[raw_platform]

        url = entity.get("url", "")
        scraped_username = entity.get("username", "") or _extract_username_from_url(url)
        account_key = (raw_platform, scraped_username.lower())
        if account_key not in account_cache:
            account_cache[account_key] = await _get_or_create_account(
                session, platform, scraped_username,
            )
        account = account_cache[account_key]

        vonis = entity.get("vonis_hukum", {})
        rating = vonis.get("rating", "SU")
        kategori = vonis.get("kategori", "SAFE")
        engine_status = _ENGINE_STATUS_BY_RATING.get(rating, "NEEDS_REVIEW")

        thumbnail_url = entity.get("thumbnail_url", "") or ""
        file_paths = entity.get("file_path") or []
        if not thumbnail_url and file_paths:
            for fp in file_paths:
                if not fp.lower().endswith((".mp4", ".webm", ".mkv", ".mov", ".avi")):
                    thumbnail_url = fp
                    break

        content = Content(
            account_id=account.account_id,
            source_url=url,
            content_type=entity.get("content_type", "text"),
            description=(entity.get("bukti_teks") or "")[:2000],
            crawl_timestamp=finished_at,
            engine_status=engine_status,
            final_rating=rating,
            raw_metadata={
                "mission_id": mission_id,
                "seed_trend": seed_trend,
                "source": raw_platform,
                "reason": vonis.get("reason", ""),
                "thumbnail_url": thumbnail_url,
                "file_path": file_paths,
                "screenshot_path": screenshot_map.get(url, ""),
            },
        )
        session.add(content)
        await session.flush()

        igrs = await _get_igrs_rule(session, kategori)

        decision = EngineDecision(
            content_id=content.content_id,
            igrs_rule_id=igrs.id if igrs else None,
            final_kategori=kategori,
            final_rating=rating,
            is_vetoed=vonis.get("is_vetoed", False),
            decided_at=finished_at,
        )
        session.add(decision)

    for kw in history_keywords:
        kw_clean = kw.strip().lower()
        if not kw_clean:
            continue
        existing = await session.execute(
            select(TrendingKeyword).where(
                TrendingKeyword.agent_id == agent.agent_id,
                TrendingKeyword.keyword == kw_clean,
            )
        )
        if existing.scalars().first() is None:
            session.add(TrendingKeyword(
                agent_id=agent.agent_id,
                keyword=kw_clean,
                source="trending",
                trend_score=1.0,
                trend_status="active",
                detected_at=finished_at,
            ))

    await session.commit()
    print(f"[REPORT] Mission {mission_id[:8]} disimpan: {stats['total']} konten, {stats['unsafe']} berbahaya, {len(history_keywords)} keyword.")
    return stats


def _log_to_report(log: AgentExecutionLog) -> dict[str, Any]:
    """Shape a crawler execution log into the BatchReport the frontend expects."""
    out = log.output_result or {}
    inp = log.input_payload or {}
    return {
        "id": inp.get("mission_id", str(log.log_id)),
        "seed_trend": inp.get("seed_trend", ""),
        "started_at": log.execution_start.isoformat() if log.execution_start else "",
        "finished_at": log.execution_end.isoformat() if log.execution_end else "",
        "total_created": out.get("total_created", 0),
        "safe": out.get("safe", 0),
        "unsafe": out.get("unsafe", 0),
        "by_platform": out.get("by_platform", {}),
        "by_age_group": out.get("by_age_group", {}),
    }


async def get_recent_missions(session: AsyncSession, limit: int = 10) -> list[dict[str, Any]]:
    result = await session.execute(
        select(AgentExecutionLog)
        .join(AiAgent, AgentExecutionLog.agent_id == AiAgent.agent_id)
        .where(AiAgent.agent_name == "PAD Crawler Agent")
        .order_by(AgentExecutionLog.execution_start.desc())
        .limit(limit)
    )
    return [_log_to_report(log) for log in result.scalars().all()]


async def get_mission_by_id(
    session: AsyncSession, mission_id: str
) -> dict[str, Any] | None:
    """Single mission report by its mission_id (the BatchReport `id`).

    Powers the laporan-hasil detail page (/admin/report/[id]). Matches the
    mission_id stored in input_payload; falls back to the numeric log_id used
    by older rows that predate mission_id tracking.
    """
    base = (
        select(AgentExecutionLog)
        .join(AiAgent, AgentExecutionLog.agent_id == AiAgent.agent_id)
        .where(AiAgent.agent_name == "PAD Crawler Agent")
    )

    result = await session.execute(
        base.where(AgentExecutionLog.input_payload["mission_id"].astext == mission_id)
        .order_by(AgentExecutionLog.execution_start.desc())
        .limit(1)
    )
    log = result.scalars().first()

    if log is None and mission_id.isdigit():
        result = await session.execute(
            base.where(AgentExecutionLog.log_id == int(mission_id)).limit(1)
        )
        log = result.scalars().first()

    return _log_to_report(log) if log else None
