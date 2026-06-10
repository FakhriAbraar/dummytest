"""Auto-crawler schedule configuration API.

Exposes the singleton :class:`~app.db.tables.CrawlerSchedule` row to the admin
UI and applies changes to the live :mod:`app.services.scheduler`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.sql import get_db_session
from app.db.tables import CrawlerSchedule
from app.services import scheduler

router = APIRouter(prefix="/schedule", tags=["Auto Crawler Schedule"])

DB = Annotated[AsyncSession, Depends(get_db_session)]

ScheduleMode = Literal["interval", "daily", "monthly"]
MonthlyMode = Literal["specific", "range"]


class TimeOfDay(BaseModel):
    """Satu waktu eksekusi (jam:menit) untuk jadwal harian/bulanan."""

    hour: int = Field(default=8, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)


class ScheduleConfigIn(BaseModel):
    """Editable auto-crawler settings submitted from the admin page.

    Hanya satu `mode` aktif. Mode harian & bulanan mendukung beberapa jam
    eksekusi (`times`). Mode bulanan bisa beberapa tanggal spesifik
    (`days_of_month`) atau rentang tanggal (`day_range_start`..`day_range_end`).
    Jumlah konten & keyword tidak dibatasi ketat; depth maksimal 3.
    """

    enabled: bool = False
    mode: ScheduleMode = "interval"
    interval_hours: int = Field(default=6, ge=1, le=720)
    start_hour: int = Field(default=8, ge=0, le=23)
    start_minute: int = Field(default=0, ge=0, le=59)

    # Harian & bulanan: beberapa jam eksekusi.
    times: list[TimeOfDay] = Field(default_factory=list)

    # Bulanan.
    monthly_mode: MonthlyMode = "specific"
    days_of_month: list[int] = Field(default_factory=list)
    day_of_month: int = Field(default=1, ge=1, le=28)  # legacy / fallback
    day_range_start: int = Field(default=1, ge=1, le=28)
    day_range_end: int = Field(default=28, ge=1, le=28)

    trends_keyword_count: int = Field(default=3, ge=1, le=1000)
    max_content_x: int = Field(default=3, ge=0, le=1000)
    max_content_instagram: int = Field(default=3, ge=0, le=1000)
    max_content_tiktok: int = Field(default=3, ge=0, le=1000)
    max_depth: int = Field(default=2, ge=1, le=3)
    custom_keywords: list[str] = Field(default_factory=list)


class ScheduleConfigOut(ScheduleConfigIn):
    """Current settings plus read-only scheduler status."""

    last_run_at: datetime | None = None
    updated_at: datetime | None = None
    next_run_at: datetime | None = None


def _to_out(cfg: CrawlerSchedule) -> ScheduleConfigOut:
    raw_times = cfg.times or []
    times = [
        TimeOfDay(hour=int(t.get("hour", 0)), minute=int(t.get("minute", 0)))
        for t in raw_times
        if isinstance(t, dict)
    ]
    if not times:
        # Fallback agar UI selalu punya minimal satu baris jam.
        times = [TimeOfDay(hour=cfg.start_hour, minute=cfg.start_minute)]

    days = [int(d) for d in (cfg.days_of_month or []) if d is not None]
    if not days:
        days = [cfg.day_of_month]

    return ScheduleConfigOut(
        enabled=cfg.enabled,
        mode=cast(ScheduleMode, cfg.mode),
        interval_hours=cfg.interval_hours,
        start_hour=cfg.start_hour,
        start_minute=cfg.start_minute,
        times=times,
        monthly_mode=cast(MonthlyMode, cfg.monthly_mode or "specific"),
        days_of_month=days,
        day_of_month=cfg.day_of_month,
        day_range_start=cfg.day_range_start,
        day_range_end=cfg.day_range_end,
        trends_keyword_count=cfg.trends_keyword_count,
        max_content_x=cfg.max_content_x,
        max_content_instagram=cfg.max_content_instagram,
        max_content_tiktok=cfg.max_content_tiktok,
        max_depth=cfg.max_depth,
        custom_keywords=list(cfg.custom_keywords or []),
        last_run_at=cfg.last_run_at,
        updated_at=cfg.updated_at,
        next_run_at=scheduler.get_next_run_time(),
    )


async def _get_or_create(session: AsyncSession) -> CrawlerSchedule:
    """Return the singleton config row, creating a default (disabled) one."""
    cfg = await session.get(CrawlerSchedule, 1)
    if cfg is None:
        cfg = CrawlerSchedule(id=1, updated_at=datetime.now(tz=timezone.utc))
        session.add(cfg)
        await session.commit()
        await session.refresh(cfg)
    return cfg


@router.get("", response_model=ScheduleConfigOut)
async def get_schedule(session: DB) -> ScheduleConfigOut:
    cfg = await _get_or_create(session)
    return _to_out(cfg)


@router.put("", response_model=ScheduleConfigOut)
async def update_schedule(payload: ScheduleConfigIn, session: DB) -> ScheduleConfigOut:
    cfg = await _get_or_create(session)
    cfg.enabled = payload.enabled
    cfg.mode = payload.mode
    cfg.interval_hours = payload.interval_hours
    cfg.start_hour = payload.start_hour
    cfg.start_minute = payload.start_minute
    cfg.day_of_month = payload.day_of_month

    # Normalisasi daftar jam: buang duplikat, urutkan, minimal satu entri.
    seen: set[tuple[int, int]] = set()
    norm_times: list[dict[str, int]] = []
    for t in payload.times:
        key = (t.hour, t.minute)
        if key not in seen:
            seen.add(key)
            norm_times.append({"hour": t.hour, "minute": t.minute})
    if not norm_times:
        norm_times = [{"hour": payload.start_hour, "minute": payload.start_minute}]
    norm_times.sort(key=lambda x: (x["hour"], x["minute"]))
    cfg.times = norm_times

    cfg.monthly_mode = payload.monthly_mode
    # Tanggal spesifik: unik, dalam 1..28, terurut.
    cfg.days_of_month = sorted(
        {d for d in payload.days_of_month if 1 <= d <= 28}
    ) or [payload.day_of_month]
    lo, hi = payload.day_range_start, payload.day_range_end
    if lo > hi:
        lo, hi = hi, lo
    cfg.day_range_start = lo
    cfg.day_range_end = hi

    cfg.trends_keyword_count = payload.trends_keyword_count
    cfg.max_content_x = payload.max_content_x
    cfg.max_content_instagram = payload.max_content_instagram
    cfg.max_content_tiktok = payload.max_content_tiktok
    cfg.max_depth = payload.max_depth
    cfg.custom_keywords = [k.strip() for k in payload.custom_keywords if k.strip()]
    cfg.updated_at = datetime.now(tz=timezone.utc)
    await session.commit()
    await session.refresh(cfg)
    # Apply to the live scheduler while the row is still attached/loaded.
    scheduler.reschedule_from_config(cfg)
    return _to_out(cfg)


@router.post("/run-now")
async def run_now(session: DB) -> dict[str, Any]:
    """Fire one crawl immediately using the saved config (ignores enabled/schedule)."""
    cfg = await _get_or_create(session)
    config = scheduler.crawl_config_from_row(cfg)
    cfg.last_run_at = datetime.now(tz=timezone.utc)
    await session.commit()
    job = scheduler.spawn_crawl(config)
    return {"job_id": job.job_id, "status": job.status}
