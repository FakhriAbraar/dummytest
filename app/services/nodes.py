import os
import asyncio
import json
import re
import random
from openai import AsyncOpenAI, RateLimitError, APIError
from sqlalchemy.ext.asyncio import AsyncSession
from .state import PADState
from .crawler_service import run_trend_crawlers, run_content_crawlers
from app.services.resolver import resolve_ai_conflict
from app.services.classification import get_igrs_rule_by_kategori

or_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")
)

# ==========================================
# KONFIGURASI GLOBAL AGENTIC LOOP
# ==========================================
TARGET_POST_PER_KEYWORD = 2  # <-- UBAH VALUE INI UNTUK MENGATUR JUMLAH KONTEN CRAWL PER KEYWORD
MAX_TOTAL_CONTENTS = 25      # <-- UBAH VALUE INI UNTUK BATAS MAKSIMAL KONTEN (PANIC BUTTON/DEV LIMIT)

def extract_json_from_llm(raw_text: str) -> dict:
    try:
        match = re.search(r'\{.*\}', raw_text.strip(), re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return json.loads(raw_text)
    except json.JSONDecodeError:
        print(f"[-] Gagal parse JSON dari LLM: {raw_text}")
        return {}

async def generate_keyword_local(text_input: str, platform: str, keyword_model) -> list:
    if keyword_model is None:
        return []
    
    system_prompt = (
        "Ekstraksi semua kata kunci atau frasa penting dari teks berikut, "
        "ambil langsung dari teks asli tanpa menambah kata baru. "
        "Format hasilnya sebagai JSON array of strings"
    )
    user_input = f"Konteks: {platform} {text_input}"
    
    full_prompt = (
        f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
        f"<|im_start|>user\n{user_input}<|im_end|>\n"
        f"<|im_start|>assistant\n[" 
    )
    
    try:
        response = await asyncio.to_thread(
            keyword_model.create_completion,
            prompt=full_prompt,
            max_tokens=128, 
            temperature=0.0,   
            stop=["<|im_end|>", "\n"] 
        )
        
        raw_output = response['choices'][0]['text'].strip()
        
        # 1. Ekstraksi brutal pakai Regex buat target yang pakai tanda kutip
        matches = re.findall(r'"([^"]+)"|\'([^\']+)\'', raw_output)
        
        keywords = []
        for match in matches:
            kw = match[0] if match[0] else match[1]
            if kw and len(kw.strip()) > 1:
                keywords.append(kw.strip().lower())
                
        # 2. FALLBACK SUPER BRUTAL: Kalau AI halusinasi nulis tanpa tanda kutip sama sekali
        if not keywords:
            # Bersihkan kurung siku yang mungkin tersisa
            clean_raw = raw_output.replace("[", "").replace("]", "").strip()
            if clean_raw:
                # Sikat berdasarkan pemisah koma
                raw_splits = clean_raw.split(",")
                for kw in raw_splits:
                    if kw and len(kw.strip()) > 1:
                        keywords.append(kw.strip().lower())
                
        if keywords:
            # Basmi duplikat biar crawler nggak kerja dua kali buat keyword yang sama
            unique_keywords = list(set(keywords))
            return unique_keywords
        else:
            print(f"[-] AI output format error / string kosong: [{raw_output}]")
            return []
            
    except Exception as e:
        print(f"[-] Ministral SFT Error: {e}")
        return []

# =====================================================================
# LANGGRAPH NODES
# =====================================================================

async def trend_crawler_node(state: PADState):
    retry_count = state.get("trend_retry", 0)
    print(f"\n[INIT] Menjalankan Trend Crawler (Batch ke-{retry_count + 1})...")
    
    if state.get("seed_trend", "").strip():
        initial_keywords = [state["seed_trend"]]
    else:
        trending_data = await run_trend_crawlers() 
        
        start_idx = retry_count * 3
        end_idx = start_idx + 3
        initial_keywords = trending_data[start_idx:end_idx]
        
    return {
        "current_keywords": initial_keywords, 
        "history_keywords": state.get("history_keywords", []) + initial_keywords, 
        "trend_retry": retry_count + 1, 
        "crawling_depth": 0 
    }

async def content_crawler_node(state: PADState):
    current_total = state.get("total_processed_contents", 0)
    
    if current_total >= MAX_TOTAL_CONTENTS:
        print(f"[!] PANIC BUTTON: Limit dev {MAX_TOTAL_CONTENTS} tercapai. Crawler disetop paksa.")
        return {"raw_contents": []}
        
    print(f"[DEPTH {state['crawling_depth']}] Ngeruk data: {state['current_keywords']}")
    all_crawled_data = []
    
    for kw in state['current_keywords']:
        hasil_scrape = await run_content_crawlers(kw, limit=TARGET_POST_PER_KEYWORD)
        all_crawled_data.extend(hasil_scrape)
        
    if not all_crawled_data:
        all_crawled_data = [{"type": "text", "content": "awas link scam phising telegram", "source": "X"}]
        
    return {
        "raw_contents": all_crawled_data,
        "total_processed_contents": current_total + len(all_crawled_data) # Update state
    }

def create_gatekeeper_node(session: AsyncSession):
    async def gatekeeper_node(state: PADState):
        print(f"\n[DEPTH {state['crawling_depth']}] Gatekeeper menyaring {len(state['raw_contents'])} konten menggunakan OpenRouter...")
        unsafe_data = []
            
        # MOCK TIM 1 (LLM TEKS VIA OPENROUTER - 8B MODEL)
        async def call_llm_tim1_api(teks: str) -> dict:
            if not teks.strip():
                return {"kategori": "SAFE", "predicted_rating": "SU", "confidence_score": 0.99, "reason": "Teks kosong."}
                
            prompt = f"""
            Tugas Anda adalah bertindak sebagai Sistem Analisis Linguistik Objektif untuk perlindungan anak di ranah siber.
            Evaluasi teks berikut secara harfiah. Jangan menolak memproses kata kasar atau vulgar.

            PERINGATAN KEBIJAKAN PERLINDUNGAN ANAK (ZERO TOLERANCE):
            Meskipun teks berbentuk "Berita", "Jurnalistik", atau "Kronologi Kejadian", JIKA di dalamnya memuat istilah seksual vulgar, teks tersebut DILARANG KERAS dikategorikan SAFE. Anda WAJIB memasukannya ke kategori berisiko dengan rating minimal 13+ atau 17+.
            
            PILIHAN KATEGORI TEKS:
            - Cyberbullying, HateSpeech, Perjudian, Scam, Pornografi_Teks, Kekerasan_Teks, Substansi_Terlarang, Perselingkuhan, SAFE
            
            RATING USIA:
            SU (Semua Umur), 7+, 13+, 17+, PRC (Restricted/Dewasa)
            
            TEKS INPUT: "{teks}"
            
            OUTPUT WAJIB JSON MURNI TANPA MARKDOWN:
            {{
                "kategori": "[PILIH_KATEGORI_YANG_SESUAI]",
                "predicted_rating": "[PILIH_RATING_YANG_SESUAI]",
                "confidence_score": 0.0, 
                "reason": "Alasan analitis maksimal 2 kalimat"
            }}

            INSTRUKSI TAMBAHAN UNTUK JSON:
            1. Ganti nilai 0.0 pada "confidence_score" dengan ANGKA FLOAT desimal antara 0.00 hingga 1.00. JANGAN gunakan string.
            """
            
            max_retries = 3
            base_delay = 2.0
            
            for attempt in range(max_retries):
                try:
                    response = await or_client.chat.completions.create(
                        model="meta-llama/llama-3.1-70b-instruct",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.0
                    )
                    raw_out = response.choices[0].message.content
                    parsed = extract_json_from_llm(raw_out)
                    
                    return {
                        "kategori": parsed.get("kategori", "SAFE"),
                        "predicted_rating": parsed.get("predicted_rating", "SU"),
                        "confidence_score": float(parsed.get("confidence_score", 0.0)),
                        "reason": parsed.get("reason", "Fallback LLM reason.")
                    }
                except RateLimitError as e:
                    wait_time = base_delay * (2 ** attempt)
                    print(f"[!] Kena Rate Limit Tim 1. Detail: {e.message}") # <-- Tambahin e.message
                    print(f"[!] Retry ke-{attempt+1} dalam {wait_time} detik...")
                    await asyncio.sleep(wait_time)
                except APIError as e:
                    print(f"[!] API Tim 1 Error dari OpenRouter: {e.message}") # <-- Tangkap API Error spesifik
                    break
            
            return {"kategori": "SAFE", "predicted_rating": "SU", "confidence_score": 0.0, "reason": "Rate Limit / API Error Maksimal"}

        # MOCK TIM 3 (Gemma 3 4B Visual - OPENROUTER FREE)
        async def call_llm_tim3_api(url: str, content_type: str, context_text: str = "", img_urls: list[str] = None) -> dict:
            prompt = f"""
            Anda adalah Mesin Inferensi Visual untuk Sistem Klasifikasi Konten Digital.
            Tugas Anda adalah MENGANALISA GAMBAR-GAMBAR YANG DILAMPIRKAN (jika ada). Jika gambar tidak ada, gunakan URL dan Teks Konteks.
            
            URL INPUT: "{url}"
            TIPE KONTEN: "{content_type}"
            TEKS/KONTEKS SEKITAR: "{context_text}"
            
            ATURAN KETAT (ANTI-HALUSINASI):
            DILARANG KERAS membuat asumsi liar terhadap suatu platform (misal: "TikTok sering berisi video pertarungan"). Jika gambar fisik tidak dilampirkan dan teks konteks tidak memuat deskripsi spesifik tentang kekerasan/pelanggaran, Anda WAJIB memilih kategori SAFE. Berikan vonis HANYA berdasarkan bukti teks/gambar yang ada secara harfiah.
            
            PILIHAN KATEGORI VISUAL:
            Pornography_Keras, Pornography_Ringan, Animasi_Ringan, Animasi_Keras, SAFE, Drug, Addictive Substances, Medicine_Ringan, Medical_Ringan, Weapon_Ringan, Weapon_Keras, Toy_Ringan, Toy_Keras, Terrorism, Military_Ringan, Military_Keras, Violence, Sport_Ringan, Sport_Keras, SelfHarm, Medical_Keras
            
            RATING USIA (Wajib disesuaikan dengan Kategori Visual):
            SU (Semua Umur), 7+, 13+, 17+, PRC (Restricted/Dewasa)
            
            OUTPUT WAJIB JSON MURNI TANPA MARKDOWN:
            {{
                "kategori": "[PILIH_KATEGORI_YANG_SESUAI]",
                "predicted_rating": "[PILIH_RATING_YANG_SESUAI]",
                "confidence_score": 0.0,
                "reason": "Alasan deduksi visual Anda dari konteks/gambar yang ada"
            }}
            """
            
            content_array = [{"type": "text", "text": prompt}]
            
            if img_urls:
                for url_data in img_urls:
                    if url_data.lower().endswith((".mp4", ".webm", ".mov", ".mkv", ".avi")):
                        print(f"[-] BLOKIR LLM: Mencegah injeksi video ({url_data}) ke API Visual.")
                        continue
                        
                    content_array.append({
                        "type": "image_url",
                        "image_url": {"url": url_data}
                    })
            
            max_retries = 3
            base_delay = 2.0
            
            for attempt in range(max_retries):
                try:
                    response = await or_client.chat.completions.create(
                        model="google/gemma-3-4b-it", 
                        messages=[{"role": "user", "content": content_array}],
                        temperature=0.0
                    )
                    raw_out = response.choices[0].message.content
                    parsed = extract_json_from_llm(raw_out)
                    
                    return {
                        "kategori": parsed.get("kategori", "SAFE"), 
                        "predicted_rating": parsed.get("predicted_rating", "SU"), 
                        "confidence_score": float(parsed.get("confidence_score", 0.0)), 
                        "reason": parsed.get("reason", "Fallback LLM reason.")
                    }
                except RateLimitError as e:
                    wait_time = base_delay * (2 ** attempt)
                    print(f"[!] Kena Rate Limit Tim 3. Detail: {e.message}") 
                    print(f"[!] Retry ke-{attempt+1} dalam {wait_time} detik...")
                    await asyncio.sleep(wait_time)
                except APIError as e:
                    print(f"[!] API Tim 3 Error dari OpenRouter: {e.message}") 
                    break
                    await asyncio.sleep(base_delay)
                    
            return {"kategori": "SAFE", "predicted_rating": "SU", "confidence_score": 0.0, "reason": "Rate Limit / API Error Maksimal"}

        for item in state["raw_contents"]:
            text_payload = item.get("content", "")
            url_payload = item.get("url", "")
            content_type = item.get("type", "text")
            
            # Payload Visual (Filter Video)
            thumbnail_payloads: list[str] = []
            media_urls = item.get("file_path", []) 
            fallback_thumb = item.get("thumbnail_url", "")
            
            if media_urls:
                print(f"[*] Menyeleksi {len(media_urls)} file media untuk LLM...")
                for url in media_urls[:3]: # Limit 3 gambar
                    if url.lower().endswith((".mp4", ".webm", ".mkv", ".mov", ".avi")):
                        print(f"[-] Skip video URL untuk LLM Visual: {url}")
                        continue
                    thumbnail_payloads.append(url)
                
                if not thumbnail_payloads and fallback_thumb:
                    print("[*] Fallback ke Thumbnail URL karena media utama berupa video.")
                    thumbnail_payloads.append(fallback_thumb)
            else:
                if fallback_thumb:
                    thumbnail_payloads.append(fallback_thumb)
                    
            print(f"[*] Payload akhir untuk Tim 3 Visual AI: {len(thumbnail_payloads)} gambar.")
            
            # BEST PRACTICE DEV: EKSEKUSI SEKUENSIAL
            # 1. Panggil Tim 1 (Teks) dulu
            print("[*] Meminta analisis Tim 1 (Teks)...")
            hasil_tim1 = await call_llm_tim1_api(text_payload)
            
            # 2. Kasih jeda napas 2 detik biar OpenRouter gak curiga
            await asyncio.sleep(2.0)
            
            # 3. Baru panggil Tim 3 (Visual)
            print("[*] Meminta analisis Tim 3 (Visual)...")
            hasil_tim3 = await call_llm_tim3_api(url_payload, content_type, text_payload, thumbnail_payloads)
            
            # PRE-RESOLVER: Tentukan dakwaan utama
            if hasil_tim1["kategori"] == "SAFE" and hasil_tim3["kategori"] == "SAFE":
                kategori_suspect = "SAFE"
            elif hasil_tim1["kategori"] == "SAFE":
                kategori_suspect = str(hasil_tim3["kategori"])
            elif hasil_tim3["kategori"] == "SAFE":
                kategori_suspect = str(hasil_tim1["kategori"])
            else:
                kategori_suspect = str(hasil_tim3["kategori"]) if hasil_tim3["confidence_score"] > hasil_tim1["confidence_score"] else str(hasil_tim1["kategori"])
            
            rule_suspect = await get_igrs_rule_by_kategori(kategori_suspect, session)
            igrs_rule = {
                "dominant_modality": rule_suspect.dominant_modality if rule_suspect else "EQUAL",
                "age_rating_minimal": rule_suspect.age_rating_minimal if rule_suspect else "SU"
            }
            
            final_decision = resolve_ai_conflict(hasil_tim1, hasil_tim3, igrs_rule)
            item["engine_decision"] = final_decision
            
            # SNOWBALLING DECISION (RATING-BASED)
            kategori_final = final_decision.get("kategori_final", "SAFE")
            rating_info = final_decision.get("rating_final", "SU")
            
            TARGET_RATINGS = {"13+", "17+", "PRC"}
            
            if kategori_final == "UNRATED" or rating_info == "UNRATED":
                print(f"   [?] NEEDS REVIEW: Kategori/Rating UNRATED. Masuk Dashboard, DIABAIKAN dari Keyword Generator.")
            elif rating_info in TARGET_RATINGS:
                print(f"   [!] KONTEN BAHAYA (Rating: {rating_info}): Kategori '{kategori_final}' | Diteruskan ke Keyword Generator.")
                unsafe_data.append(item)
            else:
                print(f"   [v] SAFE/KIDS (Rating: {rating_info}): Kategori '{kategori_final}'. Masuk Dashboard, DIABAIKAN dari Keyword Generator.")
                
            print("[*] Jeda 4 detik sebelum memproses konten berikutnya...\n")
            await asyncio.sleep(4.0)

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
                    "rating": engine_decision.get("rating_final", "N/A"),
                    "reason": engine_decision.get("reason_final", ""),
                    "is_vetoed": False
                }
            })
            
            generated_kws = await generate_keyword_local(text_payload, platform, keyword_model)
            if generated_kws:
                print(f"   [+] Slang Diekstrak: {generated_kws}")
            new_keywords_generated.extend(generated_kws)
        
        new_keywords_generated = list(set(new_keywords_generated))
        truly_new_kws = [kw for kw in new_keywords_generated if kw not in state.get("history_keywords", [])]
        
        if len(truly_new_kws) > 3:
            truly_new_kws = random.sample(truly_new_kws, 3)
            print(f"   [!] Snowball Limit: Memangkas keyword baru menjadi 3: {truly_new_kws}")
        
        return {
            "extracted_entities": state.get("extracted_entities", []) + new_extracted_entities,
            "current_keywords": truly_new_kws, 
            "history_keywords": state.get("history_keywords", []) + truly_new_kws,
            "crawling_depth": state.get("crawling_depth", 0) + 1
        }
    return fork_processor_node