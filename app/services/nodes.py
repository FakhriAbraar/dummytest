import asyncio
import json
import os
import re
import random
from openai import AsyncOpenAI, APIError, RateLimitError
from sqlalchemy.ext.asyncio import AsyncSession
from .state import PADState
from .crawler_service import run_trend_crawlers, run_content_crawlers
from app.services.resolver import resolve_ai_conflict
from app.services.classification import get_igrs_rule_by_kategori
from app.services.video_extractor import process_media_url, VIDEO_EXTENSIONS
from app.services.visual_client import classify_visual

or_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")
)

TARGET_POST_PER_KEYWORD = 2
# Circuit-breaker keseluruhan agar snowball tidak meledak tak terbatas.
# Jumlah konten per platform diatur via Crawl Config / Auto-Crawler (adjustable),
# jadi nilai ini sengaja dibuat besar (praktis "tanpa batas" untuk kebutuhan POC).
MAX_TOTAL_CONTENTS = 1000

# Model klasifikasi gatekeeper — dapat di-override via .env tanpa ubah kode.
# Default memakai model :free OpenRouter (rate limit ketat: 8 rpm + kuota harian).
# Untuk produksi, set ke model berbayar/ber-key, mis. "qwen/qwen3-next-80b-a3b-instruct".
GATEKEEPER_TEXT_MODEL = os.getenv("GATEKEEPER_TEXT_MODEL", "deepseek/deepseek-v4-flash")
GATEKEEPER_VISUAL_MODEL = os.getenv("GATEKEEPER_VISUAL_MODEL", "google/gemma-4-31b-it:free")


def _parse_retry_after(exc: Exception) -> float | None:
    """Ekstrak waktu tunggu (detik) dari error 429 OpenRouter bila tersedia.

    Mengecek berurutan: metadata.retry_after_seconds, header Retry-After, lalu
    X-RateLimit-Reset (epoch ms). Reset yang terlalu jauh (>120s, mis. kuota
    harian) diabaikan agar tidak tidur berjam-jam.
    """
    try:
        body = getattr(exc, "body", None) or {}
        if not isinstance(body, dict):
            return None
        meta = body.get("error", {}).get("metadata", {}) or {}
        secs = meta.get("retry_after_seconds")
        if secs is not None:
            return float(secs) + 1
        headers = meta.get("headers", {}) or {}
        ra = headers.get("Retry-After")
        if ra is not None:
            return float(ra) + 1
        reset = headers.get("X-RateLimit-Reset")
        if reset is not None:
            import time as _t
            delta = float(reset) / 1000.0 - _t.time()
            if 0 < delta <= 120:
                return delta + 1
    except Exception:
        pass
    return None


def _is_daily_quota_error(exc: Exception) -> bool:
    """True bila 429 berasal dari kuota harian model :free (tidak bisa di-retry)."""
    msg = str(getattr(exc, "message", "") or exc).lower()
    return "per-day" in msg or "per day" in msg


def extract_json_from_llm(raw_text: str | None) -> dict:
    if not raw_text:
        return {}
    try:
        match = re.search(r'\{.*\}', raw_text.strip(), re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return json.loads(raw_text)
    except json.JSONDecodeError:
        print(f"[gatekeeper] LLM JSON parse failed: {raw_text!r}")
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
            print(f"[fork] keyword extraction (regex fallback, GGUF unavailable): {result}")
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
        print(f"[fork] keyword model error: {e}")
        return []


# =====================================================================
# LANGGRAPH NODES
# =====================================================================

async def trend_crawler_node(state: PADState, progress=None):
    retry_count = state.get("trend_retry", 0)
    print(f"\n[trend_crawler] START batch={retry_count + 1}")

    # "Loading Keywords": keyword kustom dari form Crawl Config.
    if progress:
        progress.start_stage("Loading Keywords")
    custom = [k.strip() for k in state.get("custom_keywords", []) if k and k.strip()]
    if progress:
        progress.complete_stage("Loading Keywords")

    # "Fetching Trending Keywords": ambil trending kecuali seed tunggal diberikan.
    # Jumlah keyword per batch dikontrol dari setting Auto-Crawler (default 3).
    keyword_count = max(1, state.get("trends_keyword_count", 3) or 3)
    if progress:
        progress.start_stage("Fetching Trending Keywords")
    try:
        if state.get("seed_trend", "").strip():
            trending = [state["seed_trend"]]
        else:
            trending_data = await run_trend_crawlers()
            start_idx = retry_count * keyword_count
            trending = trending_data[start_idx : start_idx + keyword_count]
        if progress:
            progress.complete_stage("Fetching Trending Keywords")
    except Exception as exc:
        if progress:
            progress.fail_stage("Fetching Trending Keywords", exc)
        raise

    # Keyword kustom hanya dipakai di batch pertama agar tidak diulang saat retry.
    if retry_count == 0 and custom:
        initial_keywords = []
        for kw in custom + trending:
            if kw not in initial_keywords:
                initial_keywords.append(kw)
    else:
        initial_keywords = trending

    return {
        "current_keywords": initial_keywords,
        "history_keywords": state.get("history_keywords", []) + initial_keywords,
        "trend_retry": retry_count + 1,
        "crawling_depth": 0,
    }


async def content_crawler_node(state: PADState, progress=None):
    current_total = state.get("total_processed_contents", 0)

    if current_total >= MAX_TOTAL_CONTENTS:
        print(f"[content_crawler] STOP: total content limit reached (max={MAX_TOTAL_CONTENTS})")
        return {"raw_contents": []}

    print(f"[content_crawler] depth={state['crawling_depth']} keywords={state['current_keywords']}")
    platform_limits = state.get("platform_limits") or {}
    all_crawled_data = []

    for kw in state["current_keywords"]:
        hasil_scrape = await run_content_crawlers(
            kw,
            limit=TARGET_POST_PER_KEYWORD,
            platform_limits=platform_limits,
            progress=progress,
        )
        all_crawled_data.extend(hasil_scrape)

    # "Saving Raw Content": konten mentah ronde ini diserahkan ke Gatekeeper.
    if progress:
        progress.start_stage("Saving Raw Content")
        progress.complete_stage("Saving Raw Content")

    # Tanpa dummy: bila crawler tidak mengembalikan konten apa pun, biarkan
    # kosong dan log dengan jelas (kegagalan tidak disamarkan dengan data palsu).
    if not all_crawled_data:
        print(
            "[content_crawler] ERROR: 0 items returned for "
            f"keywords={state['current_keywords']} (see crawler subprocess stderr above)"
        )

    return {
        "raw_contents": all_crawled_data,
        "total_processed_contents": current_total + len(all_crawled_data),
    }


def create_gatekeeper_node(session: AsyncSession, progress=None):
    async def gatekeeper_node(state: PADState):
        print(f"\n[gatekeeper] depth={state['crawling_depth']} classifying {len(state['raw_contents'])} item(s) via OpenRouter")
        # "Running Classification": Tim 1 (teks) + Tim 3 (visual) per konten.
        if progress:
            progress.start_stage("Running Classification")
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
            - Netral, Violence, Sexual, Harrasment, Hateful_Content, Self-Harm
            
            RATING USIA (Wajib disesuaikan dengan Kategori Teks):
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

            max_retries = 4
            base_delay = 5.0

            for attempt in range(max_retries):
                try:
                    response = await or_client.chat.completions.create(
                        model=GATEKEEPER_TEXT_MODEL,
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
                    if _is_daily_quota_error(e):
                        print("[gatekeeper] tim1(text) kuota harian model :free habis — stop retry.")
                        break
                    # Hormati Retry-After dari server; fallback ke exponential backoff.
                    wait_time = _parse_retry_after(e) or (base_delay * (2 ** attempt))
                    wait_time = min(wait_time, 60.0)
                    print(f"[gatekeeper] tim1(text) rate limited: {e.message}")
                    print(f"[gatekeeper] retry {attempt+1}/{max_retries} in {wait_time:.1f}s")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(wait_time)
                except APIError as e:
                    print(f"[gatekeeper] tim1(text) OpenRouter API error: {e.message}")
                    break

            return {"kategori": "SAFE", "predicted_rating": "SU", "confidence_score": 0.0, "reason": "Rate Limit / API Error Maksimal"}

        # TIM 3 — Analisis Visual via endpoint model visual Tim 3 (pad3_model).
        # Gambar/video di-resolve dulu (keyframe video, base64 MinIO) lalu ditembak
        # ke visual_client.classify_visual (lihat app/services/visual_client.py).
        async def call_llm_tim3_api(url: str, content_type: str, context_text: str = "", img_urls: list[str] | None = None) -> dict:
            resolved_images: list[str] = []

            if img_urls:
                for url_data in img_urls:
                    is_video = url_data.lower().endswith(VIDEO_EXTENSIONS)

                    if is_video:
                        print(f"[gatekeeper] tim3(visual) video keyframe extraction: {url_data[:80]}")
                        keyframe_urls = await process_media_url(url_data)
                        resolved_images.extend(keyframe_urls)
                        print(f"[gatekeeper] tim3(visual) added {len(keyframe_urls)} keyframe(s) to payload")
                    else:
                        final_url = url_data
                        if not url_data.startswith("http") and not url_data.startswith("data:"):
                            from app.services.minio import get_file_base64
                            b64_res = await get_file_base64(url_data)
                            if b64_res.get("status") == "success":
                                final_url = b64_res["data_uri"]
                        resolved_images.append(final_url)

            print(f"[gatekeeper] tim3(visual) payload images={len(resolved_images)}")
            return await classify_visual(context_text, resolved_images, content_type=content_type)

        for item in state["raw_contents"]:
            text_payload = item.get("content", "")
            url_payload = item.get("url", "")
            content_type = item.get("type", "text")

            # Payload Visual (Gambar + Video — video akan diproses keyframe oleh call_llm_tim3_api)
            media_payloads: list[str] = []
            media_urls = item.get("file_path", [])
            fallback_thumb = item.get("thumbnail_url", "")

            if media_urls:
                print(f"[gatekeeper] selecting {len(media_urls)} media file(s) for tim3(visual)")
                for u in media_urls[:5]:
                    media_payloads.append(u)

                if not media_payloads and fallback_thumb:
                    print("[gatekeeper] media empty, fallback to thumbnail_url")
                    media_payloads.append(fallback_thumb)
            else:
                if fallback_thumb:
                    media_payloads.append(fallback_thumb)

            print(f"[gatekeeper] tim3(visual) final payload media={len(media_payloads)}")

            # Eksekusi sekuensial untuk menghindari rate limit OpenRouter
            print("[gatekeeper] tim1(text) request")
            hasil_tim1 = await call_llm_tim1_api(text_payload)

            await asyncio.sleep(2.0)

            print("[gatekeeper] tim3(visual) request")
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

            kategori_final = final_decision.get("kategori_final", "SAFE")
            rating_info = final_decision.get("rating_final", "SU")

            # Pertahankan tipe IGRS konkret untuk konten aman.
            # Kasus: salah satu AI mengembalikan "SAFE" generik sehingga pemenang
            # resolver = "SAFE", padahal AI lain sudah mengenali kategori IGRS
            # konkret yang ratingnya juga aman (mis. Sport_Ringan/Animasi_Ringan).
            # Hanya berlaku saat rating final aman (SU/7+) DAN kategori suspect
            # juga ber-rating aman -> tidak melemahkan pelabelan konten berbahaya.
            SAFE_RATINGS = {"SU", "7+"}
            suspect_min_rating = igrs_rule.get("age_rating_minimal", "SU")
            if (
                kategori_final == "SAFE"
                and rating_info in SAFE_RATINGS
                and kategori_suspect not in ("SAFE", "")
                and suspect_min_rating in SAFE_RATINGS
            ):
                print(
                    f"[gatekeeper] kategori enrichment: SAFE -> {kategori_suspect} "
                    f"(rating tetap {rating_info})"
                )
                kategori_final = kategori_suspect
                final_decision["kategori_final"] = kategori_final

            item["engine_decision"] = final_decision

            TARGET_RATINGS = {"13+", "17+", "PRC"}

            if kategori_final == "UNRATED" or rating_info == "UNRATED":
                print("[gatekeeper] verdict=NEEDS_REVIEW (UNRATED) -> stored, excluded from keyword generator")
            elif rating_info in TARGET_RATINGS:
                print(f"[gatekeeper] verdict=UNSAFE rating={rating_info} kategori={kategori_final} -> keyword generator")
                unsafe_data.append(item)
            else:
                print(f"[gatekeeper] verdict=SAFE rating={rating_info} kategori={kategori_final} -> stored, excluded from keyword generator")

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

            print("[gatekeeper] sleep 4s before next item\n")
            await asyncio.sleep(4.0)

        print(f"\n[gatekeeper] depth={state['crawling_depth']} done: flagged_unsafe={len(unsafe_data)}/{len(all_classified)}")
        if progress:
            progress.complete_stage("Running Classification")
        return {
            "unsafe_contents": unsafe_data,
            "all_processed_contents": state.get("all_processed_contents", []) + all_classified,
        }

    return gatekeeper_node


def create_fork_processor_node(keyword_model, progress=None):
    async def fork_processor_node(state: PADState):
        print(f"[fork] depth={state['crawling_depth']} START (keyword expansion)")
        # "Generating RAG Analysis": ekstraksi entitas + keyword turunan.
        if progress:
            progress.start_stage("Generating RAG Analysis")
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
                print(f"[fork] extracted keywords: {generated_kws}")
            new_keywords_generated.extend(generated_kws)

        new_keywords_generated = list(set(new_keywords_generated))
        truly_new_kws = [kw for kw in new_keywords_generated if kw not in state.get("history_keywords", [])]

        if len(truly_new_kws) > 3:
            truly_new_kws = random.sample(truly_new_kws, 3)
            print(f"[fork] snowball cap: trimmed new keywords to 3: {truly_new_kws}")

        if progress:
            progress.complete_stage("Generating RAG Analysis")
        return {
            "extracted_entities": state.get("extracted_entities", []) + new_extracted_entities,
            "current_keywords": truly_new_kws,
            "history_keywords": state.get("history_keywords", []) + truly_new_kws,
            "crawling_depth": state.get("crawling_depth", 0) + 1,
        }

    return fork_processor_node
