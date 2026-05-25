from __future__ import annotations

import asyncio
import base64
import mimetypes
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.sql import get_db_session
from app.services.check_engine import run_public_checking_pipeline
from app.services.classification import get_igrs_rule_by_kategori
from app.services.real_ml import call_llm_tim1, call_llm_tim3
from app.services.resolver import resolve_ai_conflict

router = APIRouter()


class CheckRequest(BaseModel):
    url: str


class EngineDecision(BaseModel):
    kategori_final: str
    rating_final: str
    reason_ai: str
    is_vetoed_by_backend: bool = False


class LegalContext(BaseModel):
    bunyi_pasal_qdrant: str


class ClassificationDetail(BaseModel):
    kategori_ai: str
    confidence_score: float
    reasoning_category: str


class Classifications(BaseModel):
    tim1_text: ClassificationDetail
    tim3_visual: ClassificationDetail


class ContentMeta(BaseModel):
    platform: str = ""
    username: str = ""
    caption: str = ""
    thumbnail_url: str = ""


class CheckResponse(BaseModel):
    target_url: str
    status: str
    engine_decision: EngineDecision
    legal_context: LegalContext
    content_meta: ContentMeta | None = None
    classifications: Classifications | None = None

@router.post("/verify", response_model=CheckResponse)
async def public_checking_endpoint(
    request: CheckRequest,
    session: AsyncSession = Depends(get_db_session)
):
    try:
        result = await run_public_checking_pipeline(request.url, session)
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ─── Upload-based content check (image / video) ────────────────────────────
# Selain URL, user juga bisa upload file (foto/video) ke endpoint ini.
# File akan dijalankan ke Tim 1 + Tim 3 (dummy/real model) untuk klasifikasi.

_IMAGE_MIME_PREFIX = "image/"
_VIDEO_MIME_PREFIX = "video/"
_MAX_BYTES_FOR_BASE64 = 8 * 1024 * 1024  # 8 MB safety cap untuk data URI


def _build_data_uri(content: bytes, mime: str) -> str:
    """Encode file bytes → 'data:{mime};base64,{...}' URI yang bisa langsung
    dipass ke OpenRouter sebagai image_url.url.
    """
    b64 = base64.b64encode(content).decode("ascii")
    return f"data:{mime};base64,{b64}"


@router.post("/upload", response_model=CheckResponse)
async def check_upload_endpoint(
    file: UploadFile = File(..., description="Foto atau video yang mau diperiksa"),
    url: str = Form("", description="Opsional: URL asal konten untuk konteks tambahan"),
    session: AsyncSession = Depends(get_db_session),  # noqa: ARG001 (dipakai untuk parity dengan /verify, IGRS rule lookup)
):
    """Klasifikasi konten berdasarkan FILE upload (foto/video), bukan URL.

    - Image (jpg/png/webp/dst.): di-base64-encode → dipass ke Tim 3 Visual.
    - Video (mp4/webm/dst.): tidak dikirim ke Tim 3 (model visual tidak baca video),
      Tim 3 fallback ke text-only mode dengan filename sebagai konteks.
    - Tim 1 selalu dipanggil dengan filename + URL opsional sebagai input teks.
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="File kosong.")
    if len(raw) > _MAX_BYTES_FOR_BASE64:
        raise HTTPException(
            status_code=413,
            detail=f"File terlalu besar untuk klasifikasi inline ({len(raw)} bytes > {_MAX_BYTES_FOR_BASE64}).",
        )

    filename = file.filename or "uploaded_file"
    mime = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"

    is_image = mime.startswith(_IMAGE_MIME_PREFIX)
    is_video = mime.startswith(_VIDEO_MIME_PREFIX)
    if not (is_image or is_video):
        raise HTTPException(
            status_code=400,
            detail=f"MIME type '{mime}' tidak didukung. Hanya foto atau video.",
        )

    content_type = "image" if is_image else "video"
    target_url = url or f"upload://{filename}"

    # Teks input untuk Tim 1: filename + URL kalau ada (model dummy pakai keyword matching)
    text_for_tim1 = f"{filename} {url}".strip()

    # Tim 3 visual: data URI untuk image, list kosong untuk video
    img_urls: list[str] = []
    if is_image:
        img_urls.append(_build_data_uri(raw, mime))

    # Panggil Tim 1 + Tim 3 paralel (sama seperti gatekeeper di nodes.py)
    tim1_result, tim3_result = await asyncio.gather(
        call_llm_tim1(target_url, text_for_tim1),
        call_llm_tim3(target_url, content_type, text_for_tim1, img_urls),
    )

    # Tentukan kategori kandidat (mirror logic gatekeeper)
    if tim1_result["kategori"] == "SAFE" and tim3_result["kategori"] == "SAFE":
        kategori_suspect = "SAFE"
    elif tim1_result["kategori"] == "SAFE":
        kategori_suspect = str(tim3_result["kategori"])
    elif tim3_result["kategori"] == "SAFE":
        kategori_suspect = str(tim1_result["kategori"])
    else:
        kategori_suspect = (
            str(tim3_result["kategori"])
            if tim3_result["confidence_score"] > tim1_result["confidence_score"]
            else str(tim1_result["kategori"])
        )

    rule_suspect = await get_igrs_rule_by_kategori(kategori_suspect, session)
    igrs_rule: dict[str, Any] = {
        "dominant_modality": rule_suspect.dominant_modality if rule_suspect else "EQUAL",
        "age_rating_minimal": rule_suspect.age_rating_minimal if rule_suspect else "SU",
    }

    final_decision = resolve_ai_conflict(
        text_result=tim1_result,
        visual_result=tim3_result,
        igrs_rule=igrs_rule,
    )

    public_status = (
        "NEEDS_REVIEW"
        if final_decision.get("rating_final") == "UNRATED"
        else "COMPLETED"
    )

    # Legal context: kosong (tidak panggil Qdrant untuk upload-mode demi kecepatan).
    # Frontend tetap menampilkan field ini, jadi kasih placeholder informatif.
    legal_context = (
        f"Klasifikasi berbasis file upload ({content_type}, {len(raw)} bytes). "
        "Untuk konteks hukum lengkap, gunakan endpoint /check/verify dengan URL konten."
    )

    # Untuk image upload, kirim balik data URI sebagai thumbnail agar frontend bisa preview.
    # Video tidak perlu (terlalu berat untuk inline).
    thumbnail_for_response = img_urls[0] if img_urls else ""

    return {
        "target_url": target_url,
        "status": public_status,
        "engine_decision": {
            "kategori_final": final_decision.get("kategori_final", "SAFE"),
            "rating_final": final_decision.get("rating_final", "SU"),
            "reason_ai": final_decision.get("reason_final", ""),
            "is_vetoed_by_backend": False,
        },
        "legal_context": {"bunyi_pasal_qdrant": legal_context},
        "content_meta": {
            "platform": "upload",
            "username": "",
            "caption": filename,
            "thumbnail_url": thumbnail_for_response,
        },
        "classifications": {
            "tim1_text": {
                "kategori_ai": tim1_result["kategori"],
                "confidence_score": tim1_result["confidence_score"],
                "reasoning_category": tim1_result["reason"],
            },
            "tim3_visual": {
                "kategori_ai": tim3_result["kategori"],
                "confidence_score": tim3_result["confidence_score"],
                "reasoning_category": tim3_result["reason"],
            },
        },
    }