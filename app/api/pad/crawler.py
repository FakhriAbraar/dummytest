import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.graph import build_pad_workflow
from app.services.report_service import (
    get_mission_by_id,
    get_recent_missions,
    save_mission_report,
)
from app.services import job_tracker
from app.services.job_runner import run_crawl_job
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.db.sql import get_db_session

router = APIRouter(prefix="/crawler", tags=["Agentic Crawler"])

# Keep strong references to in-flight background tasks so they are not GC'd.
_RUNNING_TASKS: set[asyncio.Task] = set()


class TriggerRequest(BaseModel):
    seed_trend: str = ""
    max_depth: int = 3


class StartCrawlRequest(BaseModel):
    """Crawl configuration submitted from the dedicated config page.

    Depth dibatasi maksimal 3 (sesuai kebutuhan operasional). Jumlah konten &
    keyword tidak dibatasi ketat (hanya soft-cap besar agar tidak meledak).
    """

    keywords: list[str] = Field(default_factory=list)
    max_depth: int = Field(default=2, ge=1, le=3)
    max_content_x: int = Field(default=3, ge=0, le=1000)
    max_content_instagram: int = Field(default=3, ge=0, le=1000)
    max_content_tiktok: int = Field(default=3, ge=0, le=1000)
    trends_keyword_count: int = Field(default=3, ge=1, le=1000)


@router.post("/trigger")
async def trigger_agentic_crawler(
    request: TriggerRequest,
    fastapi_req: Request,
    session: AsyncSession = Depends(get_db_session),
):
    mission_id = str(uuid.uuid4())
    started_at = datetime.now(tz=timezone.utc)
    print(f"\n[crawler_api] mission START id={mission_id[:8]} seed={request.seed_trend!r} depth={request.max_depth}")

    initial_state = {
        "seed_trend": request.seed_trend,
        "current_keywords": [],
        "history_keywords": [],
        "raw_contents": [],
        "unsafe_contents": [],
        "all_processed_contents": [],
        "extracted_entities": [],
        "total_processed_contents": 0,
        "crawling_depth": 0,
        "max_depth": request.max_depth,
    }

    workflow = build_pad_workflow(session)

    try:
        async with AsyncSqliteSaver.from_conn_string("pad_checkpoint.db") as checkpointer:
            app = workflow.compile(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": mission_id}}
            final_state = await app.ainvoke(initial_state, config=config)

        finished_at = datetime.now(tz=timezone.utc)
        unsafe_entities = final_state.get("extracted_entities", [])
        all_entities = final_state.get("all_processed_contents", [])

        stats = await save_mission_report(
            session,
            mission_id=mission_id,
            seed_trend=request.seed_trend,
            max_depth=request.max_depth,
            depth_reached=final_state.get("crawling_depth", 0),
            extracted_entities=all_entities,
            history_keywords=final_state.get("history_keywords", []),
            started_at=started_at,
            finished_at=finished_at,
        )

        return {
            "status": "success",
            "message": "Operasi selesai.",
            "mission_id": mission_id,
            "total_putaran": final_state.get("crawling_depth", 0),
            "total_bukti_dikumpulkan": len(unsafe_entities),
            "stats": stats,
            "data_pelanggaran": unsafe_entities,
        }

    except Exception as e:
        print(f"[crawler_api] FATAL pipeline error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reports")
async def get_crawler_reports(
    limit: int = 10,
    session: AsyncSession = Depends(get_db_session),
):
    reports = await get_recent_missions(session, limit=limit)
    return {"reports": reports, "count": len(reports)}


@router.get("/reports/{mission_id}")
async def get_crawler_report_detail(
    mission_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    report = await get_mission_by_id(session, mission_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


# ── Job-based crawl with detailed, real-time stage tracking ──────────────────
# The per-stage executor lives in app.services.job_runner.run_crawl_job so the
# auto-crawler scheduler can reuse the exact same code path.


@router.post("/start")
async def start_crawl_job(request: StartCrawlRequest, fastapi_req: Request):
    """Create a crawl job from the config form and run it in the background.

    Returns immediately with a `job_id` the frontend polls via `/crawler/jobs/{id}`.
    """
    job = job_tracker.create_job(request.model_dump())

    task = asyncio.create_task(run_crawl_job(job))
    job.attach_task(task)
    _RUNNING_TASKS.add(task)
    task.add_done_callback(_RUNNING_TASKS.discard)

    return {"job_id": job.job_id, "status": job.status}


@router.post("/jobs/{job_id}/stop")
async def stop_crawl_job(job_id: str):
    """Stop a running crawl job by cancelling its background task.

    Returns immediately; the job's status flips to ``cancelled`` once the task
    unwinds (the frontend's poll picks it up). Note: a crawler subprocess already
    in flight finishes in its own OS thread — stopping halts the pipeline
    orchestration, it cannot kill an in-progress external scrape mid-call.
    """
    job = job_tracker.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} tidak ditemukan.")

    if job.status not in ("pending", "running"):
        return {
            "job_id": job_id,
            "status": job.status,
            "stopped": False,
            "message": "Job sudah selesai; tidak ada yang dihentikan.",
        }

    signalled = job.request_stop()
    return {
        "job_id": job_id,
        "status": "stopping",
        "stopped": signalled,
        "message": "Permintaan stop dikirim." if signalled else "Job ditandai stop.",
    }


@router.get("/jobs")
async def list_crawl_jobs():
    return {"jobs": [job.to_dict() for job in job_tracker.list_jobs()]}


@router.get("/jobs/{job_id}")
async def get_crawl_job(job_id: str):
    job = job_tracker.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} tidak ditemukan.")
    return job.to_dict()


@router.get("/jobs/{job_id}/logs")
async def stream_crawl_job_logs(job_id: str):
    """Server-Sent Events stream of the raw backend log lines for a crawl job.

    Powers the live console in the Pipeline Monitoring panel. Emits each new
    captured line as a `data:` event, then a final `event: done` once the job
    reaches a terminal state and all buffered lines have been sent.
    """
    job = job_tracker.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} tidak ditemukan.")

    async def event_gen():
        last_seq = 0
        while True:
            pending = [e for e in job.logs if e["seq"] > last_seq]
            if pending:
                for entry in pending:
                    yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
                last_seq = pending[-1]["seq"]
            elif job.status in ("completed", "failed", "cancelled"):
                yield f"event: done\ndata: {job.status}\n\n"
                break
            await asyncio.sleep(0.35)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
