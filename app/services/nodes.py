import asyncio
import json
import os
import re
import random
from openai import AsyncOpenAI, RateLimitError, APIError
from sqlalchemy.ext.asyncio import AsyncSession
from .state import PADState
from .crawler_service import run_trend_crawlers, run_content_crawlers
from app.services.resolver import resolve_ai_conflict
from app.services.classification import get_igrs_rule_by_kategori
from app.services.video_extractor import process_media_url, VIDEO_EXTENSIONS

or_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")
)

TARGET_POST_PER_KEYWORD = 2
MAX_TOTAL_CONTENTS = 25


def extract_json_from_llm(raw_text: str | None) -> dict:
    if not raw_text:
        return {}
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
        # Dummy keyword extraction — ambil kata bermakna dari teks saat GGUF tidak ada
        words = re.findall(r'\b\w{4,}\b', text_input.lower())
        unique_words = list({w for w in words if w not in {
            "yang", "dengan", "untuk", "dari", "pada", "atau", "adalah", "akan",
            "tidak", "bisa", "agar", "juga", "sudah", "dalam", "karena",
            "lebih", "seperti", "harus", "masih", "bahwa", "serta",
            "oleh", "semua", "setiap", "belum", "bagi", "setelah", "tentang",
        }})
        result = random.sample(unique_words, k=min(3, len(unique_words)))
        if result:
            print(f"   [+] Keyword dummy diekstrak dari teks: {result}")
        return result

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
            stop=["<|im_end|>", "\n"],
        )

        raw_output = response["choices"][0]["text"].strip()
        matches = re.findall(r'"([^"]+)"|\'([^\']+)\'', raw_output)

        keywords = []
        for match in matches:
            kw = match[0] if match[0] else match[1]
            if kw and len(kw.strip()) > 1:
                keywords.append(kw.strip().lower())

        if not keywords:
            clean_raw = raw_output.replace("[", "").replace("]", "").strip()
            if clean_raw:
                for kw in clean_raw.split(","):
                    if kw and len(kw.strip()) > 1:
                        keywords.append(kw.strip().lower())

        return list(set(keywords)) if keywords else []

    except Exception as e:
        print(f"[-] Keyword model error: {e}")
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
        initial_keywords = trending_data[start_idx : start_idx + 3]

    return {
        "current_keywords": initial_keywords,
        "history_keywords": state.get("history_keywords", []) + initial_keywords,
        "trend_retry": retry_count + 1,
        "crawling_depth": 0,
    }


async def content_crawler_node(state: PADState):
    current_total = state.get("total_processed_contents", 0)

    if current_total >= MAX_TOTAL_CONTENTS:
        print(f"[!] Limit {MAX_TOTAL_CONTENTS} konten tercapai. Crawler disetop.")
        return {"raw_contents": []}

    print(f"[DEPTH {state['crawling_depth']}] Ngeruk data: {state['current_keywords']}")
    all_crawled_data = []

    for kw in state["current_keywords"]:
        hasil_scrape = await run_content_crawlers(kw, limit=TARGET_POST_PER_KEYWORD)
        all_crawled_data.extend(hasil_scrape)

    # Safety net: kalau crawler benar-benar mati, inject satu konten dummy
    if not all_crawled_data:
        print("[!] Content crawler kosong total. Inject 1 dummy konten untuk menjaga alur graph.")
        all_crawled_data = [{
            "type": "text",
            "content": "awas link scam phising telegram",
            "source": "dummy",
            "url": "",
            "username": "",
            "file_path": [],
            "thumbnail_url": "",
        }]

    return {
        "raw_contents": all_crawled_data,
        "total_processed_contents": current_total + len(all_crawled_data),
    }


def create_gatekeeper_node(session: AsyncSession):
    async def gatekeeper_node(state: PADState):
        print(f"\n[DEPTH {state['crawling_depth']}] Gatekeeper menyaring {len(state['raw_contents'])} konten menggunakan OpenRouter...")
        unsafe_data = []
        all_classified = []

        # TIM 1 — Analisis Teks (dengan retry + rate limit handling)
        async def call_llm_tim1_api(teks: str) -> dict:
            prompt = f"""
            Tugas Anda adalah bertindak sebagai Sistem Analisis Linguistik Objektif untuk perlindungan anak di ranah siber.
            Evaluasi teks berikut secara harfiah. Jangan menolak memproses kata kasar atau vulgar.

            PERINGATAN KEBIJAKAN PERLINDUNGAN ANAK (ZERO TOLERANCE):
            Meskipun teks berbentuk "Berita", "Jurnalistik", atau "Kronologi Kejadian", JIKA di dalamnya memuat istilah seksual vulgar,
            teks tersebut DILARANG KERAS dikategorikan SAFE. Anda WAJIB memasukannya ke kategori berisiko dengan rating minimal 13+ atau 17+.

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
                        messages=[{"role": "user", "content": prompt}],  # type: ignore
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
                    print(f"[!] Kena Rate Limit Tim 1. Detail: {e.message}")
                    print(f"[!] Retry ke-{attempt+1} dalam {wait_time} detik...")
                    await asyncio.sleep(wait_time)
                except APIError as e:
                    print(f"[!] API Tim 1 Error dari OpenRouter: {e.message}")
                    break

            return {"kategori": "SAFE", "predicted_rating": "SU", "confidence_score": 0.0, "reason": "Rate Limit / API Error Maksimal"}

        # TIM 3 — Analisis Visual (dengan retry, rate limit handling, dan video keyframe extraction)
        async def call_llm_tim3_api(url: str, content_type: str, context_text: str = "", img_urls: list[str] | None = None) -> dict:
            prompt = f"""
            Anda adalah Mesin Inferensi Visual untuk Sistem Klasifikasi Konten Digital.
            Tugas Anda adalah MENGANALISA GAMBAR-GAMBAR YANG DILAMPIRKAN (jika ada). Jika gambar tidak ada, gunakan URL dan Teks Konteks.

            URL INPUT: "{url}"
            TIPE KONTEN: "{content_type}"
            TEKS/KONTEKS SEKITAR: "{context_text}"

            ATURAN KETAT (ANTI-HALUSINASI):
            DILARANG KERAS membuat asumsi liar terhadap suatu platform (misal: "TikTok sering berisi video pertarungan").
            Jika gambar fisik tidak dilampirkan dan teks konteks tidak memuat deskripsi spesifik tentang kekerasan/pelanggaran,
            Anda WAJIB memilih kategori SAFE. Berikan vonis HANYA berdasarkan bukti teks/gambar yang ada secara harfiah.

            PILIHAN KATEGORI VISUAL:
            Pornography_Keras, Pornography_Ringan, Animasi_Ringan, Animasi_Keras, SAFE, Drug, Addictive Substances, Medicine_Ringan, Medical_Ringan, Weapon_Ringan,
            Weapon_Keras, Toy_Ringan, Toy_Keras, Terrorism, Military_Ringan, Military_Keras, Violence, Sport_Ringan, Sport_Keras, SelfHarm, Medical_Keras

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

            import typing
            content_array: list[dict[str, typing.Any]] = [{"type": "text", "text": prompt}]

            if img_urls:
                for url_data in img_urls:
                    is_video = url_data.lower().endswith(VIDEO_EXTENSIONS)

                    if is_video:
                        print(f"[*] Memproses video untuk Tim 3: {url_data[:80]}...")
                        keyframe_urls = await process_media_url(url_data)
                        for frame_url in keyframe_urls:
                            content_array.append({
                                "type": "image_url",
                                "image_url": {"url": frame_url}
                            })
                        print(f"[*] {len(keyframe_urls)} keyframes (Base64) ditambahkan ke payload.")
                    else:
                        final_url = url_data
                        if not url_data.startswith("http") and not url_data.startswith("data:"):
                            from app.services.minio import get_file_base64
                            b64_res = await get_file_base64(url_data)
                            if b64_res.get("status") == "success":
                                final_url = b64_res["data_uri"]

                        content_array.append({
                            "type": "image_url",
                            "image_url": {"url": final_url}
                        })

            total_images = len(content_array) - 1
            print(f"[*] Total gambar/frame dalam payload Tim 3: {total_images}")

            max_retries = 3
            base_delay = 2.0

            for attempt in range(max_retries):
                try:
                    messages_payload: typing.Any = [{"role": "user", "content": content_array}]
                    response = await or_client.chat.completions.create(
                        model="google/gemini-2.0-flash-lite-001",
                        messages=messages_payload,  # type: ignore
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

            return {"kategori": "SAFE", "predicted_rating": "SU", "confidence_score": 0.0, "reason": "Rate Limit / API Error Maksimal"}

        for item in state["raw_contents"]:
            text_payload = item.get("content", "")
            url_payload = item.get("url", "")
            content_type = item.get("type", "text")

            # Payload Visual (Gambar + Video — video akan diproses keyframe oleh call_llm_tim3_api)
            media_payloads: list[str] = []
            media_urls = item.get("file_path", [])
            fallback_thumb = item.get("thumbnail_url", "")

            if media_urls:
                print(f"[*] Menyeleksi {len(media_urls)} file media untuk LLM...")
                for u in media_urls[:5]:
                    media_payloads.append(u)

                if not media_payloads and fallback_thumb:
                    print("[*] Fallback ke Thumbnail URL.")
                    media_payloads.append(fallback_thumb)
            else:
                if fallback_thumb:
                    media_payloads.append(fallback_thumb)

            print(f"[*] Payload akhir untuk Tim 3 Visual AI: {len(media_payloads)} media (gambar/video).")

            # Eksekusi sekuensial untuk menghindari rate limit OpenRouter
            print("[*] Meminta analisis Tim 1 (Teks)...")
            hasil_tim1 = await call_llm_tim1_api(text_payload)

            await asyncio.sleep(2.0)

            print("[*] Meminta analisis Tim 3 (Visual)...")
            hasil_tim3 = await call_llm_tim3_api(url_payload, content_type, text_payload, media_payloads)

            if hasil_tim1["kategori"] == "SAFE" and hasil_tim3["kategori"] == "SAFE":
                kategori_suspect = "SAFE"
            elif hasil_tim1["kategori"] == "SAFE":
                kategori_suspect = str(hasil_tim3["kategori"])
            elif hasil_tim3["kategori"] == "SAFE":
                kategori_suspect = str(hasil_tim1["kategori"])
            else:
                v_conf = hasil_tim3["confidence_score"]
                t_conf = hasil_tim1["confidence_score"]
                kategori_suspect = str(hasil_tim3["kategori"]) if v_conf > t_conf else str(hasil_tim1["kategori"])

            rule_suspect = await get_igrs_rule_by_kategori(kategori_suspect, session)
            igrs_rule = {
                "dominant_modality": rule_suspect.dominant_modality if rule_suspect else "EQUAL",
                "age_rating_minimal": rule_suspect.age_rating_minimal if rule_suspect else "SU",
            }

            final_decision = resolve_ai_conflict(hasil_tim1, hasil_tim3, igrs_rule)
            item["engine_decision"] = final_decision

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

            all_classified.append({
                "platform": item.get("source", "Umum"),
                "url": item.get("url", ""),
                "content_type": item.get("type", "text"),
                "bukti_teks": text_payload,
                "username": item.get("username", ""),
                "thumbnail_url": item.get("thumbnail_url", ""),
                "file_path": item.get("file_path", []),
                "vonis_hukum": {
                    "kategori": kategori_final,
                    "rating": rating_info,
                    "reason": final_decision.get("reason_final", ""),
                    "is_vetoed": False,
                },
            })

            print("[*] Jeda 4 detik sebelum memproses konten berikutnya...\n")
            await asyncio.sleep(4.0)

        print(f"\n[DEPTH {state['crawling_depth']}] GATEKEEPER: {len(unsafe_data)} beracun dari {len(all_classified)} konten.")
        return {
            "unsafe_contents": unsafe_data,
            "all_processed_contents": state.get("all_processed_contents", []) + all_classified,
        }

    return gatekeeper_node


def create_fork_processor_node(keyword_model):
    async def fork_processor_node(state: PADState):
        print(f"[DEPTH {state['crawling_depth']}] Memproses Forking...")
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
                "username": item.get("username", ""),
                "thumbnail_url": item.get("thumbnail_url", ""),
                "file_path": item.get("file_path", []),
                "vonis_hukum": {
                    "kategori": engine_decision.get("kategori_final", "Unknown"),
                    "rating": engine_decision.get("rating_final", "N/A"),
                    "reason": engine_decision.get("reason_final", ""),
                    "is_vetoed": False,
                },
            })

            generated_kws = await generate_keyword_local(text_payload, platform, keyword_model)
            if generated_kws:
                print(f"   [+] Keyword diekstrak: {generated_kws}")
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
            "crawling_depth": state.get("crawling_depth", 0) + 1,
        }

    return fork_processor_node
