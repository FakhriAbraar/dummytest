import time
from .state import PADState

def check_loop_status(state: PADState) -> str:
    start_time = time.perf_counter()
    
    MAX_TREND_RETRIES = 3
    max_depth = state.get("max_depth", 1)
    
    if state["crawling_depth"] >= max_depth:
        decision = "end"
        print("--- Ngecek Status Rem ---")
        print(f"[STOP] Max depth limit ({max_depth}) tercapai.")

    elif not state.get("current_keywords"):
        current_retry = state.get("trend_retry", 1)
        
        if current_retry <= MAX_TREND_RETRIES:
            decision = "retry_trend"
            print("--- Ngecek Status Rem ---")
            print(f"[RETRY] Batch {current_retry} kosong. Mundur ambil Batch {current_retry + 1}.")
        else:
            decision = "end"
            print("--- Ngecek Status Rem ---")
            print("[STOP] Tambang mutlak kering atau batas retry habis. Mesin dimatikan.")
    else:
        decision = "continue"
        print("--- Ngecek Status Rem ---")
        print(f"[LANJUT] Menemukan {len(state['current_keywords'])} keyword baru. Putar balik ke Crawler!")
    
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    print(f"⏱️ [METRICS] Deterministic Router Response Time: {elapsed_ms:.4f} ms")
    
    return decision