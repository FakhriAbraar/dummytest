"""
Dummy ML module — menggantikan panggilan OpenRouter untuk dev/local.
Menghasilkan hasil klasifikasi random yang realistis tanpa membutuhkan API key.
"""
from __future__ import annotations

import random
import asyncio

CATEGORIES_TEXT = [
    "Cyberbullying", "HateSpeech", "Perjudian", "Scam",
    "Pornografi_Teks", "Kekerasan_Teks", "Substansi_Terlarang", "Perselingkuhan", "SAFE",
]

CATEGORIES_VISUAL = [
    "Pornography_Keras", "Pornography_Ringan", "Animasi_Ringan",
    "Drug", "Addictive Substances", "Violence", "Weapon_Ringan", "SAFE", "SAFE",
]

DUMMY_REASONS_TEXT = [
    "Teks mengandung unsur yang tidak sesuai dengan norma perlindungan anak digital.",
    "Konten teks menunjukkan indikasi pelanggaran berdasarkan analisis linguistik.",
    "Analisis leksikal tidak menemukan konten berbahaya secara signifikan.",
    "Teks terindikasi mengandung kata-kata yang berkaitan dengan kategori terlarang.",
    "Tidak ditemukan indikator bahaya dalam teks yang dianalisis.",
    "Pola linguistik menunjukkan potensi penyebaran konten negatif.",
    "Kalimat mengandung implikasi yang berpotensi membahayakan kelompok rentan.",
]

DUMMY_REASONS_VISUAL = [
    "Analisis visual menunjukkan elemen yang berpotensi membahayakan.",
    "Konten visual tidak menampilkan elemen yang mengkhawatirkan.",
    "Gambar/video mengandung unsur yang tidak sesuai untuk kelompok usia muda.",
    "Visual telah dianalisis dan tidak ditemukan indikasi konten berbahaya.",
    "Konten visual memerlukan pembatasan berdasarkan kelompok usia tertentu.",
    "Pola visual mengindikasikan kemungkinan melanggar regulasi IGRS.",
    "Elemen visual menunjukkan potensi eksploitasi atau konten tidak pantas.",
]


def _make_dummy_tim1() -> dict:
    if random.random() < 0.38:
        kat = random.choice([k for k in CATEGORIES_TEXT if k != "SAFE"])
        rating = random.choice(["13+", "17+", "PRC"])
        conf = round(random.uniform(0.65, 0.95), 2)
    else:
        kat = "SAFE"
        rating = random.choice(["SU", "7+"])
        conf = round(random.uniform(0.72, 0.99), 2)
    return {
        "kategori": kat,
        "predicted_rating": rating,
        "confidence_score": conf,
        "reason": f"[Dummy-Teks] {random.choice(DUMMY_REASONS_TEXT)}",
    }


def _make_dummy_tim3() -> dict:
    if random.random() < 0.38:
        kat = random.choice([k for k in CATEGORIES_VISUAL if k != "SAFE"])
        rating = random.choice(["13+", "17+", "PRC"])
        conf = round(random.uniform(0.60, 0.92), 2)
    else:
        kat = "SAFE"
        rating = random.choice(["SU", "7+"])
        conf = round(random.uniform(0.70, 0.98), 2)
    return {
        "kategori": kat,
        "predicted_rating": rating,
        "confidence_score": conf,
        "reason": f"[Dummy-Visual] {random.choice(DUMMY_REASONS_VISUAL)}",
    }


async def call_dummy_tim1(url: str = "", text: str = "") -> dict:
    await asyncio.sleep(0.05)
    return _make_dummy_tim1()


async def call_dummy_tim3(
    url: str = "",
    content_type: str = "text",
    text: str = "",
    img_urls: list | None = None,
) -> dict:
    await asyncio.sleep(0.05)
    return _make_dummy_tim3()
