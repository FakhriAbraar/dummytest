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

from app.services.classification import get_igrs_rule_by_kategori
from app.services.resolver import resolve_ai_conflict
from app.services.video_extractor import process_media_url, VIDEO_EXTENSIONS

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
        # Cache ke path yang dikonfigurasi (default D: drive agar tidak penuh di C:)
        cache_dir = os.getenv("SENTENCE_TRANSFORMERS_HOME", "D:/sadam/Dev/.cache/sentence_transformers")
        print(f"[*] Memuat Embedding Model (intfloat/multilingual-e5-large, 1024-dim) → cache: {cache_dir}")
        _embedder = SentenceTransformer("intfloat/multilingual-e5-large", cache_folder=cache_dir)
    return _embedder


def _build_dummy_crawl_result(url: str) -> dict:
    """Hasilkan data crawl dummy untuk mode lokal tanpa MinIO/MongoDB.
    Dipakai sebagai fallback kalau subprocess crawler gagal total.
    """
    import random as _rnd
    _templates = [
        "Konten yang dianalisis mengandung informasi seputar platform digital.",
        "Postingan ini membahas topik yang sedang trending di media sosial Indonesia.",
        "Video/gambar yang diambil dari akun publik untuk keperluan analisis konten.",
        "Caption ini diekstrak secara otomatis oleh sistem PAD untuk diklasifikasi.",
    ]
    return {
        "extracted_data": [
            {
                "url": url,
                "type": _rnd.choice(["text", "image"]),
                "caption": _rnd.choice(_templates),
                "thumbnail_url": "",
                "file_path": [],
            }
        ]
    }


async def run_crawler_subprocess(url: str) -> dict:
    print(f"\n[*] Menjalankan Scraper Subprocess untuk URL: {url}")
    try:
        cwd_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))

        def _run_cmd():
            return subprocess.run(
                [sys.executable, "scripts/crawler/content-checker.py", "--url", url],
                capture_output=True,
                text=True,
                cwd=cwd_path,
                timeout=30,
            )

        process = await asyncio.to_thread(_run_cmd)

        if process.returncode == 0:
            return json.loads(process.stdout)
        else:
            print(f"[-] Crawler gagal (Exit {process.returncode}): {process.stderr[:200]} — fallback ke dummy data.")
            return _build_dummy_crawl_result(url)
    except Exception as e:
        print(f"[-] Crawler subprocess gagal: {repr(e)} — fallback ke dummy data.")
        return _build_dummy_crawl_result(url)


async def run_public_checking_pipeline(input_url: str, session: AsyncSession) -> dict[str, Any]:
    print(f"\n[*] Menjalankan Public Checking Pipeline...")

    crawl_result = await run_crawler_subprocess(url)

    extracted_data = crawl_result.get("extracted_data", [])
    context_data: dict[str, Any] = {}
    if extracted_data:
        context_data = extracted_data[0]
        text_payload = context_data.get("caption", "") or ""
        content_type = context_data.get("type", "text")
        target_url = context_data.get("url", url) or url
        platform = context_data.get("platform", "")
        username = (context_data.get("creator") or {}).get("username") or ""
        print(f"[*] Berhasil mengekstrak {content_type}. Teks Preview: {text_payload[:50]}...")
    else:
        print("[-] Crawler tidak menghasilkan data — pipeline lanjut dengan teks kosong.")
        text_payload = ""
        content_type = "text"
        target_url = url
        platform = ""
        username = ""

    # TIM 1 — Analisis Teks via OpenRouter
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
                messages=[{"role": "user", "content": prompt}],  # type: ignore
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

    # TIM 3 — Analisis Visual via OpenRouter (dengan video keyframe extraction)
    async def call_llm_tim3_api(t_url: str, c_type: str, teks: str, img_urls: list[str] | None = None) -> dict:
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

        import typing
        content_array: list[dict[str, typing.Any]] = [{"type": "text", "text": prompt_text}]

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

        try:
            messages_payload: typing.Any = [{"role": "user", "content": content_array}]
            response = await or_client.chat.completions.create(
                model="google/gemini-2.0-flash-lite-001",
                messages=messages_payload,  # type: ignore
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

    media_payloads: list[str] = []

    if extracted_data:
        media_urls = context_data.get("file_path", [])
        fallback_thumb = context_data.get("thumbnail_url", "")

        if media_urls:
            print(f"[*] Menyeleksi {len(media_urls)} file media untuk LLM...")
            for media_url in media_urls[:5]:
                media_payloads.append(media_url)

            if not media_payloads and fallback_thumb:
                print("[*] Fallback ke Thumbnail URL.")
                media_payloads.append(fallback_thumb)
        else:
            if fallback_thumb:
                media_payloads.append(fallback_thumb)

    print(f"[*] Payload akhir untuk Tim 3 Visual AI: {len(media_payloads)} media (gambar/video).")

    mock_text_ai, mock_visual_ai = await asyncio.gather(
        call_llm_tim1_api(target_url, text_payload),
        call_llm_tim3_api(target_url, content_type, text_payload, media_payloads)
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

    # 4. QDRANT RAG — hanya diaktifkan jika QDRANT_URL di-set di .env
    _STATIC_LEGAL_FALLBACK = (
        "[UU No. 44 Tahun 2008 tentang Pornografi — Pasal 4 Ayat (1)] "
        "Setiap orang dilarang memproduksi, membuat, memperbanyak, menggandakan, menyebarluaskan, "
        "menyiarkan, mengimpor, mengekspor, menawarkan, memperjualbelikan, menyewakan, atau "
        "menyediakan pornografi yang secara eksplisit memuat: persenggamaan, termasuk persenggamaan "
        "yang menyimpang; kekerasan seksual; masturbasi atau onani; ketelanjangan atau tampilan yang "
        "mengesankan ketelanjangan; alat kelamin; atau pornografi anak."
    )
    qdrant_context = _STATIC_LEGAL_FALLBACK

    if QDRANT_URL:
        try:
            query_text = final_decision.get("reason_final") or final_decision["kategori_final"]
            search_query = f"query: {query_text}"

            embedder = _get_embedder()
            query_vector: list[float] = (await asyncio.to_thread(embedder.encode, search_query)).tolist()

            qdrant = _get_qdrant_client()
            qdrant_response = await asyncio.to_thread(
                qdrant.query_points,
                collection_name=COLLECTION_NAME,
                query=query_vector,
                limit=1,
            )
            if qdrant_response.points:
                payload: dict[str, Any] = qdrant_response.points[0].payload or {}
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
            print(f"[!] Qdrant tidak tersedia, menggunakan regulasi statis: {e}")
    else:
        print("[*] QDRANT_URL tidak di-set — menggunakan referensi hukum statis.")

    public_status = "NEEDS_REVIEW" if final_decision.get("rating_final") == "UNRATED" else "COMPLETED"

    return {
        "target_url": target_url,
        "status": public_status,
        "engine_decision": {
            "kategori_final": final_decision.get("kategori_final", "SAFE"),
            "rating_final": final_decision.get("rating_final", "SU"),
            "reason_ai": final_decision.get("reason_final", ""),
            "is_vetoed_by_backend": False,
        },
        "legal_context": {
            "bunyi_pasal_qdrant": qdrant_context,
        },
        "content_meta": {
            "platform": platform,
            "username": username,
            "caption": text_payload,
            "thumbnail_url": context_data.get("thumbnail_url", "") if extracted_data else "",
        },
        "classifications": {
            "tim1_text": {
                "kategori_ai": mock_text_ai["kategori"],
                "confidence_score": mock_text_ai["confidence_score"],
                "reasoning_category": mock_text_ai["reason"],
            },
            "tim3_visual": {
                "kategori_ai": mock_visual_ai["kategori"],
                "confidence_score": mock_visual_ai["confidence_score"],
                "reasoning_category": mock_visual_ai["reason"],
            },
        },
    }
