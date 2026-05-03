from fastapi.routing import APIRouter

from app.web.api import monitoring
from app.web.api import classification

api_router = APIRouter()
api_router.include_router(monitoring.router)
api_router.include_router(classification.router)
