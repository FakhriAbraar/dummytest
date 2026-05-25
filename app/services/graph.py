from langgraph.graph import StateGraph, END
from .state import PADState
from .nodes import trend_crawler_node, content_crawler_node, create_gatekeeper_node, create_fork_processor_node
from .router import check_loop_status  

def build_pad_workflow(keyword_model, session):
    workflow = StateGraph(PADState)
    
    workflow.add_node("TrendSeed", trend_crawler_node)
    workflow.add_node("ContentCrawler", content_crawler_node)
    
    workflow.add_node("Gatekeeper", create_gatekeeper_node(session))
    workflow.add_node("ForkProcessor", create_fork_processor_node(keyword_model))
    
    workflow.set_entry_point("TrendSeed")
    workflow.add_edge("TrendSeed", "ContentCrawler")
    workflow.add_edge("ContentCrawler", "Gatekeeper")
    workflow.add_edge("Gatekeeper", "ForkProcessor")
    
    workflow.add_conditional_edges(
        "ForkProcessor",
        check_loop_status,
        {
            "continue": "ContentCrawler",
            "retry_trend": "TrendSeed", 
            "end": END                    
        }
    )
    
    return workflow


# async def llm_agentic_router(state: PADState) -> str:
#     print("\n[AGENTIC ROUTER] Memanggil OpenRouter LLM untuk evaluasi state...")

#     start_time = time.perf_counter()
    
#     client = AsyncOpenAI(
#         base_url="https://openrouter.ai/api/v1",
#         api_key=os.getenv("OPENROUTER_API_KEY")
#     )
    
#     prompt = f"""Kamu adalah AI Orchestrator untuk sistem crawling cybercrime.
#     Status sistem saat ini:
#     - Kedalaman (Depth) saat ini: {state['crawling_depth']}
#     - Batas Maksimal Kedalaman (Max Depth): {state['max_depth']}
#     - Keyword baru yang ditemukan di putaran ini: {state['current_keywords']}
    
#     Tugasmu: Tentukan apakah sistem harus lanjut mengeruk ('continue') atau berhenti ('end').
#     Aturan logika sistem:
#     1. Jika Depth saat ini sudah sama dengan atau lebih dari Max Depth, JAWAB 'end'.
#     2. Jika tidak ada keyword baru (current_keywords kosong), JAWAB 'end'.
#     3. Jika masih ada keyword baru dan belum menyentuh batas kedalaman, JAWAB 'continue'.
    
#     Jawab HANYA dengan satu kata ('continue' atau 'end') tanpa tanda baca apapun.
#     """
    
#     try:
#         response = await client.chat.completions.create(
#             model="openai/gpt-4.1-mini",
#             messages=[{"role": "user", "content": prompt}],
#             temperature=0.0, 
#             max_tokens=20
#         )
#         decision = response.choices[0].message.content.strip().lower()
        
#         end_time = time.perf_counter() # Matikan Stopwatch
#         elapsed_ms = (end_time - start_time) * 1000 # Convert ke Millisecond
#         elapsed_sec = (end_time - start_time)
        
#         print(f"[AGENTIC ROUTER] Keputusan LLM: '{decision}'")
#         print(f"⏱️ [METRICS] Agentic LLM Router Response Time: {elapsed_ms:.2f} ms ({elapsed_sec:.2f} detik)")
        
#         if "continue" in decision:
#             return "continue"
#         else:
#             return "end"
            
#     except Exception as e:
#         end_time = time.perf_counter()
#         elapsed_sec = (end_time - start_time)
#         print(f"[!] OpenRouter API Error: {e}")
#         print(f"⏱️ [METRICS] Agentic LLM FAILED Time: {elapsed_sec:.2f} detik")
#         return "end" 


# def build_pad_workflow(keyword_model, session):
#     workflow = StateGraph(PADState)
    
#     workflow.add_node("TrendSeed", trend_crawler_node)
#     workflow.add_node("ContentCrawler", content_crawler_node)
#     workflow.add_node("Gatekeeper", create_gatekeeper_node(session))
#     workflow.add_node("ForkProcessor", create_fork_processor_node(keyword_model))
    
#     workflow.set_entry_point("TrendSeed")
#     workflow.add_edge("TrendSeed", "ContentCrawler")
#     workflow.add_edge("ContentCrawler", "Gatekeeper")
#     workflow.add_edge("Gatekeeper", "ForkProcessor")
    
#     workflow.add_conditional_edges(
#         "ForkProcessor",
#         llm_agentic_router,
#         {
#             "continue": "ContentCrawler",
#             "end": END                    
#         }
#     )
    
#     return workflow