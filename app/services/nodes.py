import os
import asyncio
import json
from sqlalchemy.ext.asyncio import AsyncSession
from .state import PADState
from .crawler_service import run_trend_crawlers, run_content_crawlers
from app.services.resolver import resolve_ai_conflict
from app.services.classification import get_igrs_rule_by_kategori

# THE FIX: Gunakan format prompt yang SAMA PERSIS dengan dataset fine-tuning lu
async def generate_keyword_local(text_input: str, platform: str, keyword_model) -> list:
    if keyword_model is None:
        return []
    
    # Replikasi format JSONL dataset lu ke dalam string mentah
    prompt = (
        f"instruction: Ekstraksi semua kata kunci atau frasa penting dari teks berikut, "
        f"ambil langsung dari teks asli tanpa menambah kata baru. Kembalikan dalam format JSON array.\n"
        f"input: Konteks: {platform} {text_input}\n"
        f"output: "
    )
    
    try:
        # Karena ini model BASE, gunakan create_completion
        response = await asyncio.to_thread(
            keyword_model.create_completion,
            prompt=prompt,
            max_tokens=64,
            temperature=0.1,
            # Kita paksa berhenti kalau dia sudah menutup array atau bikin baris baru
            stop=["\n", "instruction:"] 
        )
        
        raw_output = response['choices'][0]['text'].strip()
        
        # Karena output model lu adalah JSON array (misal: ["a", "b"]), kita parse pakai json.loads
        try:
            keywords = json.loads(raw_output)
            if isinstance(keywords, list):
                return [str(kw).lower() for kw in keywords]
        except json.JSONDecodeError:
            # Fallback jika AI gagal ngasih JSON valid, coba pembersihan manual sederhana
            print(f"[-] AI output bukan JSON valid: {raw_output}")
            clean_text = raw_output.replace("[", "").replace("]", "").replace('"', "")
            return [k.strip().lower() for k in clean_text.split(",") if k.strip()]
            
        return []
        
    except Exception as e:
        print(f"[-] Ministral Base Error: {e}")
        return []

# =====================================================================
# LANGGRAPH NODES
# =====================================================================

async def trend_crawler_node(state: PADState):
    print(f"\n[DEPTH {state['crawling_depth']}] Menjalankan Trend Crawler...")
    if state["seed_trend"].strip():
        initial_keywords = [state["seed_trend"]]
    else:
        trending_data = await run_trend_crawlers() 
        initial_keywords = trending_data[:3]
    return {"current_keywords": initial_keywords, "history_keywords": initial_keywords}

async def content_crawler_node(state: PADState):
    print(f"[DEPTH {state['crawling_depth']}] Ngeruk data: {state['current_keywords']}")
    all_crawled_data = []
    for kw in state['current_keywords']:
        hasil_scrape = await run_content_crawlers(kw, limit=5)
        all_crawled_data.extend(hasil_scrape)
    if not all_crawled_data:
        all_crawled_data = [{"type": "text", "content": "awas link scam phising telegram", "source": "X"}]
    return {"raw_contents": all_crawled_data}

def create_gatekeeper_node(session: AsyncSession):
    async def gatekeeper_node(state: PADState):
        print(f"\n[DEPTH {state['crawling_depth']}] Gatekeeper menyaring {len(state['raw_contents'])} konten...")
        unsafe_data = []
        
        # (Mock Tim 1 & Tim 3 lu tetep sama kayak sebelumnya)
        async def mock_tim1_api(teks):
            await asyncio.sleep(0.3) 
            t = teks.lower()
            if "ktp" in t or "alamat" in t or "kk" in t or "nomor hp" in t:
                # Context check sederhana biar "KTP ilang" tetap dibilang SAFE
                if "ilang" in t or "nemu" in t:
                    return {"kategori": "SAFE", "predicted_rating": "SU", "confidence_score": 0.90, "reason": "Bukan doxxing, kehilangan KTP biasa."}
                return {"kategori": "Cyberbullying", "predicted_rating": "18+", "confidence_score": 0.95, "reason": "Indikasi penyebaran data pribadi (Doxxing)."}
            if "judi" in t or "slot" in t:
                return {"kategori": "Perjudian", "predicted_rating": "PRC", "confidence_score": 0.99, "reason": "Promosi perjudian online."}
            return {"kategori": "SAFE", "predicted_rating": "SU", "confidence_score": 0.95, "reason": "Teks aman."}

        async def mock_tim3_api(url, content_type):
            await asyncio.sleep(0.4) 
            if content_type in ["video", "video_desc"] or "t.me" in url.lower():
                return {"kategori": "Pornography_Keras", "predicted_rating": "17+", "confidence_score": 0.92, "reason": "Indikasi distribusi konten asusila."}
            return {"kategori": "SAFE", "predicted_rating": "SU", "confidence_score": 0.99, "reason": "Visual aman."}

        for item in state["raw_contents"]:
            text_payload = item.get("content", "")
            url_payload = item.get("url", "")
            content_type = item.get("type", "text")
            
            hasil_tim1, hasil_tim3 = await asyncio.gather(
                mock_tim1_api(text_payload),
                mock_tim3_api(url_payload, content_type)
            )
            
            # PRE-RESOLVER: Tentukan dakwaan utama
            if hasil_tim1["kategori"] == "SAFE" and hasil_tim3["kategori"] == "SAFE":
                kategori_suspect = "SAFE"
            elif hasil_tim1["kategori"] == "SAFE":
                kategori_suspect = hasil_tim3["kategori"]
            elif hasil_tim3["kategori"] == "SAFE":
                kategori_suspect = hasil_tim1["kategori"]
            else:
                kategori_suspect = hasil_tim3["kategori"] if hasil_tim3["confidence_score"] > hasil_tim1["confidence_score"] else hasil_tim1["kategori"]
            
            rule_suspect = await get_igrs_rule_by_kategori(kategori_suspect, session)
            igrs_rule = {
                "dominant_modality": rule_suspect.dominant_modality if rule_suspect else "EQUAL",
                "age_rating_minimal": rule_suspect.age_rating_minimal if rule_suspect else "SU"
            }
            
            final_decision = resolve_ai_conflict(hasil_tim1, hasil_tim3, igrs_rule)
            item["engine_decision"] = final_decision
            
            # ==========================================
            # SNOWBALLING DECISION (SMART FILTERING)
            # ==========================================
            rating = final_decision["rating_final"]
            
            if rating in ["13+", "17+", "18+", "PRC"]:
                print(f"   [!] KONTEN BAHAYA: {final_decision['kategori_final']} ({rating}) | Diteruskan ke LLM Keyword Generator.")
                unsafe_data.append(item)
                
            elif rating == "UNRATED":
                print(f"   [?] NEEDS REVIEW: AI Ragu. Masuk Dashboard, tapi DIABAIKAN dari Keyword Generator.")
                
            else:
                print(f"   [v] SAFE: Rating AI '{rating}'. Masuk Dashboard, DIABAIKAN dari Keyword Generator.")

        print(f"\n[DEPTH {state['crawling_depth']}] HASIL GATEKEEPER: {len(unsafe_data)} konten beracun siap diekstrak LLM.")
        return {"unsafe_contents": unsafe_data}
    return gatekeeper_node

def create_fork_processor_node(keyword_model):
    async def fork_processor_node(state: PADState):
        print(f"[DEPTH {state['crawling_depth']}] Memproses Forking dengan Ministral Base...")
        new_extracted_entities = []
        new_keywords_generated = []
        
        for item in state["unsafe_contents"]:
            text_payload = item.get("content", "")
            platform = item.get("source", "Umum")
            engine_decision = item.get("engine_decision", {})
            
            new_extracted_entities.append({
                "platform": platform,
                "url": item.get("url", ""),
                "content_type": item.get("type", "text"),
                "bukti_teks": text_payload,
                "vonis_hukum": {
                    "kategori": engine_decision.get("kategori_final", "Unknown"),
                    "rating": engine_decision.get("rating_final", "Unknown"),
                    "reason": engine_decision.get("reason_final", ""),
                    "is_vetoed": False
                }
            })
            
            # Panggil ekstraksi keyword dengan model Ministral Base lu
            generated_kws = await generate_keyword_local(text_payload, platform, keyword_model)
            if generated_kws:
                print(f"   [+] Slang Diekstrak: {generated_kws}")
            new_keywords_generated.extend(generated_kws)
        
        new_keywords_generated = list(set(new_keywords_generated))
        truly_new_kws = [kw for kw in new_keywords_generated if kw not in state["history_keywords"]]
        
        return {
            "extracted_entities": state["extracted_entities"] + new_extracted_entities,
            "current_keywords": truly_new_kws, 
            "history_keywords": state["history_keywords"] + truly_new_kws,
            "crawling_depth": state["crawling_depth"] + 1
        }
    return fork_processor_node