from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

try:
    from llama_cpp import Llama as _Llama
    _LLAMA_AVAILABLE = True
except ImportError:
    _Llama = None  # type: ignore[assignment]
    _LLAMA_AVAILABLE = False

from app.db import tables as _tables  # noqa: F401  (register models on Base.metadata)
from app.db.mongo import connect_mongo, disconnect_mongo
from app.db.sql import Base, connect_postgres, disconnect_postgres, get_engine
from app.db.vector import connect_qdrant, disconnect_qdrant
from app.db.minio import connect_minio, disconnect_minio
from app.services import scheduler
from app.services.log_stream import install_log_tee

@asynccontextmanager
async def lifespan_setup(
    app: FastAPI,
) -> AsyncGenerator[None]:  # pragma: no cover
    # Mirror pipeline stdout/stderr into per-job buffers for the live log console.
    install_log_tee()

    await connect_postgres()
    await connect_mongo()
    # await connect_qdrant() # hapus? - algof
    await connect_minio()

    # Ensure the public_check history table exists (POC: created on the fly so
    # no extra Alembic step is needed). create_all is idempotent — every
    # Alembic-managed table already exists and is skipped, only the new one is
    # created.
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Migrasi ringan & idempoten: tambahkan kolom jadwal baru ke tabel lama
        # (create_all tidak meng-ALTER tabel yang sudah ada). Aman dijalankan
        # berulang — ADD COLUMN IF NOT EXISTS.
        from sqlalchemy import text

        await conn.execute(
            text(
                """
                ALTER TABLE crawler_schedule
                    ADD COLUMN IF NOT EXISTS times JSONB,
                    ADD COLUMN IF NOT EXISTS monthly_mode VARCHAR(10) NOT NULL DEFAULT 'specific',
                    ADD COLUMN IF NOT EXISTS days_of_month JSONB,
                    ADD COLUMN IF NOT EXISTS day_range_start INTEGER NOT NULL DEFAULT 1,
                    ADD COLUMN IF NOT EXISTS day_range_end INTEGER NOT NULL DEFAULT 28
                """
            )
        )

    # Pastikan akun admin default ada & bisa login (auth halaman admin).
    from app.services.auth import ensure_default_admin

    await ensure_default_admin()

    BASE_DIR = Path(__file__).resolve().parent.parent.parent
    KEYWORD_MODEL_PATH = BASE_DIR / "app" / "models" / "keyword_generator" / "ministral-3b-base-f16.gguf"

    print(f"[*] Mengecek Model Keyword di: {KEYWORD_MODEL_PATH}")

    if not KEYWORD_MODEL_PATH.exists():
        print("[-] WARNING: File GGUF tidak ditemukan! Sistem akan menggunakan mock data.")
        app.state.keyword_model = None
    elif not _LLAMA_AVAILABLE or _Llama is None:
        print("[-] WARNING: llama-cpp-python tidak tersedia. Sistem akan menggunakan mock data.")
        app.state.keyword_model = None
    else:
        print("[*] Memuat model GGUF ke RAM...")
        app.state.keyword_model = _Llama(
            model_path=str(KEYWORD_MODEL_PATH),
            n_gpu_layers=-1,
            n_ctx=2048,
            verbose=False,
        )

    # Start the auto-crawler scheduler. Reads the CrawlerSchedule config row and
    # registers the recurring crawl job if auto-crawling is enabled.
    scheduler.set_keyword_model(app.state.keyword_model)
    await scheduler.start_scheduler()

    app.middleware_stack = None
    app.middleware_stack = app.build_middleware_stack()

    yield

    scheduler.shutdown_scheduler()
    await disconnect_mongo()
    await disconnect_postgres()
    await disconnect_minio()
    await disconnect_qdrant()
