"""Shared crawl-job executor.

Runs one configured crawl through the LangGraph pipeline, reporting per-stage
progress to a :class:`job_tracker.Job`. Used by both the manual crawl endpoint
(``app.api.pad.crawler``) and the auto-crawler scheduler
(``app.services.scheduler``) so they share a single code path.
"""

from __future__ import annotations

import asyncio
import traceback
from datetime import datetime, timezone

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.db.sql import get_session_factory
from app.services import job_tracker
from app.services.graph import build_pad_workflow
from app.services.log_stream import current_job
from app.services.report_service import save_mission_report


async def run_crawl_job(job: job_tracker.Job, keyword_model: object) -> None:
    """Execute one configured crawl, reporting per-stage progress to ``job``.

    Runs as a detached background task with its own DB session (the request or
    scheduler tick that created the job has already returned). Binds ``job`` to
    the log-capture context var so every ``print()`` in the pipeline (and its
    child tasks / threads) is mirrored into the job's live log buffer.
    """
    log_token = current_job.set(job)
    try:
        await _run_crawl_job(job, keyword_model)
    except asyncio.CancelledError:
        # User pressed Stop: cancellation propagates here (CancelledError is a
        # BaseException, so the broad `except Exception` inside _run_crawl_job
        # does not swallow it). Record it as a clean stop, not a crash.
        print(f"[job_runner] job={job.job_id[:8]} DIHENTIKAN oleh pengguna.")  # noqa: T201
        job.mark_cancelled()
    finally:
        job.flush_log()
        current_job.reset(log_token)


async def _run_crawl_job(job: job_tracker.Job, keyword_model: object) -> None:
    job.mark_running()
    cfg = job.config
    mission_id = job.job_id
    started_at = datetime.now(tz=timezone.utc)

    session_factory = get_session_factory()
    if session_factory is None:
        job.mark_failed("Database not initialized.")
        return

    try:
        job.start_stage("Initializing Engine")
        initial_state = {
            "seed_trend": "",
            "custom_keywords": cfg.get("keywords", []),
            "platform_limits": {
                "x": cfg.get("max_content_x", 5),
                "instagram": cfg.get("max_content_instagram", 5),
                "tiktok": cfg.get("max_content_tiktok", 5),
            },
            "trends_keyword_count": cfg.get("trends_keyword_count", 3),
            "current_keywords": [],
            "history_keywords": [],
            "raw_contents": [],
            "unsafe_contents": [],
            "all_processed_contents": [],
            "extracted_entities": [],
            "total_processed_contents": 0,
            "crawling_depth": 0,
            "max_depth": cfg.get("max_depth", 3),
        }

        async with session_factory() as session:
            workflow = build_pad_workflow(keyword_model, session, progress=job)
            job.complete_stage("Initializing Engine")

            async with AsyncSqliteSaver.from_conn_string("pad_checkpoint.db") as checkpointer:
                app = workflow.compile(checkpointer=checkpointer)
                config = {"configurable": {"thread_id": mission_id}}
                final_state = await app.ainvoke(initial_state, config=config)

            finished_at = datetime.now(tz=timezone.utc)
            unsafe_entities = final_state.get("extracted_entities", [])
            all_entities = final_state.get("all_processed_contents", [])

            job.start_stage("Storing Results")
            stats = await save_mission_report(
                session,
                mission_id=mission_id,
                seed_trend="",
                max_depth=cfg.get("max_depth", 3),
                depth_reached=final_state.get("crawling_depth", 0),
                extracted_entities=all_entities,
                history_keywords=final_state.get("history_keywords", []),
                started_at=started_at,
                finished_at=finished_at,
            )
            job.complete_stage("Storing Results")

        job.mark_completed(
            {
                "mission_id": mission_id,
                "total_putaran": final_state.get("crawling_depth", 0),
                "total_bukti_dikumpulkan": len(unsafe_entities),
                "stats": stats,
                "data_pelanggaran": unsafe_entities,
            }
        )

    except Exception as e:  # surface any failure to the UI
        print(f"[job_runner] FATAL job={mission_id[:8]}: {e}")  # noqa: T201
        traceback.print_exc()
        job.mark_failed(e)
