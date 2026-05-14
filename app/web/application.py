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
    # === Buat Testing API Local === by Algof
    # from fastapi.middleware.cors import CORSMiddleware
    # app.add_middleware(
    #     CORSMiddleware,
    #     allow_origins=[
    #         "http://127.0.0.1:5500",
    #         "http://localhost:5500",
    #     ],
    #     allow_credentials=True,
    #     allow_methods=["*"],
    #     allow_headers=["*"],
    # )
    # === Buat Testing API Local ===

    app.include_router(router=api_router, prefix="/api")

    return app
