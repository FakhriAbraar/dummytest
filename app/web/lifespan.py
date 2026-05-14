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

from app.db.mongo import connect_mongo, disconnect_mongo
from app.db.sql import connect_postgres, disconnect_postgres
from app.db.vector import connect_qdrant, disconnect_qdrant
from app.db.minio import connect_minio, disconnect_minio

@asynccontextmanager
async def lifespan_setup(
    app: FastAPI,
) -> AsyncGenerator[None]:  # pragma: no cover
    await connect_postgres()
    await connect_mongo()
    # await connect_qdrant() # hapus? - algof
    await connect_minio()

    BASE_DIR = Path(__file__).resolve().parent.parent.parent
    KEYWORD_MODEL_PATH = BASE_DIR / "models" / "keyword_generator" / "ministral-3b-base-f16.gguf"

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

    app.middleware_stack = None
    app.middleware_stack = app.build_middleware_stack()

    yield

    await disconnect_mongo()
    await disconnect_postgres()
    await disconnect_minio()
    await disconnect_qdrant()
