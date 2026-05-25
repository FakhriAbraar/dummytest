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
MODEL_TIM1 = os.getenv("OPENROUTER_MODEL_TIM1", "meta-llama/llama-3.1-70b-instruct")
MODEL_TIM3 = os.getenv("OPENROUTER_MODEL_TIM3", "google/gemma-3-4b-it")

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
    "Kategori valid: SAFE, Cyberbullying, HateSpeech, Perjudian, Scam, "
    "Pornografi_Teks, Kekerasan_Teks, Substansi_Terlarang, Perselingkuhan.\n"
    "Rating valid: SU, 7+, 13+, 17+, PRC.\n\n"
    "Respond HANYA dengan JSON: "
    "{\"kategori\": \"<kategori>\", \"predicted_rating\": \"<rating>\", "
    "\"confidence_score\": <0.0-1.0>, \"reason\": \"<alasan singkat dalam bahasa Indonesia>\"}"
)

SYSTEM_TIM3 = (
    "Kamu adalah AI Visual Content Classifier untuk sistem Perlindungan Anak Digital (PAD) Indonesia. "
    "Analisis konten visual (gambar/video) dari media sosial dan tentukan apakah berpotensi membahayakan anak-anak.\n\n"
    "Kategori valid: SAFE, Pornography_Keras, Pornography_Ringan, Animasi_Ringan, "
    "Drug, Addictive Substances, Violence, Weapon_Ringan.\n"
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
    if not OPENROUTER_API_KEY:
        print("[!] OPENROUTER_API_KEY tidak dikonfigurasi — Tim1 menggunakan dummy.")
        from app.services.dummy_ml import call_dummy_tim1
        return await call_dummy_tim1(url, text)

    client = _get_or_client()
    user_prompt = f"URL: {url}\n\nKonten Teks:\n{text[:3000] if text else '(tidak ada teks)'}"

    for attempt in range(3):
        try:
            resp = await client.chat.completions.create(
                model=MODEL_TIM1,
                messages=[
                    {"role": "system", "content": SYSTEM_TIM1},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=300,
            )
            raw = resp.choices[0].message.content or ""
            result = _extract_json_from_response(raw)
            if result:
                return _sanitize_result(result, VALID_CATEGORIES_TEXT, raw)

        except RateLimitError as e:
            wait = _parse_retry_after(e) or (35 * (attempt + 1))
            print(f"[!] Tim1 RateLimit (attempt {attempt + 1}/3) — retry in {wait}s")
            if attempt < 2:
                await asyncio.sleep(wait)
        except APIError as e:
            print(f"[!] Tim1 APIError (attempt {attempt + 1}/3): {e}")
            if attempt < 2:
                await asyncio.sleep(5)
        except Exception as e:
            print(f"[!] Tim1 unexpected error: {e}")
            break

    return {
        "kategori": "SAFE",
        "predicted_rating": "SU",
        "confidence_score": 0.3,
        "reason": "LLM Tim1 gagal merespons setelah 3 percobaan.",
    }


async def call_llm_tim3(
    url: str = "",
    content_type: str = "text",
    text: str = "",
    img_urls: list | None = None,
) -> dict:
    if not OPENROUTER_API_KEY:
        print("[!] OPENROUTER_API_KEY tidak dikonfigurasi — Tim3 menggunakan dummy.")
        from app.services.dummy_ml import call_dummy_tim3
        return await call_dummy_tim3(url, content_type, text, img_urls)

    client = _get_or_client()
    text_prompt = (
        f"URL: {url}\nTipe Konten: {content_type}\n"
        f"Keterangan Teks: {text[:2000] if text else '(tidak ada)'}"
    )

    # Build message content — vision model jika ada gambar
    if img_urls:
        user_content = []
        for img_url in img_urls[:2]:
            user_content.append({"type": "image_url", "image_url": {"url": img_url}})
        user_content.append({"type": "text", "text": text_prompt})
        model_to_use = MODEL_TIM3
    else:
        user_content = text_prompt
        model_to_use = MODEL_TIM1  # Text-only fallback untuk Tim3 tanpa gambar

    for attempt in range(3):
        try:
            resp = await client.chat.completions.create(
                model=model_to_use,
                messages=[
                    {"role": "system", "content": SYSTEM_TIM3},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.1,
                max_tokens=300,
            )
            raw = resp.choices[0].message.content or ""
            result = _extract_json_from_response(raw)
            if result:
                return _sanitize_result(result, VALID_CATEGORIES_VISUAL, raw)

        except RateLimitError as e:
            wait = _parse_retry_after(e) or (35 * (attempt + 1))
            print(f"[!] Tim3 RateLimit (attempt {attempt + 1}/3) — retry in {wait}s")
            if attempt < 2:
                await asyncio.sleep(wait)
        except APIError as e:
            print(f"[!] Tim3 APIError (attempt {attempt + 1}/3): {e}")
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
        except Exception as e:
            print(f"[!] Tim3 unexpected error: {e}")
            break

    return {
        "kategori": "SAFE",
        "predicted_rating": "SU",
        "confidence_score": 0.3,
        "reason": "LLM Tim3 gagal merespons setelah 3 percobaan.",
    }
