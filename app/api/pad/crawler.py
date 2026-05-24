from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
from app.services.graph import build_pad_workflow
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.db.sql import get_db_session 

router = APIRouter(prefix="/crawler", tags=["Agentic Crawler"])

class TriggerRequest(BaseModel):
    seed_trend: str
    max_depth: int = 3  

@router.post("/trigger")
async def trigger_agentic_crawler(
    request: TriggerRequest, 
    fastapi_req: Request,
    session: AsyncSession = Depends(get_db_session)
):
    mission_id = str(uuid.uuid4())
    print(f"\n=== MEMULAI MISI CRAWLING [{mission_id}]: {request.seed_trend} ===")
    
    initial_state = {
        "seed_trend": request.seed_trend,
        "current_keywords": [],
        "history_keywords": [],
        "raw_contents": [],
        "unsafe_contents": [],
        "extracted_entities": [],
        "total_processed_contents": 0,
        "crawling_depth": 0,
        "max_depth": request.max_depth
    }
    
    keyword_model = getattr(fastapi_req.app.state, "keyword_model", None)
    
    workflow = build_pad_workflow(keyword_model, session)
    
    try:
        async with AsyncSqliteSaver.from_conn_string("pad_checkpoint.db") as checkpointer:
            app = workflow.compile(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": mission_id}}
            
            final_state = await app.ainvoke(initial_state, config=config)
            
            return {
                "status": "success",
                "message": "Operasi selesai.",
                "mission_id": mission_id,
                "total_putaran": final_state["crawling_depth"],
                "total_bukti_dikumpulkan": len(final_state["extracted_entities"]),
                "data_pelanggaran": final_state["extracted_entities"]
            }

    except Exception as e:
        print(f"[-] ERROR FATAL PADA PIPELINE: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))