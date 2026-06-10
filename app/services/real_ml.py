"""
Real ML module — OpenRouter LLM calls untuk Tim 1 (Text) dan Tim 3 (Visual).
Falls back ke dummy jika OPENROUTER_API_KEY tidak dikonfigurasi.
"""
from __future__ import annotations

import os
import json
import re
import asyncio

from dotenv import load_dotenv
from openai import AsyncOpenAI, RateLimitError, APIError

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL_TIM1 = os.getenv("OPENROUTER_MODEL_TIM1", "mistralai/ministral-3b-2512")
MODEL_TIM3 = os.getenv("OPENROUTER_MODEL_TIM3", "openai/gpt-4o-mini")

VALID_CATEGORIES_TEXT = {
    "Cyberbullying", "HateSpeech", "Perjudian", "Scam",
    "Pornografi_Teks", "Kekerasan_Teks", "Substansi_Terlarang", "Perselingkuhan", "SAFE",
}

VALID_CATEGORIES_VISUAL = {
    "Pornography_Keras", "Pornography_Ringan", "Animasi_Ringan",
    "Drug", "Addictive Substances", "Violence", "Weapon_Ringan", "SAFE",
}

VALID_RATINGS = {"SU", "7+", "13+", "17+", "PRC"}

SYSTEM_TIM1 = (
    "Kamu adalah AI Klasifikator Konten Digital untuk sistem Perlindungan Anak Digital (PAD) Indonesia. "
    "Analisis konten teks dari media sosial dan tentukan apakah berpotensi membahayakan anak-anak.\n\n"
    "Kategori valid: Netral, Violence, Sexual, Harrasment, Hateful_Content, Self-Harm. \n "
    "Rating valid: SU, 7+, 13+, 17+, PRC.\n\n"
    "Respond HANYA dengan JSON: "
    "{\"kategori\": \"<kategori>\", \"predicted_rating\": \"<rating>\", "
    "\"confidence_score\": <0.0-1.0>, \"reason\": \"<alasan singkat dalam bahasa Indonesia>\"}"
)

SYSTEM_TIM3 = (
    "Kamu adalah AI Visual Content Classifier untuk sistem Perlindungan Anak Digital (PAD) Indonesia. "
    "Analisis konten visual (gambar/video) dari media sosial dan tentukan apakah berpotensi membahayakan anak-anak.\n\n"
    "Kategori valid: Human_Interaction, Medicine, Sport, Education, Miliitary, Animation, Medical, Toy, "
    "Tactical_Miliitary, Action, Violent_Sport, Complex_Interactions, Suggestive, Invasive_Medical, Weapon, Violence, Addictive_Substances, Pornography, Terrorism, SelfHarm, Sadistic_Violence, Drug.\n"
    "Rating valid: SU, 7+, 13+, 17+, PRC.\n\n"
    "Respond HANYA dengan JSON: "
    "{\"kategori\": \"<kategori>\", \"predicted_rating\": \"<rating>\", "
    "\"confidence_score\": <0.0-1.0>, \"reason\": \"<alasan singkat dalam bahasa Indonesia>\"}"
)


def _get_or_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )


def _extract_json_from_response(raw: str) -> dict:
    cleaned = raw.strip()
    for prefix in ("```json", "```"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
    return {}


def _parse_retry_after(exc: Exception) -> float | None:
    """Ekstrak Retry-After dari body error OpenRouter jika tersedia."""
    try:
        body = getattr(exc, "body", None) or {}
        meta = body.get("error", {}).get("metadata", {}) if isinstance(body, dict) else {}
        secs = meta.get("retry_after_seconds")
        if secs is not None:
            return float(secs) + 2
    except Exception:
        pass
    return None


def _sanitize_result(result: dict, valid_categories: set, raw_fallback: str) -> dict:
    result.setdefault("kategori", "SAFE")
    result.setdefault("predicted_rating", "SU")
    result.setdefault("confidence_score", 0.5)
    result.setdefault("reason", raw_fallback[:200])

    if result["kategori"] not in valid_categories:
        result["kategori"] = "SAFE"
    if result["predicted_rating"] not in VALID_RATINGS:
        result["predicted_rating"] = "SU"

    return result


async def call_llm_tim1(url: str = "", text: str = "") -> dict:
    # Tim 1 (Text) selalu ditembak ke endpoint model SFT Tim 1 (padsft di RunPod),
    # tidak lagi ke OpenRouter. Lihat app/services/text_client.py.
    from app.services.text_client import classify_text

    return await classify_text(text)


async def call_llm_tim3(
    url: str = "",
    content_type: str = "text",
    text: str = "",
    img_urls: list | None = None,
) -> dict:
    # Tim 3 (Visual) selalu ditembak ke endpoint model visual Tim 3 (pad3_model),
    # tidak lagi ke OpenRouter. img_urls untuk upload sudah berupa data-URI base64.
    from app.services.visual_client import classify_visual

    context = f"{text} {url}".strip()
    return await classify_visual(context, img_urls, content_type=content_type)
