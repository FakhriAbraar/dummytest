""" Cara eksekusi yang benar sebagai subprocess dari AI Agent:

import subprocess, json, sys

result = subprocess.run(
    ["python", "-m", "scripts.crawler.twitter",
     "--keyword", "komdigi", "--target_post", "20"],
    capture_output=True,
    text=True,
    cwd="<path-to-aitf-backend>"
)

response = json.loads(result.stdout)   # Dijamin JSON murni
logs      = result.stderr              # Semua log proses ada di sini
exit_code = result.returncode          # 0 = sukses, 1 = gagal
"""

from app.services.mongo import insert_many_data
from app.services.minio import save_from_local
from app.db.mongo import connect_mongo, disconnect_mongo
from app.db.minio import connect_minio, disconnect_minio
import os
import csv
import sys
import time
import json
import uuid
import random
import asyncio
import logging
import tempfile
import argparse
import subprocess
import requests
import yt_dlp
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# sys.path.insert WAJIB sebelum semua import app.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


# ============================================================
# 1. LOGGING — Seluruh output log diarahkan ke STDERR
#    sehingga STDOUT tetap bersih untuk JSON akhir.
# ============================================================
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[twitter] %(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ============================================================
# 2. KONSTANTA
# ============================================================
load_dotenv()
TW_USER = os.getenv("TW_USER")
TW_PASS = os.getenv("TW_PASS")

BASE_DIR = Path(__file__).resolve().parent
SESSION_FILE = BASE_DIR / "twitter_session.json"
COLLECTION_NAME = "social_media_posts"
HEADLESS_FLAG = True
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
)


# ============================================================
# 3. HELPER FUNCTIONS
# ============================================================
def safe_int(value, default=None):
    """Convert string ke integer, return default jika gagal."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def do_login(page) -> bool:
    """Login otomatis ke X/Twitter menggunakan TW_USER dan TW_PASS.

    X menggunakan flow 2-langkah: username → Next → password → Log in.

    Args:
        page: Playwright Page object yang sudah dibuka.

    Returns:
        True jika login berhasil, False jika gagal.
    """
    if not TW_USER or not TW_PASS:
        print("[ERROR] TW_USER atau TW_PASS belum diset di .env")
        return False

    logger.info("Melakukan login baru untuk @%s ...", TW_USER)
    try:
        page.goto("https://x.com/i/flow/login")

        # Step 1: Username
        page.wait_for_selector(
            'input', timeout=15000)
        page.locator('input').click()
        time.sleep(0.5)
        inp = page.locator('input')
        for chunk in [TW_USER[i:i+n] for i, n in zip([0, 5, 11, 14, 15, 20], [5, 6, 3, 1, 5, 4])]:
            if chunk:
                inp.press_sequentially(chunk, delay=120)
                time.sleep(random.uniform(0.2, 0.5))
        time.sleep(1)

        # Step 2: Next
        page.locator("button:has-text('Next')").click()
        time.sleep(1.5)

        # Step 3: Password
        # Catatan: X terkadang menampilkan verifikasi phone/email di sini.
        # Jika timeout, gunakan twitter_login_test.py untuk debug secara visual.
        page.wait_for_selector(
            'input[autocomplete="current-password"]', timeout=15000)
        time.sleep(0.5)
        page.locator('input[autocomplete="current-password"]').fill(TW_PASS)
        time.sleep(1)

        # Step 4: Log in
        page.locator('[data-testid="LoginForm_Login_Button"]').click()

        # Step 5: Tunggu redirect ke home
        page.wait_for_url("https://x.com/home", timeout=30000)
        logger.info("Login berhasil!")
        return True

    except Exception as exc:
        logger.error("Login gagal: %s", exc)
        return False


# ============================================================
# 4. SCRAPING — Playwright auth + tweet-harvest + download media
# ============================================================
def scrape_twitter(keyword: list[str], target_post: int, temp_dir: Path) -> list[dict]:
    """Ekstrak auth_token via Playwright, scrape via tweet-harvest, download media.

    Args:
        keyword:     Daftar keyword pencarian Twitter/X.
        target_post: Jumlah target tweet yang diambil.
        temp_dir:    Direktori sementara untuk CSV dan file media yang diunduh.

    Returns:
        List dokumen dengan field file_path berisi path lokal sementara.

    Raises:
        RuntimeError: Jika login gagal atau auth_token tidak ditemukan.
    """
    playwright_instance = None
    browser = None
    auth_token = None

    # ---- Tahap 1: Playwright → ekstrak auth_token ----
    try:
        logger.info("Memulai Playwright ...")
        playwright_instance = sync_playwright().start()
        browser = playwright_instance.chromium.launch(
            headless=HEADLESS_FLAG,
            args=["--disable-blink-features=AutomationControlled"],
        )

        if SESSION_FILE.exists():
            logger.info("Memuat sesi login dari: %s", SESSION_FILE)
            context = browser.new_context(
                storage_state=str(SESSION_FILE),
                user_agent=USER_AGENT,
            )
        else:
            context = browser.new_context(user_agent=USER_AGENT)

        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        page.goto("https://x.com", wait_until="domcontentloaded")
        time.sleep(random.uniform(2, 4))

        if not SESSION_FILE.exists():
            if not do_login(page):
                raise RuntimeError("Login Twitter gagal.")
            context.storage_state(path=str(SESSION_FILE))
            logger.info("Session baru disimpan ke: %s", SESSION_FILE)
        else:
            # Verifikasi session masih valid
            nav_button = page.query_selector(
                '[data-testid="SideNav_AccountSwitcher_Button"]')
            if nav_button:
                logger.info("Session tersimpan valid, langsung lanjut.")
            else:
                logger.warning(
                    "Session tidak valid atau expired, mencoba login ulang ...")
                if not do_login(page):
                    raise RuntimeError("Re-login Twitter gagal.")
                context.storage_state(path=str(SESSION_FILE))
                logger.info("Session diperbarui di: %s", SESSION_FILE)

        # Ekstrak auth_token dari cookies
        cookies = context.cookies("https://x.com")
        auth_cookie = next(
            (c for c in cookies if c["name"] == "auth_token"), None)
        if not auth_cookie:
            raise RuntimeError(
                "auth_token tidak ditemukan di cookies. Session mungkin expired."
            )
        auth_token = auth_cookie["value"]
        logger.info("auth_token berhasil diekstrak.")

    finally:
        if browser:
            browser.close()
            logger.info("Browser Chromium ditutup.")
        if playwright_instance:
            playwright_instance.stop()
            logger.info("Playwright instance dihentikan.")

    # ---- Tahap 2: tweet-harvest → CSV ----
    # tweet-harvest selalu simpan ke <cwd>/tweets-data/<output>, tidak bisa terima
    # absolute Windows path (C: dikonversi jadi C-). Solusi: cwd=temp_dir + nama relatif.
    search_query = " OR ".join(keyword)
    csv_filename = "tweets.csv"
    csv_path = temp_dir / "tweets-data" / csv_filename
    cmd = [
        "npx.cmd", "tweet-harvest",
        "-s", search_query,
        "-t", auth_token,
        "-l", str(target_post),
        "-e", "csv",
        "-o", csv_filename,
    ]
    logger.info("Menjalankan tweet-harvest untuk query: %s", search_query)
    subprocess.run(
        cmd, check=True, stdout=sys.stderr, stderr=sys.stderr, cwd=str(temp_dir)
    )

    if not csv_path.exists():
        raise RuntimeError(
            f"tweet-harvest selesai tapi CSV tidak ditemukan: {csv_path}"
        )
    logger.info("tweet-harvest selesai. CSV: %s", csv_path)

    # ---- Tahap 3: Baca CSV + download media ----
    batch_id = str(uuid.uuid4())
    scraped_at_iso = datetime.now().isoformat()
    documents: list[dict] = []

    ydl_opts: dict = {
        "outtmpl": str(temp_dir / "%(id)s.%(ext)s"),
        "format": "best",
        "quiet": True,
        "no_warnings": True,
    }

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for counter, row in enumerate(reader):
            image_url = row.get("image_url", "")
            tweet_url = row.get("tweet_url", "")
            id_str = row.get("id_str") or str(counter)
            unique_id = f"twitter_{id_str}"
            file_paths: list[str] = []
            content_type = "text"

            # Gambar
            if image_url:
                content_type = "image"
                ext = os.path.splitext(urlparse(image_url).path)[1].lstrip(".")
                img_path = temp_dir / f"twitter_{id_str}.{ext}"
                try:
                    img_res = requests.get(image_url, timeout=10)
                    if img_res.status_code == 200:
                        img_path.write_bytes(img_res.content)
                        file_paths.append(str(img_path))
                        logger.info(
                            "Gambar berhasil didownload: %s", unique_id)
                    else:
                        logger.warning(
                            "Download gambar gagal (HTTP %d): %s",
                            img_res.status_code, image_url,
                        )
                except Exception as exc:
                    logger.warning(
                        "Download gambar error untuk %s: %s", unique_id, exc)

            # Video (fallback jika tidak ada gambar)
            if not file_paths and tweet_url:
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(tweet_url, download=True)
                        if info:
                            content_type = "video"
                            filename = ydl.prepare_filename(info)
                            file_paths.append(str(Path(filename)))
                            logger.info(
                                "Video berhasil didownload: %s", tweet_url)
                except Exception as exc:
                    logger.warning(
                        "Download video error untuk %s: %s", unique_id, exc)

            documents.append({
                "batch_id":       batch_id,
                "platform":       "twitter",
                "target_keyword": search_query,
                "scraped_at":     scraped_at_iso,
                "unique_id":      unique_id,
                "url":            tweet_url,
                "type":           content_type,
                "caption":        row.get("full_text"),
                "published_at":   row.get("created_at"),
                "file_path":      file_paths,  # lokal sementara — diganti MinIO di upload_and_save()
                "duration":       None,
                "creator": {
                    "username": row.get("username"),
                    "user_id":  row.get("user_id_str"),
                },
                "engagement": {
                    "like_count":    safe_int(row.get("favorite_count")),
                    "comment_count": safe_int(row.get("reply_count")),
                    "share_count":   None,
                    "view_count":    None,
                    "saved_count":   None,
                    "repost_count":  (
                        safe_int(row.get("quote_count"), 0)
                        + safe_int(row.get("retweet_count"), 0)
                    ),
                },
            })

    logger.info("CSV dibaca. Total dokumen: %d", len(documents))
    return documents


# ============================================================
# 5. UPLOAD MINIO + SAVE MONGODB (async)
# ============================================================
async def upload_and_save(documents: list[dict]) -> dict:
    """Upload file lokal ke MinIO dan simpan metadata ke MongoDB.

    Args:
        documents: List dokumen dengan file_path berisi path lokal sementara.

    Returns:
        Dict hasil insert MongoDB (status, count, ids).

    Raises:
        Exception: Jika koneksi MinIO/MongoDB gagal atau operasi I/O gagal.
    """
    await connect_minio()
    logger.info("Koneksi MinIO berhasil.")

    for doc in documents:
        unique_id = doc["unique_id"]
        local_paths = doc.get("file_path", [])
        minio_paths: list[str] = []

        for local_path in local_paths:
            local_file = Path(local_path)
            if not local_file.exists():
                logger.warning(
                    "File lokal tidak ditemukan, skip: %s", local_path)
                continue

            ext = local_file.suffix.lstrip(".")
            object_name = f"crawl/twitter/{unique_id}.{ext}"

            result = await save_from_local(
                source=local_path,
                destination=object_name,
            )
            if result.get("status") == "success":
                minio_paths.append(result["path"])
            else:
                logger.warning(
                    "Upload gagal untuk %s: %s",
                    local_file.name, result.get("message"),
                )

        doc["file_path"] = minio_paths

    await disconnect_minio()
    logger.info("Koneksi MinIO ditutup.")

    logger.info("Menginisialisasi koneksi MongoDB...")
    await connect_mongo()

    logger.info(
        "Menyimpan %d dokumen ke collection '%s'...", len(
            documents), COLLECTION_NAME
    )
    result = await insert_many_data(
        collection_name=COLLECTION_NAME,
        data_list=documents,
    )
    logger.info(
        "Berhasil disimpan! Count: %d | IDs (sample): %s...",
        result.get("count", 0),
        result.get("ids", [])[:3],
    )

    await disconnect_mongo()
    logger.info("Koneksi MongoDB ditutup.")

    return result


# ============================================================
# 6. ENTRY POINT — Satu-satunya print() ada di sini (JSON murni)
# ============================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Twitter Crawler — Scrape tweet via tweet-harvest + Playwright auth",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--keyword",     nargs="+",
                        required=True, help="Daftar keyword pencarian")
    parser.add_argument("--target_post", type=int,
                        required=True, help="Jumlah target tweet")
    args = parser.parse_args()

    logger.info("=== Twitter Crawler dimulai ===")
    logger.info("Target: %s | target_post: %d", args.keyword, args.target_post)

    try:
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)
            logger.info("Temporary directory: %s", temp_dir)

            # Step 1: Playwright auth + tweet-harvest + download media
            documents = scrape_twitter(
                args.keyword, args.target_post, temp_dir)

            if not documents:
                raise RuntimeError(
                    "Scraping selesai namun tidak ada tweet yang ditemukan.")

            # Step 2: Upload MinIO, simpan MongoDB
            response = asyncio.run(upload_and_save(documents))

        # Step 3: Output JSON murni ke STDOUT — satu-satunya print()
        logger.info("=== Crawler selesai dengan sukses ===")
        print(json.dumps(response, default=str))
        sys.exit(0)

    except Exception as exc:
        logger.error("Eksekusi gagal: %s", exc, exc_info=True)
        print(json.dumps({"status": "error", "message": str(exc)}))
        sys.exit(1)
