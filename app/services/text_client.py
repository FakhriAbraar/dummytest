"""Tim 1 Text classifier client.

Tim 1 menyediakan model SFT (Supervised Fine-Tuned) sendiri yang di-serve via
RunPod, OpenAI-compatible (`/v1/chat/completions`). Modul ini adalah
satu-satunya tempat yang "menembak" endpoint tersebut, dipakai oleh:

- `check_engine.py`  (Public Content Checker — `/api/pad/check/verify`)
- `real_ml.py`       (upload — `/api/pad/check/upload`)
- `nodes.py`         (gatekeeper pipeline crawler)

Konfigurasi via .env (semua opsional, default sudah menunjuk ke endpoint Tim 1):
    TEXT_API_BASE_URL     default https://va4o83dml7dsfh-8002.proxy.runpod.net/v1
    TEXT_API_MODEL        default padsft
    TEXT_API_KEY          default EMPTY (proxy tidak butuh auth)
    TEXT_MAX_TOKENS       default 300
    TEXT_MAX_RETRIES      default 3
    TEXT_DEFAULT_CONFIDENCE default 0.75
"""
from __future__ import annotations

import asyncio
import json
import os
import re

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

TEXT_API_BASE_URL = os.getenv(
    "TEXT_API_BASE_URL", "https://va4o83dml7dsfh-8002.proxy.runpod.net/v1"
)
TEXT_API_MODEL = os.getenv("TEXT_API_MODEL", "padsft")
TEXT_API_KEY = os.getenv("TEXT_API_KEY", "EMPTY")
TEXT_MAX_TOKENS = int(os.getenv("TEXT_MAX_TOKENS", "300"))
TEXT_MAX_RETRIES = int(os.getenv("TEXT_MAX_RETRIES", "3"))
TEXT_DEFAULT_CONFIDENCE = float(os.getenv("TEXT_DEFAULT_CONFIDENCE", "0.75"))

VALID_RATINGS = {"SU", "7+", "13+", "17+", "PRC"}

# Normalisasi rating: model bisa balas dalam berbagai bentuk/typo.
_RATING_ALIASES = {
    "SU": "SU", "SEMUA UMUR": "SU", "ALL": "SU", "G": "SU", "3+": "SU", "0+": "SU",
    "7+": "7+", "7": "7+",
    "13+": "13+", "13": "13+",
    "17+": "17+", "17": "17+", "15+": "17+", "16+": "17+",
    "PRC": "PRC", "RPC": "PRC", "18+": "PRC", "21+": "PRC",
    "R": "PRC", "DEWASA": "PRC", "ADULT": "PRC", "RESTRICTED": "PRC",
    "PROHIBITED": "PRC", "PROHIBITED CLASSIFICATION": "PRC",
}

ALLOWED_CATEGORIES = [
    "Netral", "Violence", "Sexual", "Harassment", "Hateful_Content", "Self_Harm",
]

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(base_url=TEXT_API_BASE_URL, api_key=TEXT_API_KEY)
    return _client


def _normalize_rating(val: object) -> str | None:
    if val is None:
        return None
    key = str(val).strip().upper()
    if key in _RATING_ALIASES:
        return _RATING_ALIASES[key]
    if key in VALID_RATINGS:
        return key
    # Cari token rating yang muncul di dalam string bebas.
    for tok in ("PRC", "17+", "13+", "7+", "SU"):
        if tok in key:
            return tok
    return None


def _normalize_kategori(val: object) -> str:
    if val is None:
        return "Netral"
    raw = str(val).strip()
    # Normalisasi variasi umum dari output model
    mapping = {
        "netral": "Netral",
        "safe": "Netral",
        "violence": "Violence",
        "sexual": "Sexual",
        "harassment": "Harassment",
        "harrasment": "Harassment",
        "hateful_content": "Hateful_Content",
        "hateful content": "Hateful_Content",
        "self_harm": "Self_Harm",
        "self-harm": "Self_Harm",
        "selfharm": "Self_Harm",
    }
    normalized = mapping.get(raw.lower())
    if normalized:
        return normalized
    # Jika tidak cocok, kembalikan as-is (mungkin model baru mengembalikan variant lain)
    return raw if raw else "Netral"


def _coerce_confidence(val: object, default: float) -> float:
    try:
        f = float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if f > 1.0:  # kadang model balas dalam persen (mis. 85)
        f = f / 100.0
    return max(0.0, min(1.0, f))


def parse_text_response(raw: str) -> dict:
    """Ekstrak {kategori, predicted_rating, confidence_score, reason} dari output
    model Tim 1. Tahan terhadap format "Rating: ...\nKategori: ...\nPenjelasan: ..."
    maupun JSON biasa.
    """
    text = (raw or "").strip()

    # --- Coba parse format plain text "Rating: ...\nKategori: ...\nPenjelasan: ..." ---
    rating_match = re.search(r"Rating\s*:\s*(.+)", text, re.IGNORECASE)
    kategori_match = re.search(r"Kategori\s*:\s*(.+)", text, re.IGNORECASE)
    penjelasan_match = re.search(r"Penjelasan\s*:\s*(.+)", text, re.IGNORECASE | re.DOTALL)

    if rating_match and kategori_match:
        rating_raw = rating_match.group(1).strip()
        kategori_raw = kategori_match.group(1).strip()
        reason_raw = penjelasan_match.group(1).strip() if penjelasan_match else ""

        rating = _normalize_rating(rating_raw) or "SU"
        kategori = _normalize_kategori(kategori_raw)

        # Enforce rules: non-Netral categories → PRC
        if kategori != "Netral" and rating != "PRC":
            rating = "PRC"

        return {
            "kategori": kategori,
            "predicted_rating": rating,
            "confidence_score": TEXT_DEFAULT_CONFIDENCE,
            "reason": reason_raw[:600] or "Klasifikasi teks oleh model Tim 1.",
        }

    # --- Fallback: coba parse sebagai JSON ---
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*", "", text).strip()
        if text.endswith("```"):
            text = text[:-3].strip()

    data: dict = {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            data = parsed
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict):
                    data = parsed
            except Exception:
                data = {}

    def grab(*keys: str) -> object:
        for k in keys:
            for dk, dv in data.items():
                if dk.lower() == k and dv not in (None, ""):
                    return dv
        for k in keys:
            m = re.search(rf'"{k}"\s*:\s*"([^"]*)', text, re.IGNORECASE)
            if m and m.group(1).strip():
                return m.group(1).strip()
            m2 = re.search(rf'"{k}"\s*:\s*([0-9]*\.?[0-9]+)', text, re.IGNORECASE)
            if m2:
                return m2.group(1)
        return None

    kategori_raw = grab("kategori", "category", "label", "kelas")
    rating_raw = grab("predicted_rating", "rating", "age_rating")
    reason = grab("reason", "alasan", "penjelasan", "description", "penyebab")
    conf_raw = grab("confidence_score", "confidence", "skor", "score")

    kategori = _normalize_kategori(kategori_raw)
    rating = _normalize_rating(rating_raw) or "SU"
    reason_str = str(reason).strip()[:600] if reason else ""
    confidence = _coerce_confidence(conf_raw, TEXT_DEFAULT_CONFIDENCE)

    # Enforce rules: non-Netral categories → PRC
    if kategori != "Netral" and rating != "PRC":
        rating = "PRC"

    return {
        "kategori": kategori,
        "predicted_rating": rating,
        "confidence_score": confidence,
        "reason": reason_str or "Klasifikasi teks oleh model Tim 1.",
    }


def _build_prompt(text_content: str) -> str:
    """Build the system prompt for Tim 1's PAD SFT model."""
    truncated = (text_content or "").strip()[:3000] or "(tidak ada teks)"
    return f"""Anda adalah sistem klasifikasi konten PAD (Perlindungan Anak di Ruang Digital).

Tugas:
Analisis teks yang diberikan, lalu tentukan kategori konten, klasifikasi rating, dan penjelasan analisisnya.

Kategori yang tersedia:
- Netral
- Violence
- Sexual
- Harassment
- Hateful_Content
- Self_Harm

Rating yang tersedia:
- SU
- 7+
- 13+
- 17+
- PRC (Prohibited Classification)

Aturan:
- Violence, Sexual, Harassment, Hateful_Content, dan Self_Harm selalu menggunakan rating PRC (Prohibited).
- Hanya kategori Netral yang dapat menggunakan rating SU, 7+, 13+, atau 17+.
- Klasifikasi harus berdasarkan informasi yang secara eksplisit terdapat dalam teks.
- Penjelasan wajib mengutip frasa atau kalimat yang mendukung hasil klasifikasi.

Teks Input:
\"{truncated}\"

Format Output:

Rating: ...

Kategori: ...

Penjelasan: ..."""


async def classify_text(text_content: str = "") -> dict:
    """Klasifikasi teks via endpoint Tim 1 (padsft).

    Mengembalikan dict ternormalisasi {kategori, predicted_rating,
    confidence_score, reason}.
    """
    prompt = _build_prompt(text_content)

    print(f"[text] tim1 -> {TEXT_API_MODEL} text_len={len(text_content)}")

    client = _get_client()
    for attempt in range(TEXT_MAX_RETRIES):
        try:
            resp = await client.chat.completions.create(
                model=TEXT_API_MODEL,
                messages=[{"role": "user", "content": prompt}],  # type: ignore[arg-type]
                temperature=0.0,
                max_tokens=TEXT_MAX_TOKENS,
            )
            raw = resp.choices[0].message.content or ""
            print(f"[text] tim1 raw: {raw[:200]!r}")
            return parse_text_response(raw)
        except Exception as e:  # noqa: BLE001
            print(f"[text] tim1 error (attempt {attempt + 1}/{TEXT_MAX_RETRIES}): {e}")
            if attempt < TEXT_MAX_RETRIES - 1:
                await asyncio.sleep(2 * (attempt + 1))

    return {
        "kategori": "Netral",
        "predicted_rating": "SU",
        "confidence_score": 0.0,
        "reason": "Model teks Tim 1 gagal merespons.",
    }
