"""Unified Multi-modal Client for itspad (Tim 1, Keyword Generator, Tim 3)

Mengkombinasikan model klasifikasi teks, gambar, dan ekstraksi keyword ke dalam 
satu endpoint `itspad` port 8001.

Konfigurasi via .env:
    ITSPAD_API_BASE_URL default https://5t4gp3ab7iv7cr-8001.proxy.runpod.net/v1
    ITSPAD_API_MODEL    default itspad
    ITSPAD_API_KEY      default EMPTY
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import re

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

ITSPAD_API_BASE_URL = os.getenv("ITSPAD_API_BASE_URL", "https://5t4gp3ab7iv7cr-8001.proxy.runpod.net/v1")
ITSPAD_API_MODEL = os.getenv("ITSPAD_API_MODEL", "itspad")
ITSPAD_API_KEY = os.getenv("ITSPAD_API_KEY", "EMPTY")
ITSPAD_MAX_TOKENS = int(os.getenv("ITSPAD_MAX_TOKENS", "512"))
ITSPAD_MAX_RETRIES = int(os.getenv("ITSPAD_MAX_RETRIES", "3"))

_client: AsyncOpenAI | None = None

def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(base_url=ITSPAD_API_BASE_URL, api_key=ITSPAD_API_KEY)
    return _client

def _normalize_rating(raw_rating: str) -> str:
    """Normalkan variasi rating ke standard: SU, 7+, 13+, 17+, PRC, UNRATED"""
    if not raw_rating:
        return "SU"
        
    val = raw_rating.strip().upper()
    
    mapping = {
        "SEMUA UMUR": "SU", "ALL": "SU", "G": "SU", "3+": "SU", "0+": "SU", "SU": "SU",
        "7+": "7+", "7": "7+",
        "13+": "13+", "13": "13+",
        "15+": "17+", "16+": "17+", "17+": "17+", "17": "17+",
        "18+": "PRC", "21+": "PRC", "KONTEN TERLARANG": "PRC", "PRC": "PRC", "R": "PRC", 
        "DEWASA": "PRC", "ADULT": "PRC", "RESTRICTED": "PRC", "PROHIBITED": "PRC",
        "UNRATED": "UNRATED"
    }
    
    if val in mapping:
        return mapping[val]
        
    for tok, mapped in mapping.items():
        if tok in val:
            return mapped
            
    return "SU"

def parse_output(task: str, output: str) -> dict:
    """Parse output dari model berdasarkan Task."""
    clean_output = output.strip()
    
    # Hapus markdown block ```json ... ```
    clean_output = re.sub(r'^```json\s*', '', clean_output, flags=re.IGNORECASE)
    clean_output = re.sub(r'^```\s*', '', clean_output)
    clean_output = re.sub(r'```\s*$', '', clean_output)
    
    if task == "KEYWORD_EXTRACTION":
        # Model kadang balas JSON valid (double quote), kadang list gaya Python
        # (single quote) yang BUKAN JSON valid — mis. ['a', 'b']. Coba json.loads
        # lalu ast.literal_eval, baru fallback regex (tangkap quote tunggal & ganda).
        for loader in (json.loads, ast.literal_eval):
            try:
                parsed = loader(clean_output)
                if isinstance(parsed, (list, tuple)):
                    kws = [str(x).strip() for x in parsed if str(x).strip()]
                    return {"keywords": kws, "raw": output}
            except Exception:
                pass

        matches = re.findall(r"""['"]([^'"]+)['"]""", clean_output)
        if matches:
            return {"keywords": [m.strip() for m in matches if m.strip()], "raw": output}

        return {"keywords": [], "raw": output}

    # Untuk TEXT_CLASSIFICATION & IMG_CLASSIFICATION
    rating = "UNKNOWN"
    description = ""
    
    # Coba Parse JSON
    try:
        obj = json.loads(clean_output)
        if isinstance(obj, dict):
            rating = obj.get("rating", obj.get("Rating", "UNKNOWN"))
            description = obj.get("description", obj.get("Description", obj.get("Penjelasan", "")))
    except Exception:
        # Fallback cari json yang disematkan
        match = re.search(r'\{.*\}', clean_output, re.DOTALL)
        if match:
            try:
                obj = json.loads(match.group(0))
                if isinstance(obj, dict):
                    rating = obj.get("rating", obj.get("Rating", "UNKNOWN"))
                    description = obj.get("description", obj.get("Description", obj.get("Penjelasan", "")))
            except Exception:
                pass
                
    # Fallback RegEx if JSON failed
    if rating == "UNKNOWN" or not description:
        r_match = re.search(r'Rating\s*:\s*(.+)', clean_output, re.IGNORECASE)
        if r_match:
            rating = r_match.group(1).strip()
            
        d_match = re.search(r'Penjelasan\s*:\s*(.*)', clean_output, re.IGNORECASE | re.DOTALL)
        if d_match:
            description = d_match.group(1).strip()
            
    if not description:
        description = clean_output
        
    valid_ratings = ["Semua Umur", "7+", "13+", "15+", "18+", "Konten Terlarang", "Unrated", "SU", "PRC"]
    if rating == "UNKNOWN":
        for r in valid_ratings:
            if r.lower() in clean_output.lower():
                rating = r
                break
                
    normalized_rating = _normalize_rating(rating)
    kategori = "SAFE" if normalized_rating in ["SU", "7+"] else "UNSAFE"
    
    return {
        "kategori": kategori,
        "predicted_rating": normalized_rating,
        "confidence_score": 0.85, # default high confidence
        "reason": description[:600] or "Analisis selesai.",
        "raw_output": output
    }

async def _call_itspad(task: str, system_prompt: str, user_content: str | list) -> dict:
    """Fungsi utama memanggil endpoint vLLM untuk model itspad."""
    client = _get_client()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]
    
    for attempt in range(ITSPAD_MAX_RETRIES):
        try:
            resp = await client.chat.completions.create(
                model=ITSPAD_API_MODEL,
                messages=messages, # type: ignore
                temperature=0.0,
                max_tokens=ITSPAD_MAX_TOKENS
            )
            raw = resp.choices[0].message.content or ""
            return parse_output(task, raw)
        except Exception as e:
            print(f"[itspad] error (attempt {attempt + 1}/{ITSPAD_MAX_RETRIES}): {e}")
            if attempt < ITSPAD_MAX_RETRIES - 1:
                await asyncio.sleep(2 * (attempt + 1))
                
    # Return default fail safes
    if task == "KEYWORD_EXTRACTION":
        return {"keywords": [], "raw": ""}
    return {
        "kategori": "SAFE",
        "predicted_rating": "SU",
        "confidence_score": 0.0,
        "reason": "Model itspad gagal merespons.",
    }

async def classify_text(text_content: str = "") -> dict:
    """Menggantikan Tim 1."""
    task = "TEXT_CLASSIFICATION"
    prompt = (
        f"[TASK: {task}]\n"
        "Anda adalah sistem moderasi konten media sosial Indonesia. Tugas Anda adalah mengklasifikasikan caption/teks media sosial ke dalam kategori rating usia yang tepat dan berikan penjelasannya.\n\n"
        "DEFINISI RATING:\n"
        "- Semua Umur (Semua Umur): Konten positif, aman, dan ramah keluarga. Tidak ada unsur negatif apapun.\n"
        "- 7+: Hiburan dan fiksi ringan untuk anak SD. Boleh ada persaingan atau tantangan ringan, TANPA kekerasan realistis atau bahasa kasar.\n"
        "- 13+: Konten remaja awal. Boleh ada konflik sosial, curahan hati, misteri fiksi. TANPA unsur dewasa atau kekerasan grafis.\n"
        "- 15+: Konten remaja akhir. Boleh ada diskusi politik ringan, isu sosial, berita faktual, kriminalitas tanpa glorifikasi.\n"
        "- 18+: Konten dewasa yang LEGAL. Mencakup: alkohol, rokok, romansa dewasa (tanpa eksplisit), kehidupan malam.\n"
        "- Konten Terlarang (Konten Terlarang): HANYA untuk konten yang secara EKSPLISIT mengandung: (1) ancaman kekerasan fisik langsung, (2) pelecehan/objektifikasi seksual, (3) promosi judi online dengan kata kunci slot/gacor/scatter, (4) ujaran kebencian SARA secara langsung.\n\n"
        "FORMAT OUTPUT:\n"
        "Rating: [Semua Umur / 7+ / 13+ / 15+ / 18+ / Konten Terlarang]\n"
        "Penjelasan: [Penjelasan Logis 2-4 kalimat, sebutkan frasa spesifik sebagai penguat penjelasan jika ada atau memungkinkan]"
    )
    return await _call_itspad(task, prompt, text_content)

async def extract_keywords(text_content: str = "", platform: str = "") -> list[str]:
    """Menggantikan lokal GGUF Keyword Generator."""
    task = "KEYWORD_EXTRACTION"
    prompt = (
        f"[TASK: {task}]\n"
        "Ekstraksi semua kata kunci penting dari teks berikut dengan cara mengambil langsung dari teks asli, "
        "jangan ubah atau tambahkan apapun. Format hasilnya sebagai JSON array of strings"
    )
    user_content = f"Konteks: {platform} {text_content}"
    res = await _call_itspad(task, prompt, user_content)
    return res.get("keywords", [])

async def classify_visual(context_text: str = "", image_urls: list[str] | None = None, content_type: str = "image") -> dict:
    """Menggantikan Tim 3."""
    task = "IMG_CLASSIFICATION"
    prompt = (
        f"[TASK: {task}]\n"
        "Tugas: Analisis gambar atau teks yang diberikan, lalu tentukan klasifikasi rating usia dan deskripsi analisisnya berdasarkan karakteristik data berikut.\n\n"
        "Aturan Klasifikasi Rating:\n"
        "* \"Semua Umur\" -> Data netral, aman, bersifat edukatif, atau ramah anak tanpa adanya unsur ketegangan, ancaman, maupun darah.\n"
        "* \"7+\" -> Konten fantasi/animasi ringan, prosedur medis klinis luar tubuh yang damai, atau objek senjata yang terdistorsi dalam bentuk mainan anak plastik/neon.\n"
        "* \"13+\" -> Aktivitas simulasi taktis militer, replika senjata gelap/kamuflase (Airsoft), olahraga kontak fisik intens, atau romansa pasangan ringan tanpa cedera fatal atau darah fotorealistis.\n"
        "* \"15+\" -> Realitas keras dewasa, mencakup tindakan medis invasif/bedah organ, konflik fisik nyata (perkelahian/pengeroyokan), atau keberadaan fisik senjata api/tajam asli dalam posisi diam.\n"
        "* \"18+\" -> Konten khusus dewasa yang memuat penggunaan zat adiktif (rokok/alkohol), perilaku membahayakan diri sendiri (self-harm), atau sensualitas tingkat tinggi dengan pakaian minim tanpa ketelanjangan vulgar.\n"
        "* \"Konten Terlarang\" -> Pelanggaran hukum atau norma mutlak seperti pornografi/ketelanjangan alat vital, aktivitas terorisme/propaganda radikal, ancaman senjata mematikan secara langsung, atau penggunaan aktif narkoba keras.\n\n"
        "Aturan Penanganan Ambiguitas (Anti-Halusinasi):\n"
        "- Lakukan analisis objek secara objektif dan mendalam terlebih dahulu sebelum menentukan rating. Jangan malas menebak jika objek di dalam gambar terlihat jelas.\n"
        "- Namun, jika gambar sangat kabur (blur), tidak memiliki konteks objek yang jelas, atau Anda benar-benar tidak yakin demi menghindari halusinasi prediksi yang fatal, gunakan rating \"Unrated\".\n\n"
        "Aturan Output:\n"
        "- Wajib merespons hanya dalam format JSON valid tanpa teks tambahan di luar JSON.\n"
        "- Jangan gunakan markdown block (jangan gunakan ```json).\n\n"
        "Format Output:\n"
        "{\n"
        "\"rating\": \"...\",\n"
        "\"description\": \"...\"\n"
        "}"
    )
    
    user_content: list[dict] = []
    text_payload = f"Tipe konten: {content_type}\nKonteks: {context_text}\nAnalisis input ini secara objektif dan klasifikasikan ratingnya."
    user_content.append({"type": "text", "text": text_payload})
    
    for u in (image_urls or []):
        if u:
            user_content.append({"type": "image_url", "image_url": {"url": u}})
            
    # Karena itspad adalah multimodel, kirim gambar berserta promptnya
    return await _call_itspad(task, prompt, user_content)
