"""Per-job backend log capture for the live Pipeline Monitoring console.

The agentic pipeline narrates its progress with plain ``print()`` calls spread
across many modules (nodes, crawler_service, resolver, …). To stream those raw
logs to the frontend *without* rewriting every print, we tee ``sys.stdout`` /
``sys.stderr``: every write still goes to the real console, and — if the current
asyncio task has a crawl job bound via the :data:`current_job` context variable —
the same text is appended to that job's in-memory log buffer.

Because :class:`contextvars.ContextVar` is copied into child tasks (``asyncio``
gather) and worker threads (``asyncio.to_thread``), a single ``current_job.set``
at the top of ``run_crawl_job`` routes the entire pipeline's output — including
subprocess crawler logs printed from threads — into the right job. Requests and
background work with no job bound (``current_job`` is ``None``) only hit the real
console, so job buffers never get polluted by unrelated output.
"""

from __future__ import annotations

import contextlib
import contextvars
import sys
from typing import TYPE_CHECKING, Any, TextIO

if TYPE_CHECKING:
    from app.services.job_tracker import Job

# Bound by run_crawl_job; read by the tee at write-time to find the active buffer.
current_job: contextvars.ContextVar[Job | None] = contextvars.ContextVar(
    "current_crawl_job", default=None
)


class _TeeStream:
    """File-like proxy that mirrors writes to the real stream and the active job."""

    def __init__(self, real: TextIO) -> None:
        self._real = real

    def write(self, s: str) -> int:
        try:
            n = self._real.write(s)
        except UnicodeEncodeError:
            # Real console can't encode some chars (e.g. emoji on a Windows
            # cp1252 stdout). Degrade to a replaced rendering instead of letting
            # a stray emoji in a print() crash the whole pipeline. The job buffer
            # below still receives the original text (streamed to the UI as UTF-8).
            enc = getattr(self._real, "encoding", None) or "utf-8"
            n = self._real.write(s.encode(enc, "replace").decode(enc, "replace"))
        if s:
            job = current_job.get()
            if job is not None:
                # never let logging break the pipeline
                with contextlib.suppress(Exception):
                    job.append_log(s)
        return n

    def flush(self) -> None:
        self._real.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


def install_log_tee() -> None:
    """Wrap stdout/stderr once. Idempotent so uvicorn ``--reload`` won't re-stack."""
    if not isinstance(sys.stdout, _TeeStream):
        sys.stdout = _TeeStream(sys.stdout)
    if not isinstance(sys.stderr, _TeeStream):
        sys.stderr = _TeeStream(sys.stderr)
