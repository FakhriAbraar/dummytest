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
_JOB_ID = "auto_crawl"

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


def _build_trigger(cfg: CrawlerSchedule) -> CronTrigger | IntervalTrigger:
    """Map the stored schedule onto an APScheduler trigger (Asia/Jakarta)."""
    if cfg.mode == "daily":
        return CronTrigger(hour=cfg.start_hour, minute=cfg.start_minute, timezone=WIB)
    if cfg.mode == "monthly":
        return CronTrigger(
            day=cfg.day_of_month,
            hour=cfg.start_hour,
            minute=cfg.start_minute,
            timezone=WIB,
        )
    # interval (default): every N hours, anchored to today's start_hour:start_minute.
    now = datetime.now(WIB)
    start = now.replace(
        hour=cfg.start_hour, minute=cfg.start_minute, second=0, microsecond=0
    )
    return IntervalTrigger(hours=cfg.interval_hours, start_date=start, timezone=WIB)


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
    if sched.get_job(_JOB_ID):
        sched.remove_job(_JOB_ID)
    if not cfg.enabled:
        print("[scheduler] Auto-crawl disabled; no job scheduled.")  # noqa: T201
        return
    sched.add_job(
        _run_scheduled_crawl,
        trigger=_build_trigger(cfg),
        id=_JOB_ID,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    job = sched.get_job(_JOB_ID)
    nxt = job.next_run_time if job else None
    print(f"[scheduler] Auto-crawl scheduled (mode={cfg.mode}); next run: {nxt}")  # noqa: T201


def get_next_run_time() -> datetime | None:
    """Next scheduled fire time (Asia/Jakarta), or None when idle/disabled."""
    if _scheduler is None:
        return None
    job = _scheduler.get_job(_JOB_ID)
    return job.next_run_time if job else None


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
