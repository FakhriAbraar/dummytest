from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.pad import check, crawler, schedule, stats
from app.web.api.router import api_router
from app.web.lifespan import lifespan_setup


def get_app() -> FastAPI:
    app = FastAPI(
        title="pad",
        lifespan=lifespan_setup,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router=api_router, prefix="/api")
    app.include_router(crawler.router, prefix="/api/pad")
    app.include_router(stats.router, prefix="/api/pad")
    app.include_router(schedule.router, prefix="/api/pad")
    app.include_router(check.router, prefix="/api/pad/check", tags=["Public Checking"])

    return app
