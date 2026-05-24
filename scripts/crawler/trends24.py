""" Cara eksekusi yang benar sebagai subprocess dari AI Agent:

import subprocess, json, sys

result = subprocess.run(
    ["python", "-m", "scripts.crawler.trends24", "--region", "indonesia"],
    capture_output=True,
    text=True,
    cwd="<path-to-aitf-backend>"
)

response = json.loads(result.stdout)   # Dijamin JSON murni
logs      = result.stderr              # Semua log proses ada di sini
exit_code = result.returncode          # 0 = sukses, 1 = gagal
"""

import sys
import json
import time
import asyncio
import logging
import argparse
from typing import Any
from datetime import datetime

from bs4 import BeautifulSoup
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
    format="[trends24] %(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ============================================================
# 2. ARGUMENT PARSING
# ============================================================
parser = argparse.ArgumentParser(
    description="Trends24 Scraper — Scrape trending topics dari trends24.in",
    formatter_class=argparse.RawTextHelpFormatter,
)
parser.add_argument(
    "--region",
    type=str,
    default="indonesia",
    help="Region/negara yang di-scrape (contoh: 'indonesia', 'global', 'united-states')",
)
parser.add_argument(
    "--headless",
    type=lambda x: x.lower() != "false",
    default=True,
    help="Jalankan browser dalam mode headless (default: True)",
)
args = parser.parse_args()

# ============================================================
# 3. KONSTANTA
# ============================================================
TARGET_URL      = f"https://trends24.in/{args.region}/"
HEADLESS_FLAG   = args.headless
COLLECTION_NAME = "trends24_keyword"


# ============================================================
# 4. SCRAPING — Semua log ke stderr, tidak ada print() di sini
# ============================================================
def scrape_trends24() -> list[dict[str, Any]]:
    """Scrape data tren dari Trends24 menggunakan Playwright.

    Returns:
        List of dict berisi data tren yang berhasil di-scrape.

    Raises:
        Exception: Jika terjadi kegagalan Playwright (timeout, DOM tidak ditemukan, dll.)
    """
    results: list[dict[str, Any]] = []
    timestamp = datetime.now().isoformat()

    playwright_instance = None
    browser = None

    try:
        logger.info("Memulai Playwright...")
        playwright_instance = sync_playwright().start()

        logger.info("Membuka browser Chromium (headless=%s)...", HEADLESS_FLAG)
        browser = playwright_instance.chromium.launch(headless=HEADLESS_FLAG)

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/119.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        # --- Navigasi ---
        logger.info("Mengakses halaman: %s", TARGET_URL)
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)

        # --- Klik tab 'Table' ---
        logger.info("Menunggu dan mengklik tab 'Table'...")
        page.wait_for_selector("#tab-link-table", timeout=15000)
        page.click("#tab-link-table")

        # --- Tunggu data tabel ---
        logger.info("Menunggu konten tabel dimuat...")
        page.wait_for_selector("tbody.list tr", timeout=15000)
        time.sleep(2)  # Jeda agar semua row terisi penuh

        # --- Parsing HTML ---
        logger.info("Memulai parsing HTML...")
        html_content = page.content()
        soup = BeautifulSoup(html_content, "html.parser")
        tbody = soup.find("tbody", class_="list")

        if not tbody:
            raise RuntimeError(
                "Elemen 'tbody.list' tidak ditemukan di halaman. "
                "Kemungkinan struktur DOM berubah atau halaman gagal dimuat."
            )

        rows = tbody.find_all("tr")
        logger.info("Ditemukan %d baris data. Memulai ekstraksi...", len(rows))

        for row in rows:
            topic_cell = row.find("td", class_="topic")
            if not topic_cell:
                continue

            rank_cell     = row.find("td", class_="rank")
            position_cell = row.find("td", class_="position")
            count_cell    = row.find("td", class_="count")
            duration_cell = row.find("td", class_="duration")

            results.append({
                "scraped_at":           timestamp,
                "topic":                topic_cell.get_text(strip=True),
                "rank":                 rank_cell.get_text(strip=True) if rank_cell else None,
                "history_top_position": position_cell.get_text(strip=True) if position_cell else None,
                "related_link":         topic_cell.find("a")["href"] if topic_cell.find("a") else None,
                "tweet_count":          count_cell.get_text(strip=True) if count_cell else None,
                "trending_duration":    duration_cell.get_text(strip=True) if duration_cell else None,
            })

        logger.info("Ekstraksi selesai. Total: %d item.", len(results))
        return results

    finally:
        # Garansi resource selalu ditutup, baik sukses maupun gagal
        if browser:
            browser.close()
            logger.info("Browser Chromium ditutup.")
        if playwright_instance:
            playwright_instance.stop()
            logger.info("Playwright instance dihentikan.")


# ============================================================
# 5. DATABASE — Lifecycle koneksi MongoDB dikelola di sini
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
    # hidup sampai operasi I/O benar-benar selesai. Menutup client di `finally`
    # menyebabkan koneksi terputus sebelum `insert_many` sempat menyelesaikan
    # round-trip ke server, menghasilkan error "connection closed".
    # Lifecycle ditangani secara eksplisit dan berurutan di bawah.

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
# 6. ENTRY POINT — Satu-satunya print() ada di sini (JSON murni)
# ============================================================
if __name__ == "__main__":
    logger.info("=== Trends24 Crawler dimulai ===")
    logger.info("Target: %s | Headless: %s", TARGET_URL, HEADLESS_FLAG)

    try:
        # Step 1: Scraping
        extracted_data = scrape_trends24()

        if not extracted_data:
            raise RuntimeError(
                "Scraping selesai namun tidak ada data yang berhasil diekstrak."
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