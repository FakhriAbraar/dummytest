import time
from .state import PADState

def check_loop_status(state: PADState) -> str:
    start_time = time.perf_counter()
    
    if state["crawling_depth"] >= state["max_depth"]:
        decision = "end"
        print("--- Ngecek Status Rem ---")
        print(f"[STOP] Max depth limit reached.")
    elif not state["current_keywords"]:
        decision = "end"
        print("--- Ngecek Status Rem ---")
        print(f"[STOP] Tambang kering. Nggak ada konten unsafe.")
    else:
        decision = "continue"
        print("--- Ngecek Status Rem ---")
        print(f"[LANJUT] Menemukan keyword baru. Putar balik ke Crawler!")
    
    end_time = time.perf_counter()
    elapsed_ms = (end_time - start_time) * 1000 # Convert ke Millisecond
    
    print(f"⏱️ [METRICS] Deterministic Router Response Time: {elapsed_ms:.4f} ms")
    
    return decision