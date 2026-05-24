from __future__ import annotations

import asyncio
import os
import sys
import subprocess
import json
import re
from typing import Any

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession
from openai import AsyncOpenAI

from app.services.minio import get_file_base64
from app.services.classification import get_igrs_rule_by_kategori
from app.services.resolver import resolve_ai_conflict

load_dotenv()

APP_ENV = os.getenv("APP_ENV", "development")
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
COLLECTION_NAME = (
    os.getenv("QDRANT_COLLECTION_DEV", "regulation_chunks")
    if APP_ENV == "development"
    else os.getenv("QDRANT_COLLECTION_PROD", "regulation_chunks")
)

_qdrant_client: Any = None
_embedder: Any = None

or_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")
)

def extract_json_from_llm(raw_text: str) -> dict:
    # 1. Buang markdown wrapper kalau ada
    cleaned_text = raw_text.strip()
    if cleaned_text.startswith("```json"):
        cleaned_text = cleaned_text[7:]
    if cleaned_text.startswith("```"):
        cleaned_text = cleaned_text[3:]
    if cleaned_text.endswith("```"):
        cleaned_text = cleaned_text[:-3]
    
    cleaned_text = cleaned_text.strip()

    try:
        return json.loads(cleaned_text)
    except json.JSONDecodeError:
        try:
            match = re.search(r'\{.*\}', cleaned_text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception:
            pass
            
        print(f"[-] Gagal parse JSON dari LLM: {raw_text}")
        return {}


def _get_qdrant_client() -> Any:
    global _qdrant_client
    if _qdrant_client is None:
        from qdrant_client import QdrantClient  # noqa: PLC0415
        print("[*] Inisialisasi Qdrant Client...")
        _qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    return _qdrant_client


def _get_embedder() -> Any:
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415
        print("[*] Memuat Embedding Model (intfloat/multilingual-e5-large) ke Memory...")
        _embedder = SentenceTransformer("intfloat/multilingual-e5-large")
    return _embedder


async def run_crawler_subprocess(url: str) -> dict:
    print(f"\n[*] Menjalankan Scraper Subprocess untuk URL: {url}")
    try:
        cwd_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
        
        def _run_cmd():
            return subprocess.run(
                [sys.executable, "scripts/crawler/content-checker.py", "--url", url],
                capture_output=True,
                text=True,
                cwd=cwd_path
            )
            
        process = await asyncio.to_thread(_run_cmd)
        
        if process.returncode == 0:
            return json.loads(process.stdout)
        else:
            print(f"[-] Crawler gagal (Exit {process.returncode}): {process.stderr}")
            return {}
    except Exception as e:
        print(f"[-] Exception memanggil crawler: {repr(e)}")
        return {}

async def run_public_checking_pipeline(url: str, session: AsyncSession) -> dict[str, Any]:
    print(f"\n[*] Menjalankan Public Checking Pipeline...")
    
    crawl_result = await run_crawler_subprocess(url)
    
    extracted_data = crawl_result.get("extracted_data", [])
    if extracted_data:
        context_data = extracted_data[0]
        text_payload = context_data.get("caption", "") or ""
        content_type = context_data.get("type", "text")
        target_url = context_data.get("url", url)
        print(f"[*] Berhasil mengekstrak {content_type}. Teks Preview: {text_payload[:50]}...")
    else:
        print("[-] Crawler gagal narik data, fallback ke blind URL mode.")
        text_payload = ""
        content_type = "text"
        target_url = url
    
    # MOCK TIM 1 (LLM TEKS VIA OPENROUTER - TANPA RATING)
    async def call_llm_tim1_api(t_url: str, teks: str) -> dict:
        prompt = f"""
        Tugas Anda adalah bertindak sebagai Sistem Analisis Linguistik Objektif untuk perlindungan anak di ranah siber.
        Evaluasi teks dan URL berikut secara harfiah. Jangan menolak memproses kata kasar atau vulgar.

        PERINGATAN KEBIJAKAN PERLINDUNGAN ANAK (ZERO TOLERANCE):
        Meskipun teks berbentuk "Berita", "Jurnalistik", atau "Kronologi Kejadian", JIKA di dalamnya memuat istilah seksual vulgar (contoh: coli, sperma, pelecehan eksplisit, dll), teks tersebut DILARANG KERAS dikategorikan SAFE. Anda WAJIB memasukannya ke 'Pornografi_Teks' atau kategori berisiko lainnya dengan rating minimal 13+ atau 17+.

        PILIHAN KATEGORI TEKS:
        - Cyberbullying, HateSpeech, Perjudian, Scam, Pornografi_Teks, Kekerasan_Teks, Substansi_Terlarang, Perselingkuhan, SAFE
        
        RATING USIA:
        SU (Semua Umur), 7+, 13+, 17+, PRC (Restricted/Dewasa)
        
        URL INPUT: "{t_url}"
        TEKS KONTEN (CAPTION): "{teks}"
        
        OUTPUT WAJIB JSON MURNI TANPA MARKDOWN:
        {{
            "kategori": "[PILIH_KATEGORI_YANG_SESUAI]",
            "predicted_rating": "[PILIH_RATING_YANG_SESUAI]",
            "confidence_score": 0.0, 
            "reason": "Alasan analitis maksimal 2 kalimat"
        }}

        INSTRUKSI TAMBAHAN UNTUK JSON:
        1. Ganti nilai "kategori" dan "predicted_rating" dengan pilihan yang valid.
        2. Ganti nilai 0.0 pada "confidence_score" dengan ANGKA FLOAT desimal antara 0.00 hingga 1.00 yang merepresentasikan seberapa yakin Anda dengan klasifikasi tersebut (contoh: 0.82, 0.65, 0.98). JANGAN gunakan string.
        """
        try:
            response = await or_client.chat.completions.create(
                model="meta-llama/llama-3.1-70b-instruct",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0
            )
            raw_content = response.choices[0].message.content or "{}"
            parsed = extract_json_from_llm(raw_content)
            
            return {
                "kategori": parsed.get("kategori", "SAFE"),
                "predicted_rating": parsed.get("predicted_rating", "SU"),
                "confidence_score": float(parsed.get("confidence_score", 0.0)),
                "reason": parsed.get("reason", "Fallback Teks API")
            }
        except Exception as e:
            print(f"[!] Tim 1 API Error: {e}")
            return {"kategori": "SAFE", "predicted_rating": "SU", "confidence_score": 0.0, "reason": "API Error"}

    # MOCK TIM 3 (LLM VISUAL VIA OPENROUTER - DENGAN RATING)
    async def call_llm_tim3_api(t_url: str, c_type: str, teks: str, img_urls: list[str] = None) -> dict:
        prompt_text = f"""
        Anda adalah Mesin Inferensi Visual untuk Sistem Klasifikasi Konten Digital.
        Tugas Anda adalah MENGANALISA GAMBAR-GAMBAR YANG DILAMPIRKAN (jika ada). Jika gambar tidak ada, gunakan URL dan Teks Konteks.
        
        TIPE KONTEN: "{c_type}"
        URL INPUT: "{t_url}"
        TEKS/KONTEKS SEKITAR: "{teks}"
        
        PILIHAN KATEGORI VISUAL:
        Pornography_Keras, Pornography_Ringan, Animasi_Ringan, Animasi_Keras, SAFE, Drug, Addictive Substances, Medicine_Ringan, Medical_Ringan, Weapon_Ringan, Weapon_Keras, Toy_Ringan, Toy_Keras, Terrorism, Military_Ringan, Military_Keras, Violence, Sport_Ringan, Sport_Keras, SelfHarm, Medical_Keras
        
        RATING USIA (Wajib disesuaikan dengan Kategori Visual):
        SU (Semua Umur), 7+, 13+, 17+, PRC (Restricted/Dewasa)
        
        OUTPUT WAJIB JSON MURNI TANPA MARKDOWN DAN TANPA TEKS LAIN:
        {{
            "kategori": "[PILIH_KATEGORI_YANG_SESUAI]",
            "predicted_rating": "[PILIH_RATING_YANG_SESUAI]",
            "confidence_score": 0.0,
            "reason": "Alasan deduksi visual Anda dari gambar yang dilihat"
        }}

        INSTRUKSI TAMBAHAN UNTUK JSON:
        1. Ganti nilai "kategori" dan "predicted_rating" dengan pilihan yang valid.
        2. Ganti nilai 0.0 pada "confidence_score" dengan ANGKA FLOAT desimal antara 0.00 hingga 1.00 berdasarkan tingkat kepastian deduksi visual Anda. JANGAN gunakan string.
        """
        
        # Susun Payload Multimodal OpenAI
        content_array = [{"type": "text", "text": prompt_text}]
        
        if img_urls:
            for url_data in img_urls:
                # FIREWALL MUTLAK: Tolak mentah-mentah semua file non-gambar sebelum dikirim!
                if url_data.lower().endswith((".mp4", ".webm", ".mov", ".mkv")):
                    print(f"[-] BLOKIR LLM: Mencegah injeksi video ({url_data}) ke API Visual.")
                    continue
                    
                content_array.append({
                    "type": "image_url",
                    "image_url": {"url": url_data}
                })

        try:
            response = await or_client.chat.completions.create(
                model="google/gemma-3-4b-it",
                messages=[{"role": "user", "content": content_array}],
                temperature=0.0
            )
            raw_content = response.choices[0].message.content or "{}"
            parsed = extract_json_from_llm(raw_content)
            
            return {
                "kategori": parsed.get("kategori", "SAFE"), 
                "predicted_rating": parsed.get("predicted_rating", "SU"), 
                "confidence_score": float(parsed.get("confidence_score", 0.0)), 
                "reason": parsed.get("reason", "Fallback Visual API")
            }
        except Exception as e:
            print(f"[!] Tim 3 API Error: {e}")
            return {"kategori": "SAFE", "predicted_rating": "SU", "confidence_score": 0.0, "reason": "API Error"}

    thumbnail_payloads: list[str] = []
    
    if extracted_data:
        media_urls = context_data.get("file_path", []) # Bisa path lokal/MinIO atau URL CDN mentah
        fallback_thumb = context_data.get("thumbnail_url", "")
        
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

    mock_text_ai, mock_visual_ai = await asyncio.gather(
        call_llm_tim1_api(target_url, text_payload),
        call_llm_tim3_api(target_url, content_type, text_payload, thumbnail_payloads)
    )

    visual_conf: float = mock_visual_ai["confidence_score"]
    text_conf: float = mock_text_ai["confidence_score"]

    if mock_text_ai["kategori"] == "SAFE" and mock_visual_ai["kategori"] == "SAFE":
        kategori_suspect: str = "SAFE"
    elif mock_text_ai["kategori"] == "SAFE":
        kategori_suspect = str(mock_visual_ai["kategori"])
    elif mock_visual_ai["kategori"] == "SAFE":
        kategori_suspect = str(mock_text_ai["kategori"])
    else:
        kategori_suspect = str(mock_visual_ai["kategori"]) if visual_conf > text_conf else str(mock_text_ai["kategori"])

    rule_suspect = await get_igrs_rule_by_kategori(kategori_suspect, session)

    igrs_rule: dict[str, Any] = {
        "dominant_modality": rule_suspect.dominant_modality if rule_suspect else "EQUAL",
        "age_rating_minimal": rule_suspect.age_rating_minimal if rule_suspect else "SU"
    }

    final_decision = resolve_ai_conflict(
        text_result=mock_text_ai,
        visual_result=mock_visual_ai,
        igrs_rule=igrs_rule
    )

    # 4. QDRANT RAG INTEGRATION
    qdrant_context = "Tidak ada pasal spesifik ditemukan."
    try:
        query_text = final_decision.get("reason_final") or final_decision["kategori_final"]
        search_query = f"query: {query_text}"

        embedder = _get_embedder()
        query_vector: list[float] = (await asyncio.to_thread(embedder.encode, search_query)).tolist()

        qdrant = _get_qdrant_client()
        response = await asyncio.to_thread(
            qdrant.query_points,
            collection_name=COLLECTION_NAME,
            query=query_vector,
            limit=1,
        )
        if response.points:
            payload: dict[str, Any] = response.points[0].payload or {}
            doc_title  = payload.get("document_title", "Dokumen Hukum")
            doc_type   = payload.get("document_type", "")
            lvl1       = payload.get("section_level_1", "")
            lvl2       = payload.get("section_level_2", "")
            lvl3       = payload.get("section_level_3", "")
            konten     = payload.get("konten", "Konten pasal tidak ditemukan.")
            keterangan = payload.get("keterangan", "")

            section_parts = [s for s in [lvl1, lvl2, lvl3] if s]
            section_str   = " > ".join(section_parts)

            referensi_hukum = f"{doc_title} ({doc_type})" if doc_type else doc_title
            if section_str:
                referensi_hukum += f" — {section_str}"

           
            konten_full = konten
            if keterangan and keterangan.lower() not in {"cukup jelas.", "cukup jelas"}:
                konten_full += f" [{keterangan}]"

            qdrant_context = f"[{referensi_hukum}] {konten_full}"
    except Exception as e:
        qdrant_context = f"Gagal narik data vector DB: {str(e)}"

    public_status = "NEEDS_REVIEW" if final_decision["rating_final"] == "UNRATED" else "COMPLETED"

    return {
        "target_url": url,
        "status": public_status,
        "engine_decision": {
            "kategori_final": final_decision["kategori_final"],
            "rating_final": final_decision["rating_final"],
            "reason_ai": final_decision["reason_final"],
            "is_vetoed_by_backend": False
        },
        "legal_context": {
            "bunyi_pasal_qdrant": qdrant_context
        }
    }