from __future__ import annotations

import asyncio
import os
import sys
import subprocess
import json
import re
from typing import Any

from dotenv import load_dotenv
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.classification import get_igrs_rule_by_kategori
from app.services.parent_advice import get_random_parent_advice
from app.services.resolver import resolve_ai_conflict
from app.services.video_extractor import process_media_url, VIDEO_EXTENSIONS
from app.services.visual_client import classify_visual

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

        print(f"[checker] LLM JSON parse failed: {raw_text!r}")
        return {}


def _get_qdrant_client() -> Any:
    global _qdrant_client
    if _qdrant_client is None:
        from qdrant_client import QdrantClient  # noqa: PLC0415
        print("[checker] init Qdrant client")
        _qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    return _qdrant_client


def _get_embedder() -> Any:
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415
        # Cache ke path yang dikonfigurasi (default D: drive agar tidak penuh di C:)
        cache_dir = os.getenv("SENTENCE_TRANSFORMERS_HOME", "../.cache/sentence_transformers")
        print(f"[checker] loading embedding model intfloat/multilingual-e5-large (1024-dim) cache={cache_dir}")
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
    print(f"\n[checker] scraper subprocess START url={url}")
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
            print(f"[checker] scraper FAILED exit={process.returncode} stderr={process.stderr[:200]!r} -> using dummy fallback metadata")
            return _build_dummy_crawl_result(url)
    except Exception as e:
        print(f"[checker] scraper subprocess error: {e!r} -> using dummy fallback metadata")
        return _build_dummy_crawl_result(url)


async def run_public_checking_pipeline(url: str, session: AsyncSession) -> dict[str, Any]:
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
        print(f"[checker] extracted content_type={content_type} text_preview={text_payload[:50]!r}")
    else:
        print("[-] Crawler gagal narik data, fallback ke blind URL mode.")
        text_payload = ""
        content_type = "text"
        target_url = url
        platform = ""
        username = ""

    # TIM 1 — Analisis Teks via endpoint Tim 1 (padsft di RunPod)
    async def call_llm_tim1_api(t_url: str, teks: str) -> dict:
        from app.services.text_client import classify_text
        return await classify_text(teks)

    # TIM 3 — Analisis Visual via endpoint Tim 3 (pad3_model di RunPod, lihat
    # app/services/visual_client.py). Gambar/video di-resolve dulu (keyframe video,
    # base64 MinIO) menjadi daftar URL siap kirim, lalu ditembak ke model visual.
    async def call_llm_tim3_api(t_url: str, c_type: str, teks: str, img_urls: list[str] | None = None) -> dict:
        resolved_images: list[str] = []

        if img_urls:
            for url_data in img_urls:
                is_video = url_data.lower().endswith(VIDEO_EXTENSIONS)

                if is_video:
                    print(f"[checker] tim3(visual) video keyframe extraction: {url_data[:80]}")
                    keyframe_urls = await process_media_url(url_data)
                    resolved_images.extend(keyframe_urls)
                    print(f"[checker] tim3(visual) added {len(keyframe_urls)} keyframe(s) to payload")
                else:
                    final_url = url_data
                    if not url_data.startswith("http") and not url_data.startswith("data:"):
                        from app.services.minio import get_file_base64
                        b64_res = await get_file_base64(url_data)
                        if b64_res.get("status") == "success":
                            final_url = b64_res["data_uri"]
                    resolved_images.append(final_url)

        print(f"[checker] tim3(visual) payload images={len(resolved_images)}")
        return await classify_visual(teks, resolved_images, content_type=c_type)

    media_payloads: list[str] = []

    if extracted_data:
        media_urls = context_data.get("file_path", [])
        fallback_thumb = context_data.get("thumbnail_url", "")

        if media_urls:
            print(f"[checker] selecting {len(media_urls)} media file(s) for tim3(visual)")
            for media_url in media_urls[:5]:
                media_payloads.append(media_url)

            if not media_payloads and fallback_thumb:
                print("[checker] media empty, fallback to thumbnail_url")
                media_payloads.append(fallback_thumb)
        else:
            if fallback_thumb:
                media_payloads.append(fallback_thumb)

    print(f"[checker] tim3(visual) final payload media={len(media_payloads)}")

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

    # Pertahankan tipe IGRS konkret untuk konten aman: bila pemenang resolver
    # "SAFE" tapi salah satu AI mengenali kategori IGRS konkret yang ratingnya
    # juga aman (SU/7+), pakai kategori konkret itu. Tidak melemahkan pelabelan
    # konten berbahaya (lihat catatan sama di gatekeeper nodes.py).
    _kf = final_decision.get("kategori_final", "SAFE")
    _rf = final_decision.get("rating_final", "SU")
    if (
        _kf == "SAFE"
        and _rf in ("SU", "7+")
        and kategori_suspect not in ("SAFE", "")
        and igrs_rule["age_rating_minimal"] in ("SU", "7+")
    ):
        print(f"[checker] kategori enrichment: SAFE -> {kategori_suspect} (rating tetap {_rf})")
        final_decision["kategori_final"] = kategori_suspect

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
            print(f"[checker] Qdrant unavailable, using static legal fallback: {e}")
    else:
        print("[checker] QDRANT_URL not set, using static legal fallback")

    public_status = "NEEDS_REVIEW" if final_decision.get("rating_final") == "UNRATED" else "COMPLETED"

    # Saran untuk orang tua sesuai rating final (dipilih acak dari tabel parent_advice).
    parent_advice = await get_random_parent_advice(
        final_decision.get("rating_final", "SU"), session
    )

    return {
        "target_url": target_url,
        "status": public_status,
        "engine_decision": {
            "kategori_final": final_decision.get("kategori_final", "SAFE"),
            "rating_final": final_decision.get("rating_final", "SU"),
            "reason_ai": final_decision.get("reason_final", ""),
            "is_vetoed_by_backend": False,
        },
        "parent_advice": parent_advice,
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
                "predicted_rating": mock_text_ai["predicted_rating"],
                "confidence_score": mock_text_ai["confidence_score"],
                "reasoning_category": mock_text_ai["reason"],
            },
            "tim3_visual": {
                "kategori_ai": mock_visual_ai["kategori"],
                "predicted_rating": mock_visual_ai["predicted_rating"],
                "confidence_score": mock_visual_ai["confidence_score"],
                "reasoning_category": mock_visual_ai["reason"],
            },
        },
    }
