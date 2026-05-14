from typing import TypedDict, List, Dict, Any

class PADState(TypedDict):
    seed_trend: str
    current_keywords: List[str]
    history_keywords: List[str]  # Buat ngecek jenuh/convergence
    
    raw_contents: List[Dict[str, Any]]     # Hasil kerukan mentah
    unsafe_contents: List[Dict[str, Any]]  # Hasil filter Model Tim 1/3
    
    extracted_entities: List[Dict[str, Any]] # Data siap masuk PostgreSQL
    
    crawling_depth: int
    max_depth: int  # Rem darurat fisik