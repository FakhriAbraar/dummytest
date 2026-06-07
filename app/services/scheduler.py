"""Live auto-crawler scheduler (APScheduler).

A single in-process :class:`AsyncIOScheduler` runs one job, ``auto_crawl``, whose
trigger is derived from the singleton :class:`~app.db.tables.CrawlerSchedule`
config row. When the job fires it re-reads the latest config and launches a crawl
through the shared :func:`~app.services.job_runner.run_crawl_job`, so scheduled
runs show up in the same job tracker / report history as manual ones.

Assumes a single uvicorn worker (see ``settings.workers_count``), matching the
assumption already made by ``job_tracker``.
"""

from __future__ import annotations

import asyncio
import traceback
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.db.sql import get_session_factory
from app.db.tables import CrawlerSchedule
from app.services import job_tracker
from app.services.job_runner import run_crawl_job

WIB = ZoneInfo("Asia/Jakarta")
_JOB_PREFIX = "auto_crawl"  # semua job auto-crawl pakai prefix ini (bisa >1)

_scheduler: AsyncIOScheduler | None = None
_keyword_model: Any = None
# Keep strong refs to detached crawl tasks so they aren't GC'd mid-run.
_RUNNING_TASKS: set[asyncio.Task[None]] = set()


def set_keyword_model(model: Any) -> None:
    """Stash the loaded GGUF keyword model so scheduled crawls can use it."""
    global _keyword_model  # noqa: PLW0603
    _keyword_model = model


def _ensure_scheduler() -> AsyncIOScheduler:
    global _scheduler  # noqa: PLW0603
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone=WIB)
    if not _scheduler.running:
        _scheduler.start()
    return _scheduler


def crawl_config_from_row(cfg: CrawlerSchedule) -> dict[str, Any]:
    """Build the crawl-job config dict expected by ``run_crawl_job``."""
    return {
        "keywords": list(cfg.custom_keywords or []),
        "max_depth": cfg.max_depth,
        "max_content_x": cfg.max_content_x,
        "max_content_instagram": cfg.max_content_instagram,
        "max_content_tiktok": cfg.max_content_tiktok,
        "trends_keyword_count": cfg.trends_keyword_count,
    }


def _times_of_day(cfg: CrawlerSchedule) -> list[tuple[int, int]]:
    """Daftar (jam, menit) eksekusi untuk mode harian/bulanan.

    Fallback ke start_hour:start_minute bila `times` kosong (kompat data lama).
    """
    raw = cfg.times or []
    pairs: list[tuple[int, int]] = []
    for t in raw:
        if isinstance(t, dict):
            pairs.append((int(t.get("hour", 0)), int(t.get("minute", 0))))
    if not pairs:
        pairs = [(cfg.start_hour, cfg.start_minute)]
    # unik + terurut
    return sorted(set(pairs))


def _monthly_day_expr(cfg: CrawlerSchedule) -> str:
    """Ekspresi `day` untuk CronTrigger bulanan: "1,5,20" (specific) atau "1-15" (range)."""
    if (cfg.monthly_mode or "specific") == "range":
        lo = max(1, min(28, cfg.day_range_start))
        hi = max(1, min(28, cfg.day_range_end))
        if lo > hi:
            lo, hi = hi, lo
        return f"{lo}-{hi}"
    days = sorted({int(d) for d in (cfg.days_of_month or []) if 1 <= int(d) <= 28})
    if not days:
        days = [cfg.day_of_month]
    return ",".join(str(d) for d in days)


def _build_triggers(cfg: CrawlerSchedule) -> list[CronTrigger | IntervalTrigger]:
    """Map jadwal tersimpan ke satu/lebih trigger APScheduler (Asia/Jakarta).

    - interval : satu IntervalTrigger (tiap N jam dari jam patokan).
    - daily    : satu CronTrigger per jam eksekusi.
    - monthly  : satu CronTrigger per jam eksekusi, dengan ekspresi tanggal
                 (beberapa tanggal atau rentang).
    """
    if cfg.mode == "daily":
        return [
            CronTrigger(hour=h, minute=m, timezone=WIB)
            for (h, m) in _times_of_day(cfg)
        ]
    if cfg.mode == "monthly":
        day_expr = _monthly_day_expr(cfg)
        return [
            CronTrigger(day=day_expr, hour=h, minute=m, timezone=WIB)
            for (h, m) in _times_of_day(cfg)
        ]
    # interval (default): every N hours, anchored to today's start_hour:start_minute.
    now = datetime.now(WIB)
    start = now.replace(
        hour=cfg.start_hour, minute=cfg.start_minute, second=0, microsecond=0
    )
    return [IntervalTrigger(hours=cfg.interval_hours, start_date=start, timezone=WIB)]


def spawn_crawl(config: dict[str, Any]) -> job_tracker.Job:
    """Create a tracked job and run it as a detached task. Returns the job."""
    job = job_tracker.create_job(config)
    task = asyncio.create_task(run_crawl_job(job, _keyword_model))
    _RUNNING_TASKS.add(task)
    task.add_done_callback(_RUNNING_TASKS.discard)
    return job


async def _run_scheduled_crawl() -> None:
    """APScheduler callback: re-read config, stamp last_run, fire one crawl."""
    factory = get_session_factory()
    if factory is None:
        print("[scheduler] DB not ready; skipping tick.")  # noqa: T201
        return
    try:
        async with factory() as session:
            cfg = await session.get(CrawlerSchedule, 1)
            if cfg is None or not cfg.enabled:
                print("[scheduler] Auto-crawl disabled; skipping tick.")  # noqa: T201
                return
            config = crawl_config_from_row(cfg)
            cfg.last_run_at = datetime.now(tz=timezone.utc)
            await session.commit()
        print(  # noqa: T201
            f"[scheduler] Auto-crawl tick {datetime.now(WIB):%Y-%m-%d %H:%M %Z}"
        )
        spawn_crawl(config)
    except Exception as exc:  # never let a tick kill the scheduler
        print(f"[scheduler] Tick failed: {exc}")  # noqa: T201
        traceback.print_exc()


def reschedule_from_config(cfg: CrawlerSchedule) -> None:
    """(Re)register the auto_crawl job from ``cfg``; remove it when disabled.

    Reads ``cfg`` attributes synchronously, so the caller must invoke this while
    the row is still attached/loaded (e.g. before the session closes).
    """
    sched = _ensure_scheduler()
    # Bersihkan semua job auto-crawl lama (bisa lebih dari satu).
    for job in sched.get_jobs():
        if job.id and job.id.startswith(_JOB_PREFIX):
            sched.remove_job(job.id)
    if not cfg.enabled:
        print("[scheduler] Auto-crawl disabled; no job scheduled.")  # noqa: T201
        return
    triggers = _build_triggers(cfg)
    for idx, trigger in enumerate(triggers):
        sched.add_job(
            _run_scheduled_crawl,
            trigger=trigger,
            id=f"{_JOB_PREFIX}_{idx}",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
    nxt = get_next_run_time()
    print(  # noqa: T201
        f"[scheduler] Auto-crawl scheduled (mode={cfg.mode}, {len(triggers)} jadwal); "
        f"next run: {nxt}"
    )


def get_next_run_time() -> datetime | None:
    """Waktu fire terdekat di antara semua job auto-crawl (Asia/Jakarta)."""
    if _scheduler is None:
        return None
    candidates = [
        job.next_run_time
        for job in _scheduler.get_jobs()
        if job.id and job.id.startswith(_JOB_PREFIX) and job.next_run_time
    ]
    return min(candidates) if candidates else None


async def start_scheduler() -> None:
    """Lifespan startup: start the scheduler and register the job if enabled."""
    _ensure_scheduler()  # creates and starts the AsyncIOScheduler
    factory = get_session_factory()
    if factory is None:
        print("[scheduler] DB not ready at startup; scheduler idle.")  # noqa: T201
        return
    async with factory() as session:
        cfg = await session.get(CrawlerSchedule, 1)
        if cfg is not None and cfg.enabled:
            reschedule_from_config(cfg)
        else:
            print("[scheduler] No enabled auto-crawl config; scheduler idle.")  # noqa: T201


def shutdown_scheduler() -> None:
    """Lifespan shutdown: stop the scheduler without waiting for running jobs."""
    global _scheduler  # noqa: PLW0603
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None
