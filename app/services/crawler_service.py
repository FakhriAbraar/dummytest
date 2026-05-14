import asyncio

async def run_trend_crawlers() -> list: 
    print("[*] [MOCK] Menjalankan Google Trends...")
    await asyncio.sleep(1.5)
    return ["kasus doxxing telegram"]

async def run_content_crawlers(keyword: str, limit: int = 5) -> list:
    print(f"[*] [MOCK] Mengerahkan crawler sosmed untuk keyword: '{keyword}'...")
    await asyncio.sleep(1.5)
    unified_data = []
    kw_lower = keyword.lower()
    
    # --- SKENARIO DEPTH 0 (Umpan Awal) ---
    if "kasus doxxing telegram" in kw_lower:
        unified_data = [
            {"type": "text", "content": "Viral banget kasus doxxing telegram, gila netizen berani banget spill KTP dan alamat korban.", "source": "X", "url": "https://x.com/fake1"},
            {"type": "video_desc", "content": "Bagi dong link video skandal telegram yang lagi viral, penasaran nih. pm ya.", "source": "TikTok", "url": "https://tiktok.com/fake2"},
            {"type": "text", "content": "Info cuaca hari ini cerah banget, enak buat ngopi di rumah.", "source": "IG", "url": "https://ig.com/fake3"} # Sengaja dikasih SAFE
        ]
        
    elif "spill ktp" in kw_lower or "alamat" in kw_lower:
        unified_data = [
            {"type": "text", "content": "Tolong report akun ini, dia main ancam sebar KK dan nomor HP di grup.", "source": "X", "url": "https://x.com/fake4"},
            {"type": "text", "content": "KTP ku ilang di jalan kemarin, ada yang nemu ga ya?", "source": "Facebook", "url": "https://fb.com/fake5"} # SAFE context
        ]
    elif "video skandal" in kw_lower or "link" in kw_lower:
        unified_data = [
            {"type": "video", "content": "Full video asusila tanpa sensor, join grup VIP sekarang.", "source": "Telegram", "url": "https://t.me/fake6"}
        ]
        
    elif "sebar kk" in kw_lower or "vip" in kw_lower or "asusila" in kw_lower:
        unified_data = [
            {"type": "text", "content": "Open BO judi slot gacor, klik link di bio.", "source": "X", "url": "https://x.com/fake7"}
        ]
        
    else:
        unified_data = [
            {"type": "text", "content": f"Lagi rame pada ngomongin {keyword} ya?", "source": "X", "url": "https://x.com/fake8"}
        ]
        
    print(f"[+] [MOCK] Crawler mendapatkan {len(unified_data)} konten untuk '{keyword}'.")
    return unified_data[:limit]