from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.check_engine import run_public_checking_pipeline

from app.db.sql import get_db_session 

router = APIRouter()

class CheckRequest(BaseModel):
    url: str

class EngineDecision(BaseModel):
    kategori_final: str
    rating_final: str
    reason_ai: str
    is_vetoed_by_backend: bool

class LegalContext(BaseModel):
    bunyi_pasal_qdrant: str

class CheckResponse(BaseModel):
    target_url: str
    status: str
    engine_decision: EngineDecision
    legal_context: LegalContext

@router.post("/verify", response_model=CheckResponse)
async def public_checking_endpoint(
    request: CheckRequest, 
    session: AsyncSession = Depends(get_db_session)
):
    try:
        result = await run_public_checking_pipeline(request.url, session)
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))