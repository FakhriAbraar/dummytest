""" Cara eksekusi yang benar sebagai subprocess dari AI Agent:

import subprocess, json, sys

result = subprocess.run(
    ["python", "-m", "scripts.crawler.google-trends"],
    capture_output=True,
    text=True,
    cwd="<path-to-aitf-backend>"
)

response = json.loads(result.stdout)   # Dijamin JSON murni
logs      = result.stderr              # Semua log proses ada di sini
exit_code = result.returncode          # 0 = sukses, 1 = gagal
"""

import sys
import csv
import json
import asyncio
import logging
import tempfile
from typing import Any
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.db.mongo import connect_mongo, disconnect_mongo
from app.services.mongo import insert_many_data

# ============================================================
# 1. LOGGING — Seluruh output log diarahkan ke STDERR
#    sehingga STDOUT tetap bersih untuk JSON akhir.
# ============================================================
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[google-trends] %(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ============================================================
# 2. KONSTANTA
# ============================================================
TARGET_URL      = "https://trends.google.com/trending?geo=ID"
COLLECTION_NAME = "google_trends_keyword"

# Mapping header CSV ke key dokumen MongoDB
KEY_MAPPING = {
    "Trends":          "topic",
    "Search volume":   "search_volume",
    "Started":         "trend_started",
    "Ended":           "trend_ended",
    "Trend breakdown": "trend_breakdown",
    "Explore link":    "explore_link",
}


# ============================================================
# 3. SCRAPING — Semua log ke stderr, tidak ada print() di sini
# ============================================================
def _scrape_once() -> list[dict[str, Any]]:
    """Satu kali percobaan scrape Google Trends via export CSV (Playwright).

    Menggunakan direktori temporer untuk menyimpan file CSV sementara.
    File CSV dihapus otomatis setelah dikonversi ke list of dict.

    Returns:
        List of dict berisi data tren. Bisa kosong bila Google Trends sempat
        meng-export CSV header-only (race kondisi intermiten di sisi mereka).

    Raises:
        Exception: Jika terjadi kegagalan Playwright (timeout, elemen tidak ditemukan,
                   download gagal, dll.)
    """
    timestamp = datetime.now().isoformat()
    playwright_instance = None
    browser = None

    try:
        logger.info("Memulai Playwright...")
        playwright_instance = sync_playwright().start()

        logger.info("Membuka browser Chromium (headless=True)...")
        browser = playwright_instance.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        # --- Navigasi ---
        logger.info("Mengakses halaman: %s", TARGET_URL)
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)

        # --- Tunggu tabel trending ter-render sepenuhnya ---
        # Google Trends merender data secara async; export sebelum data muncul
        # menghasilkan CSV kosong (hanya header). Selector ini memastikan
        # setidaknya satu baris data trending sudah ada di DOM.
        logger.info("Menunggu data trending ter-render...")
        page.wait_for_selector("tr.enOdEe-wZVHld-vqLbZd-oKdM2c", timeout=30000)
        # Tunggu network reda + jeda agar seluruh baris (dan data di balik
        # export) selesai termuat. Tanpa ini, export kadang hanya berisi header
        # sehingga parsing menghasilkan 0 item.
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            logger.warning("networkidle tidak tercapai dalam 15s, lanjut tetap.")
        page.wait_for_timeout(2500)
        logger.info("Data tabel terdeteksi, siap di-export.")

        # --- Klik tombol Export ---
        logger.info("Mengklik tombol 'Export'...")
        page.get_by_role("button", name="Export").click()

        # --- Download CSV ---
        logger.info("Memulai download CSV...")
        with page.expect_download(timeout=30000) as download_info:
            page.get_by_role("menuitem", name="Download CSV").click()
        download = download_info.value

        # --- Simpan ke direktori temporer ---
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / download.suggested_filename
            download.save_as(str(csv_path))
            logger.info("CSV tersimpan sementara di: %s", csv_path)

            # --- Parse CSV → list of dict ---
            # encoding utf-8-sig agar BOM (jika Google menambahkannya) tidak
            # ikut menempel pada nama kolom pertama sehingga "Trends" tetap cocok.
            data: list[dict[str, Any]] = []
            with open(csv_path, newline="", encoding="utf-8-sig") as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    new_row: dict[str, Any] = {}
                    for csv_key, json_key in KEY_MAPPING.items():
                        if csv_key in row:
                            value = row[csv_key]
                            # Bersihkan karakter non-breaking space di field waktu
                            if csv_key in ("Started", "Ended"):
                                value = value.replace("\u202f", " ").strip()
                            new_row[json_key] = value
                    new_row["scraped_at"] = timestamp
                    data.append(new_row)

            logger.info("Parsing selesai. Total: %d item.", len(data))
        # TemporaryDirectory otomatis dihapus di sini (keluar dari `with` block)
        logger.info("File CSV sementara dibersihkan.")

        return data

    finally:
        # Garansi resource selalu ditutup, baik sukses maupun gagal
        if browser:
            browser.close()
            logger.info("Browser Chromium ditutup.")
        if playwright_instance:
            playwright_instance.stop()
            logger.info("Playwright instance dihentikan.")


def scrape_google_trends(max_attempts: int = 3) -> list[dict[str, Any]]:
    """Scrape Google Trends Indonesia dengan retry untuk export CSV kosong.

    Google Trends sesekali meng-export CSV yang hanya berisi header (race
    kondisi di sisi mereka) sehingga parsing menghasilkan 0 item meski tabel
    sudah terlihat. Fungsi ini mengulang seluruh proses scrape hingga
    mendapatkan data atau kehabisan percobaan.

    Args:
        max_attempts: Jumlah maksimum percobaan scrape.

    Returns:
        List of dict berisi data tren yang berhasil di-scrape (bisa kosong bila
        semua percobaan menghasilkan CSV header-only).
    """
    data: list[dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        logger.info("Percobaan scrape %d/%d...", attempt, max_attempts)
        data = _scrape_once()
        if data:
            return data
        logger.warning(
            "Percobaan %d menghasilkan 0 item (kemungkinan export CSV header-only).",
            attempt,
        )
    return data


# ============================================================
# 4. DATABASE — Lifecycle koneksi MongoDB dikelola di sini
# ============================================================
async def save_to_mongo(data: list[dict[str, Any]]) -> dict[str, Any]:
    """Simpan data ke MongoDB dengan mengelola lifecycle koneksi secara penuh.

    Args:
        data: List of dict yang akan di-insert ke collection.

    Returns:
        Dict hasil insert (status, ids, count).

    Raises:
        Exception: Jika koneksi MongoDB gagal atau insert gagal.
    """
    logger.info("Menginisialisasi koneksi MongoDB...")
    await connect_mongo()

    # CATATAN: disconnect_mongo() TIDAK diletakkan di blok `finally` untuk
    # menghindari race condition. Motor (async driver) membutuhkan client tetap
    # hidup sampai operasi I/O benar-benar selesai. Lifecycle ditangani secara
    # eksplisit dan berurutan di bawah.

    logger.info("Menyimpan %d dokumen ke collection '%s'...", len(data), COLLECTION_NAME)
    result = await insert_many_data(
        collection_name=COLLECTION_NAME,
        data_list=data,
    )
    result["extracted_data"] = data
    logger.info(
        "Berhasil disimpan! Count: %d | IDs (sample): %s...",
        result.get("count", 0),
        result.get("ids", [])[:3],
    )

    # Tutup koneksi hanya setelah insert selesai sepenuhnya
    await disconnect_mongo()
    logger.info("Koneksi MongoDB ditutup.")

    return result


# ============================================================
# 5. ENTRY POINT — Satu-satunya print() ada di sini (JSON murni)
# ============================================================
if __name__ == "__main__":
    logger.info("=== Google Trends Crawler dimulai ===")
    logger.info("Target: %s", TARGET_URL)

    try:
        # Step 1: Scraping
        extracted_data = scrape_google_trends()

        if not extracted_data:
            raise RuntimeError(
                "Scraping selesai namun tidak ada data yang berhasil diekstrak dari CSV."
            )

        # Step 2: Simpan ke MongoDB
        response = asyncio.run(save_to_mongo(extracted_data))

        # Step 3: Output JSON murni ke STDOUT — satu-satunya print()
        logger.info("=== Crawler selesai dengan sukses ===")
        print(json.dumps(response, default=str))
        sys.exit(0)

    except Exception as exc:
        logger.error("Eksekusi gagal: %s", exc, exc_info=True)
        error_payload = {
            "status":  "error",
            "message": str(exc),
        }
        # Error juga dikembalikan sebagai JSON ke STDOUT agar Agent bisa parse
        print(json.dumps(error_payload))
        sys.exit(1)