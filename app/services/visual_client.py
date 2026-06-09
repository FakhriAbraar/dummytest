"""Tim 3 Visual classifier client.

Tim 3 menyediakan model visual (VLM) sendiri yang di-serve via vLLM di balik
proxy RunPod, OpenAI-compatible (`/v1/chat/completions`). Modul ini adalah
satu-satunya tempat yang "menembak" endpoint tersebut, dipakai oleh:

- `check_engine.py`  (Public Content Checker — `/api/pad/check/verify`)
- `real_ml.py`       (upload foto/video — `/api/pad/check/upload`)
- `nodes.py`         (gatekeeper pipeline crawler)

Konfigurasi via .env (semua opsional, default sudah menunjuk ke endpoint Tim 3):
    VISUAL_API_BASE_URL   default https://va4o83dml7dsfh-8001.proxy.runpod.net/v1
    VISUAL_API_MODEL      default pad3_model
    VISUAL_API_KEY        default EMPTY (proxy tidak butuh auth)
    VISUAL_MAX_IMAGES     default 2   (jaga budget context vLLM max_model_len=2048)
    VISUAL_MAX_TOKENS     default 400
    VISUAL_DEFAULT_CONFIDENCE default 0.75

Catatan: model di-fine-tune dan output JSON-nya longgar (kadang pakai key
`rating`/`penyebab`/`description`, kadang terpotong karena `finish_reason=length`).
`parse_visual_response()` sengaja dibuat toleran terhadap semua varian itu.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

VISUAL_API_BASE_URL = os.getenv(
    "VISUAL_API_BASE_URL", "https://va4o83dml7dsfh-8001.proxy.runpod.net/v1"
)
VISUAL_API_MODEL = os.getenv("VISUAL_API_MODEL", "pad3_model")
VISUAL_API_KEY = os.getenv("VISUAL_API_KEY", "EMPTY")
VISUAL_MAX_IMAGES = int(os.getenv("VISUAL_MAX_IMAGES", "2"))
VISUAL_MAX_TOKENS = int(os.getenv("VISUAL_MAX_TOKENS", "400"))
VISUAL_MAX_RETRIES = int(os.getenv("VISUAL_MAX_RETRIES", "2"))
VISUAL_DEFAULT_CONFIDENCE = float(os.getenv("VISUAL_DEFAULT_CONFIDENCE", "0.75"))
# pad3_model context-nya kecil (max_model_len=2048). Gambar full-res bisa makan
# >2000 token sendirian -> error 400. Downscale dulu ke sisi maksimal ini (px).
VISUAL_MAX_IMAGE_DIM = int(os.getenv("VISUAL_MAX_IMAGE_DIM", "512"))

VALID_RATINGS = {"SU", "7+", "13+", "17+", "PRC", "UNRATED"}

# Normalisasi rating: model bisa balas dalam berbagai bentuk/typo. Skala dummysaran
# (3+/15+/18+) ikut dipetakan ke skala sistem (SU/7+/13+/17+/PRC).
_RATING_ALIASES = {
    "SU": "SU", "SEMUA UMUR": "SU", "ALL": "SU", "G": "SU", "3+": "SU", "0+": "SU",
    "7+": "7+", "7": "7+",
    "13+": "13+", "13": "13+",
    "17+": "17+", "17": "17+", "15+": "17+", "16+": "17+",
    "PRC": "PRC", "RPC": "PRC", "18+": "PRC", "21+": "PRC",
    "R": "PRC", "DEWASA": "PRC", "ADULT": "PRC", "RESTRICTED": "PRC",
    "UNRATED": "UNRATED",
}

ALLOWED_RATINGS = [
    '13+', '17+', '7+', 'PRC', 'Semua Umur', 'Unrated'
]
ALLOWED_CATEGORIES = [
    'Action', 'Addictive Substances', 'Animation', 'Complex Interactions',
    'Drug', 'Education', 'Invasive_Medical', 'Medical', 'Medicine',
    'Military', 'Pornography', 'SelfHarm', 'Sport', 'Suggestive',
    'Tactical_Military', 'Terrorism', 'Toy', 'Uncategorized',
    'Violence', 'Violent_Sport', 'Weapon'
]

UNCATEGORIZED_LABEL = 'Uncategorized'
UNRATED_LABEL = 'Unrated'

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(base_url=VISUAL_API_BASE_URL, api_key=VISUAL_API_KEY)
    return _client


def _bytes_to_jpeg_data_uri(raw: bytes, max_dim: int) -> str:
    from PIL import Image  # noqa: PLC0415

    img = Image.open(io.BytesIO(raw))
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((max_dim, max_dim))  # in-place, jaga rasio aspek
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _fetch_bytes(url: str) -> bytes:
    import httpx  # noqa: PLC0415

    with httpx.Client(timeout=15.0, follow_redirects=True) as c:
        resp = c.get(url)
        resp.raise_for_status()
        return resp.content


def _downscale_image(url: str, max_dim: int) -> str:
    """Kembalikan data-URI JPEG kecil (<= max_dim px) dari data-URI/URL http.

    Penting untuk pad3_model yang context-nya 2048 token: tanpa ini, 1 gambar
    full-res saja bisa menembus limit dan bikin error 400. Gagal proses ->
    kembalikan url asli (biar tetap dicoba, tidak menghentikan klasifikasi).
    """
    try:
        if url.startswith("data:"):
            _, _, b64data = url.partition(",")
            raw = base64.b64decode(b64data)
        elif url.startswith("http"):
            raw = _fetch_bytes(url)
        else:
            return url
        return _bytes_to_jpeg_data_uri(raw, max_dim)
    except Exception as e:  # noqa: BLE001
        print(f"[visual] downscale gagal ({url[:48]}...): {e}")
        return url


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


def _coerce_confidence(val: object, default: float) -> float:
    try:
        f = float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if f > 1.0:  # kadang model balas dalam persen (mis. 85)
        f = f / 100.0
    return max(0.0, min(1.0, f))


def parse_visual_response(raw: str) -> dict:
    """Ekstrak {kategori, predicted_rating, confidence_score, reason} dari output
    model yang longgar. Tahan terhadap JSON terpotong (value tanpa closing quote).
    """
    text = (raw or "").strip()
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
        # Fallback regex — menangkap value walau JSON terpotong (tanpa closing ").
        for k in keys:
            m = re.search(rf'"{k}"\s*:\s*"([^"]*)', text, re.IGNORECASE)
            if m and m.group(1).strip():
                return m.group(1).strip()
            m2 = re.search(rf'"{k}"\s*:\s*([0-9]*\.?[0-9]+)', text, re.IGNORECASE)
            if m2:
                return m2.group(1)
        return None

    kategori = grab("kategori", "category", "label", "kelas")
    rating_raw = grab("predicted_rating", "rating", "age_rating", "umur", "usia")
    reason = grab(
        "reason", "alasan", "penyebab", "description", "deskripsi", "penjelasan",
        "penilaian", "keterangan", "analisis", "catatan",
    )
    conf_raw = grab("confidence_score", "confidence", "skor", "score")

    kategori_str = str(kategori).strip()[:100] if kategori else "SAFE"
    rating = _normalize_rating(rating_raw) or "SU"
    reason_str = str(reason).strip()[:600] if reason else ""
    confidence = _coerce_confidence(conf_raw, VISUAL_DEFAULT_CONFIDENCE)

    # Model fine-tuned ini kadang menaruh kalimat deskripsi di field `kategori`.
    # Jika begitu (kategori seperti kalimat) dan reason kosong, pakai sebagai reason.
    if not reason_str and len(kategori_str.split()) > 5:
        reason_str = kategori_str

    return {
        "kategori": kategori_str or "SAFE",
        "predicted_rating": rating,
        "confidence_score": confidence,
        "reason": reason_str or "Klasifikasi visual oleh model Tim 3.",
    }


def _build_prompt(context_text: str, content_type: str, has_image: bool) -> str:
    instruction = f"""Tugas: Analisis gambar yang diberikan, lalu tentukan kategori/domain, klasifikasi rating usia, dan deskripsi analisisnya.

Aturan Output:
- Wajib merespons hanya dalam format JSON valid tanpa teks tambahan di luar JSON.
- Jangan gunakan markdown block (jangan gunakan ```json).
- "category" harus memilih dari: {ALLOWED_CATEGORIES}
- "rating" harus memilih dari: {ALLOWED_RATINGS}
- Jika konten berada di luar domain atau tidak termasuk dalam kategori yang diizinkan, gunakan category "{UNCATEGORIZED_LABEL}" dan rating "{UNRATED_LABEL}".

Format Output:
{{
  "category": "...",
  "rating": "...",
  "description": "..."
}}""".strip()

    if has_image:
        return instruction
        
    ctx = (context_text or "").strip()[:150] or "(tidak ada)"
    return f"{instruction}\n\n[INFO TAMBAHAN]\nBila gambar tidak tersedia, analisis berdasarkan konteks berikut:\nTipe konten: {content_type}\nKonteks teks: {ctx}".strip()


async def _classify_single_batch(
    context_text: str,
    images_chunk: list[str],
    content_type: str,
) -> dict:
    has_img = len(images_chunk) > 0
    prompt = _build_prompt(context_text, content_type, has_img)

    if images_chunk:
        user_content: list[dict] = [
            {"type": "image_url", "image_url": {"url": u}} for u in images_chunk
        ]
        user_content.append({"type": "text", "text": prompt})
        messages: list = [{"role": "user", "content": user_content}]
    else:
        messages = [{"role": "user", "content": prompt}]

    print(f"[visual] tim3 -> {VISUAL_API_MODEL} images={len(images_chunk)}")

    client = _get_client()
    for attempt in range(VISUAL_MAX_RETRIES):
        try:
            resp = await client.chat.completions.create(
                model=VISUAL_API_MODEL,
                messages=messages,  # type: ignore[arg-type]
                temperature=0.0,
                max_tokens=VISUAL_MAX_TOKENS,
            )
            raw = resp.choices[0].message.content or ""
            print(f"[visual] tim3 raw: {raw[:160]!r}")
            return parse_visual_response(raw)
        except Exception as e:  # noqa: BLE001
            print(f"[visual] tim3 error (attempt {attempt + 1}/{VISUAL_MAX_RETRIES}): {e}")
            if attempt < VISUAL_MAX_RETRIES - 1:
                await asyncio.sleep(2 * (attempt + 1))

    return {
        "kategori": "SAFE",
        "predicted_rating": "SU",
        "confidence_score": 0.0,
        "reason": "Model visual Tim 3 gagal merespons.",
    }


async def classify_visual(
    context_text: str = "",
    image_urls: list[str] | None = None,
    content_type: str = "image",
) -> dict:
    """Klasifikasi visual via endpoint Tim 3 (pad3_model).

    `image_urls` harus berupa URL http(s) publik atau data-URI base64 yang sudah
    siap kirim (resolusi MinIO / ekstraksi keyframe video dilakukan oleh pemanggil).
    Mengembalikan dict ternormalisasi {kategori, predicted_rating,
    confidence_score, reason}.
    """
    valid_urls = [u for u in (image_urls or []) if u]
    
    if not valid_urls:
        return await _classify_single_batch(context_text, [], content_type)

    chunk_size = max(1, VISUAL_MAX_IMAGES)
    chunks = [valid_urls[i:i + chunk_size] for i in range(0, len(valid_urls), chunk_size)]
    
    print(f"[visual] tim3 memproses {len(valid_urls)} gambar dalam {len(chunks)} batch (berurutan)")
    
    results = []
    for chunk in chunks:
        res = await _classify_single_batch(context_text, chunk, content_type)
        results.append(res)
    
    rating_severity = {"SU": 0, "7+": 1, "13+": 2, "17+": 3, "PRC": 4}
    worst_result = results[0]
    worst_score = -1
    
    for r in results:
        is_unsafe = str(r.get("kategori", "SAFE")).strip().upper() != "SAFE"
        r_rating = str(r.get("predicted_rating", "SU")).strip().upper()
        rating_score = rating_severity.get(r_rating, 0)
        
        score = (100 if is_unsafe else 0) + rating_score
        if score > worst_score:
            worst_score = score
            worst_result = r
            
    return worst_result
