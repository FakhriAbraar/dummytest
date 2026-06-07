from typing import TypedDict, List, Dict, Any

class PADState(TypedDict):
    seed_trend: str
    custom_keywords: List[str]        # Keyword tambahan dari form Crawl Config
    platform_limits: Dict[str, int]   # Max konten per platform (x/instagram/tiktok)
    trends_keyword_count: int         # Jumlah keyword yang diambil dari trends per batch
    current_keywords: List[str]
    history_keywords: List[str]  # Buat ngecek jenuh/convergence
    trend_retry: int
    
    raw_contents: List[Dict[str, Any]]     # Hasil kerukan mentah
    unsafe_contents: List[Dict[str, Any]]  # Hasil filter Model Tim 1/3
    all_processed_contents: List[Dict[str, Any]]  # SEMUA konten setelah gatekeeper (safe + unsafe) untuk disimpan ke DB

    extracted_entities: List[Dict[str, Any]] # Data siap masuk PostgreSQL
    
    total_processed_contents: int  # Akumulasi konten yang sudah diproses (panic button)
    crawling_depth: int
    max_depth: int  # Rem darurat fisik