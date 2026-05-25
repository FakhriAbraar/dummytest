from __future__ import annotations

import sys

import uvicorn

from app.settings import settings


def main() -> None:
    # Force UTF-8 stdout/stderr on Windows so subprocess output dengan unicode tidak crash print()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    uvicorn.run(
        "app.web.application:get_app",
        workers=settings.workers_count,
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level=settings.log_level.value.lower(),
        factory=True,
    )


if __name__ == "__main__":
    main()