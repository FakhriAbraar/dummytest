"""In-memory crawl-job registry with per-stage progress tracking.

Powers the "Detailed Crawl Progress & Logs" view (see revision.md). A job holds
the ordered list of pipeline stages; the pipeline nodes report transitions
(running / completed / failed) through the same Job handle while they execute.

State lives in process memory only — it is intentionally lightweight for the POC
and is lost on restart. A single uvicorn worker is assumed.
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

# Ordered stages shown in the UI. Stages map onto the LangGraph pipeline nodes.
STAGE_SEQUENCE: list[str] = [
    "Initializing Engine",
    "Loading Keywords",
    "Fetching Trending Keywords",
    "Crawling X",
    "Crawling Instagram",
    "Crawling TikTok",
    "Saving Raw Content",
    "Running Classification",
    "Generating RAG Analysis",
    "Storing Results",
]

# Maps a platform "source" (as produced by the crawlers) to its UI stage name.
PLATFORM_STAGE: dict[str, str] = {
    "x": "Crawling X",
    "twitter": "Crawling X",
    "instagram": "Crawling Instagram",
    "tiktok": "Crawling TikTok",
}

_MAX_JOBS = 50  # keep the most recent N jobs in memory
_MAX_LOG_LINES = 2000  # rolling cap on captured backend log lines per job


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class Job:
    """A single crawl run and the live status of each of its stages."""

    def __init__(self, job_id: str, config: dict[str, Any]) -> None:
        self.job_id = job_id
        self.config = config
        self.status = "pending"  # pending | running | completed | failed
        self.error: str | None = None
        self.result: dict[str, Any] | None = None
        self.created_at = _now()
        self.updated_at = self.created_at
        self.stages: list[dict[str, Any]] = [
            {"name": name, "status": "pending", "error": None, "timestamp": None}
            for name in STAGE_SEQUENCE
        ]
        # Raw backend log lines captured during the run (see services.log_stream).
        self.logs: list[dict[str, Any]] = []
        # Partial (un-newline-terminated) text is buffered per OS thread so the
        # parallel crawler subprocesses (run via asyncio.to_thread) don't splice
        # their half-written lines into each other.
        self._log_partials: dict[int, str] = {}
        self._log_lock = threading.Lock()
        self._log_seq = 0

    # ── live log capture ─────────────────────────────────────────────────
    def append_log(self, text: str) -> None:
        """Accumulate raw stdout/stderr text, emitting one entry per full line."""
        tid = threading.get_ident()
        with self._log_lock:
            buf = self._log_partials.get(tid, "") + text
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                self._emit_log(line)
            self._log_partials[tid] = buf

    def _emit_log(self, line: str) -> None:
        line = line.rstrip("\r")
        self._log_seq += 1
        self.logs.append({"seq": self._log_seq, "ts": _now(), "line": line})
        if len(self.logs) > _MAX_LOG_LINES:
            del self.logs[: len(self.logs) - _MAX_LOG_LINES]

    def flush_log(self) -> None:
        """Emit any trailing text not terminated by a newline, all threads."""
        with self._log_lock:
            for buf in self._log_partials.values():
                if buf:
                    self._emit_log(buf)
            self._log_partials.clear()

    # ── stage transitions ────────────────────────────────────────────────
    def _stage(self, name: str) -> dict[str, Any]:
        for stage in self.stages:
            if stage["name"] == name:
                return stage
        stage = {"name": name, "status": "pending", "error": None, "timestamp": None}
        self.stages.append(stage)
        return stage

    def _touch(self) -> None:
        self.updated_at = _now()

    def start_stage(self, name: str) -> None:
        stage = self._stage(name)
        stage["status"] = "running"
        stage["error"] = None
        stage["timestamp"] = _now()
        self._touch()

    def complete_stage(self, name: str) -> None:
        stage = self._stage(name)
        stage["status"] = "completed"
        stage["timestamp"] = _now()
        self._touch()

    def fail_stage(self, name: str, error: Any) -> None:
        stage = self._stage(name)
        stage["status"] = "failed"
        stage["error"] = str(error)
        stage["timestamp"] = _now()
        self._touch()

    def start_platform(self, source: str) -> None:
        name = PLATFORM_STAGE.get(source.lower())
        if name:
            self.start_stage(name)

    def complete_platform(self, source: str) -> None:
        name = PLATFORM_STAGE.get(source.lower())
        if name:
            self.complete_stage(name)

    def fail_platform(self, source: str, error: Any) -> None:
        name = PLATFORM_STAGE.get(source.lower())
        if name:
            self.fail_stage(name, error)

    # ── lifecycle ────────────────────────────────────────────────────────
    def mark_running(self) -> None:
        self.status = "running"
        self._touch()

    def mark_completed(self, result: dict[str, Any] | None = None) -> None:
        self.flush_log()
        self.status = "completed"
        self.result = result
        # Any stage still pending/running at success is rolled up to completed.
        for stage in self.stages:
            if stage["status"] in ("pending", "running"):
                stage["status"] = "completed"
                stage["timestamp"] = stage["timestamp"] or _now()
        self._touch()

    def mark_failed(self, error: Any) -> None:
        self.flush_log()
        self.status = "failed"
        self.error = str(error)
        # Flag the stage that was in flight as the point of failure.
        for stage in self.stages:
            if stage["status"] == "running":
                stage["status"] = "failed"
                stage["error"] = str(error)
                stage["timestamp"] = _now()
        self._touch()

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "error": self.error,
            "result": self.result,
            "config": self.config,
            "stages": self.stages,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


_JOBS: "OrderedDict[str, Job]" = OrderedDict()


def create_job(config: dict[str, Any]) -> Job:
    job = Job(str(uuid.uuid4()), config)
    _JOBS[job.job_id] = job
    while len(_JOBS) > _MAX_JOBS:
        _JOBS.popitem(last=False)
    return job


def get_job(job_id: str) -> Job | None:
    return _JOBS.get(job_id)


def list_jobs() -> list[Job]:
    # newest first
    return list(reversed(_JOBS.values()))
