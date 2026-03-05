from fastapi import FastAPI

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

    app.include_router(router=api_router, prefix="/api")

    return app
