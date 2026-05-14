from __future__ import annotations

import asyncio
import os
from typing import Any

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession

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


async def run_public_checking_pipeline(url: str, session: AsyncSession) -> dict[str, Any]:
    mock_visual_ai: dict[str, Any] = {
        "predicted_rating": "SU", "kategori": "SAFE",
        "confidence_score": 0.99, "reason": "Konten pemandangan alam."
    }
    mock_text_ai: dict[str, Any] = {
        "predicted_rating": "SU", "kategori": "SAFE",
        "confidence_score": 0.99, "reason": "Teks normal."
    }

    if "porn" in url.lower():
        mock_visual_ai = {
            "predicted_rating": "17+", "kategori": "Pornography_Keras",
            "confidence_score": 0.95, "reason": "Menampilkan adegan seksual eksplisit."
        }
    elif "conflict" in url.lower():
        mock_visual_ai = {"predicted_rating": "18+", "kategori": "Violence", "confidence_score": 0.90, "reason": "Darah di mana-mana."}
        mock_text_ai = {"predicted_rating": "SU", "kategori": "SAFE", "confidence_score": 0.95, "reason": "Teks aman."}

    visual_conf: float = float(mock_visual_ai["confidence_score"])
    text_conf: float = float(mock_text_ai["confidence_score"])

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
            doc_title = payload.get("document_title", "Dokumen Hukum")
            pasal = payload.get("pasal", "")
            ayat = payload.get("ayat", "")
            konten = payload.get("konten", "Konten pasal tidak ditemukan.")

            referensi_hukum = str(doc_title)
            if pasal:
                referensi_hukum += f" - {pasal}"
            if ayat:
                referensi_hukum += f" Ayat {ayat}"
            qdrant_context = f"[{referensi_hukum}] {konten}"
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
