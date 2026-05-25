import asyncio
import re
import random
from sqlalchemy.ext.asyncio import AsyncSession
from .state import PADState
from .crawler_service import run_trend_crawlers, run_content_crawlers
from app.services.resolver import resolve_ai_conflict
from app.services.classification import get_igrs_rule_by_kategori
from app.services.real_ml import call_llm_tim1, call_llm_tim3

TARGET_POST_PER_KEYWORD = 2
MAX_TOTAL_CONTENTS = 25


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

    # Safety net: kalau crawler benar-benar mati, kasih satu konten dummy
    # supaya graph tetap mengalir sampai gatekeeper (tidak deadlock di iterasi kosong)
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
        print(f"\n[DEPTH {state['crawling_depth']}] Gatekeeper menyaring {len(state['raw_contents'])} konten...")
        unsafe_data = []
        all_classified = []

        for item in state["raw_contents"]:
            text_payload = item.get("content", "")
            url_payload = item.get("url", "")
            content_type = item.get("type", "text")

            thumbnail_payloads: list[str] = []
            media_urls = item.get("file_path", [])
            fallback_thumb = item.get("thumbnail_url", "")

            if media_urls:
                for u in media_urls[:3]:
                    if not u.lower().endswith((".mp4", ".webm", ".mkv", ".mov", ".avi")):
                        thumbnail_payloads.append(u)
                if not thumbnail_payloads and fallback_thumb:
                    thumbnail_payloads.append(fallback_thumb)
            elif fallback_thumb:
                thumbnail_payloads.append(fallback_thumb)

            hasil_tim1, hasil_tim3 = await asyncio.gather(
                call_llm_tim1(url_payload, text_payload),
                call_llm_tim3(url_payload, content_type, text_payload, thumbnail_payloads),
            )

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

            is_unsafe = rating_info in {"13+", "17+", "PRC"}
            if kategori_final == "UNRATED" or rating_info == "UNRATED":
                print(f"   [?] NEEDS REVIEW: UNRATED.")
            elif is_unsafe:
                print(f"   [!] BAHAYA (Rating: {rating_info}): '{kategori_final}'")
                unsafe_data.append(item)
            else:
                print(f"   [v] SAFE (Rating: {rating_info}): '{kategori_final}'")

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

        truly_new_kws = [
            kw for kw in set(new_keywords_generated)
            if kw not in state.get("history_keywords", [])
        ]
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
