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
import re
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
import platform
import httpx
from filelock import FileLock, Timeout as FileLockTimeout
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

# Kredensial untuk do_login() — hanya dipakai sebagai fallback manual,
# tidak digunakan oleh pool flow.
TW_USER = os.getenv("TW_USER_1") or os.getenv("TW_USER")
TW_PASS = os.getenv("TW_PASS")

BASE_DIR = Path(__file__).resolve().parent

# ---- Session Pool ----
POOL_SIZE     = 5
SESSION_FILES = [BASE_DIR / f"twitter_session_{i}.json" for i in range(1, POOL_SIZE + 1)]
LOCK_FILES    = [BASE_DIR / f".twitter_session_{i}.lock" for i in range(1, POOL_SIZE + 1)]
RR_STATE_FILE = BASE_DIR / ".twitter_rr_counter"
RR_LOCK_FILE  = BASE_DIR / ".twitter_rr.lock"

COLLECTION_NAME = "social_media_posts"
HEADLESS_FLAG = False
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


def _get_next_rr_index() -> int:
    """Baca dan increment round-robin counter secara atomik (multi-process safe).

    Menggunakan file lock pada RR_LOCK_FILE untuk memastikan tidak ada
    dua proses yang membaca/menulis counter secara bersamaan.

    Returns:
        int: Index slot (0-based) sebagai titik awal pencarian sesi idle.
    """
    with FileLock(str(RR_LOCK_FILE), timeout=10):
        try:
            idx = int(RR_STATE_FILE.read_text().strip()) if RR_STATE_FILE.exists() else 0
        except (ValueError, IOError):
            idx = 0
        RR_STATE_FILE.write_text(str((idx + 1) % POOL_SIZE))
        return idx


def do_login(page) -> bool:
    """Login otomatis ke X/Twitter menggunakan TW_USER dan TW_PASS.

    X menggunakan flow 2-langkah: username → Next → password → Log in.
    Fungsi ini adalah fallback manual — tidak dipanggil oleh pool flow.

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
# 4. SCRAPING — Session pool + Playwright auth + tweet-harvest + download media
# ============================================================
def scrape_twitter(keyword: list[str], target_post: int, temp_dir: Path) -> list[dict]:
    """Ekstrak auth_token via Playwright (session pool), scrape via tweet-harvest, download media.

    Mekanisme session pool:
    - Memilih slot sesi secara round-robin menggunakan file counter atomik.
    - Setiap slot dikunci dengan FileLock (inter-process) agar tidak dipakai
      oleh dua instance sekaligus.
    - Jika slot sedang dipakai (locked) atau session-nya expired, slot tersebut
      dilewati dan dicoba slot berikutnya — tanpa re-login.
    - Lock dilepas segera setelah auth_token diekstrak, sebelum tweet-harvest,
      sehingga slot tidak terblokir saat download CSV yang bisa berlangsung lama.

    Args:
        keyword:     Daftar keyword pencarian Twitter/X.
        target_post: Jumlah target tweet yang diambil.
        temp_dir:    Direktori sementara untuk CSV dan file media yang diunduh.

    Returns:
        List dokumen dengan field file_path berisi path lokal sementara.

    Raises:
        RuntimeError: Jika semua slot pool tidak tersedia atau tidak valid.
    """
    start_idx  = _get_next_rr_index()
    auth_token = None

    # ---- Tahap 1: Playwright → round-robin session pool → ekstrak auth_token ----
    for offset in range(POOL_SIZE):
        slot_idx     = (start_idx + offset) % POOL_SIZE
        session_file = SESSION_FILES[slot_idx]
        lock         = FileLock(str(LOCK_FILES[slot_idx]), timeout=0)

        # Coba kunci slot (non-blocking). Jika gagal → slot sibuk, geser ke berikutnya.
        try:
            lock.acquire()
            logger.info("[Pool] Slot %d/%d berhasil dikunci.", slot_idx + 1, POOL_SIZE)
        except FileLockTimeout:
            logger.info("[Pool] Slot %d sibuk, lanjut ke berikutnya...", slot_idx + 1)
            continue

        playwright_instance = None
        browser             = None

        try:
            # File session tidak ada → skip slot ini
            if not session_file.exists():
                logger.warning(
                    "[Pool] Slot %d: file session '%s' tidak ditemukan, skip.",
                    slot_idx + 1, session_file.name
                )
                continue  # finally: cleanup + release lock, lanjut iterasi berikutnya

            logger.info("[Pool] Memulai Playwright untuk slot %d ...", slot_idx + 1)
            playwright_instance = sync_playwright().start()
            browser = playwright_instance.chromium.launch(
                headless=HEADLESS_FLAG,
                args=["--disable-blink-features=AutomationControlled"],
            )

            context = browser.new_context(
                storage_state=str(session_file),
                user_agent=USER_AGENT,
            )
            page = context.new_page()
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            page.goto("https://x.com", wait_until="domcontentloaded")
            time.sleep(random.uniform(2, 4))

            # Validasi session — cek elemen nav khas akun yang sudah login.
            # Jika tidak ditemukan → session expired. Skip tanpa re-login.
            nav_button = page.query_selector('[data-testid="SideNav_AccountSwitcher_Button"]')
            if not nav_button:
                logger.warning(
                    "[Pool] Slot %d: session expired atau tidak valid. "
                    "Skip ke slot berikutnya (tanpa re-login).",
                    slot_idx + 1
                )
                continue  # finally: cleanup + release lock

            logger.info("[Pool] Slot %d: session valid, ekstrak auth_token.", slot_idx + 1)

            # Ekstrak auth_token dari cookies
            cookies     = context.cookies("https://x.com")
            auth_cookie = next((c for c in cookies if c["name"] == "auth_token"), None)
            if not auth_cookie:
                logger.warning(
                    "[Pool] Slot %d: auth_token tidak ditemukan di cookies. Skip.",
                    slot_idx + 1
                )
                continue  # finally: cleanup + release lock

            auth_token = auth_cookie["value"]
            logger.info("[Pool] Slot %d: auth_token berhasil diekstrak.", slot_idx + 1)

        finally:
            # Selalu dijalankan: sebelum continue, break, maupun exception tak terduga.
            # Lock dilepas di sini — sebelum tweet-harvest — agar slot tidak terblokir lama.
            if browser:
                browser.close()
                logger.info("[Pool] Browser Chromium ditutup (slot %d).", slot_idx + 1)
            if playwright_instance:
                playwright_instance.stop()
                logger.info("[Pool] Playwright instance dihentikan (slot %d).", slot_idx + 1)
            if lock.is_locked:
                lock.release()
                logger.info("[Pool] Lock slot %d dilepas.", slot_idx + 1)

        # auth_token berhasil didapat → keluar dari loop pool
        if auth_token:
            break

    else:
        # for...else: blok ini jalan hanya jika loop selesai tanpa `break`
        # (artinya semua POOL_SIZE slot telah dicoba dan semuanya gagal)
        raise RuntimeError(
            f"Tidak ada session pool yang valid atau tersedia "
            f"({POOL_SIZE} slot dicoba). "
            "Periksa file twitter_session_1..5.json dan refresh session yang expired."
        )

    # ---- Tahap 2: tweet-harvest → CSV ----
    search_query = " OR ".join(keyword)
    csv_filename = "tweets.csv"
    csv_path     = temp_dir / "tweets-data" / csv_filename

    # OS Lock-in FIX: Jangan nulis npx.cmd hardcode!
    npx_exec = "npx.cmd" if platform.system() == "Windows" else "npx"

    cmd = [
        npx_exec, "tweet-harvest",
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

    # ---- Tahap 3: Baca CSV + Ekstrak Multi-Media via vxtwitter ----
    batch_id      = str(uuid.uuid4())
    scraped_at_iso = datetime.now().isoformat()
    documents: list[dict] = []

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        # Pake httpx.Client biar connection pooling aktif, request beruntun jadi ngebut
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            for counter, row in enumerate(reader):
                tweet_url = row.get("tweet_url", "")
                id_str    = row.get("id_str") or str(counter)
                unique_id = f"twitter_{id_str}"

                media_urls = []

                # 1. TEMBAK VXTWITTER: Jaminan 100% dapet semua array foto & link mp4 murni
                if tweet_url:
                    api_url = re.sub(
                        r'(https?://)(www\.)?(twitter\.com|x\.com)', r'\1api.vxtwitter.com', tweet_url)
                    try:
                        resp = client.get(api_url)
                        if resp.status_code == 200:
                            api_data   = resp.json()
                            media_urls = api_data.get("mediaURLs", [])
                    except Exception as e:
                        logger.warning(
                            "vxtwitter fetch gagal untuk %s: %s", unique_id, e)

                # 2. FALLBACK: Kalau vxtwitter down, pecah string URL dari CSV tweet-harvest
                if not media_urls:
                    img_raw = row.get("image_url", "")
                    vid_raw = row.get("video_url", "")
                    if img_raw:
                        media_urls.extend(
                            [u.strip() for u in re.split(r'[\s,]+', img_raw) if u.strip()])
                    if vid_raw:
                        media_urls.extend(
                            [u.strip() for u in re.split(r'[\s,]+', vid_raw) if u.strip()])

                # 3. DOWNLOAD MULTI-MEDIA
                file_paths   = []
                content_type = "text"

                if media_urls:
                    uid_dir = temp_dir / unique_id
                    uid_dir.mkdir(parents=True, exist_ok=True)

                    for idx, m_url in enumerate(media_urls):
                        try:
                            m_resp = client.get(m_url)
                            if m_resp.status_code == 200:
                                ext = m_url.split("?")[0].split(".")[-1].lower()
                                if ext not in {"jpg", "jpeg", "png", "webp", "mp4", "gif"}:
                                    ext = "mp4" if "video" in m_url else "jpg"

                                m_path = uid_dir / f"{idx}.{ext}"
                                m_path.write_bytes(m_resp.content)
                                file_paths.append(str(m_path))
                                logger.info("  [+] Media downloaded: %s", m_path.name)
                            else:
                                logger.warning(
                                    "  [-] Media download gagal (HTTP %d): %s",
                                    m_resp.status_code, m_url)
                        except Exception as e:
                            logger.error("  [-] Download media error %s: %s", m_url, e)

                    # 4. TENTUKAN TIPE KONTEN BUAT AI
                    if len(file_paths) > 1:
                        content_type = "multipleImage"
                    elif len(file_paths) == 1:
                        content_type = "video" if file_paths[0].endswith(".mp4") else "image"

                # 5. PACKING KE DOKUMEN
                # Cover URL: first non-video media URL (original CDN URL, browser-renderable)
                cover_url = next(
                    (u for u in media_urls
                     if not u.split("?")[0].lower().endswith((".mp4", ".webm", ".mkv", ".mov"))),
                    "",
                )

                documents.append({
                    "batch_id":       batch_id,
                    "platform":       "twitter",
                    "source":         "keyword_crawl",
                    "target_keyword": search_query,
                    "scraped_at":     scraped_at_iso,
                    "unique_id":      unique_id,
                    "url":            tweet_url,
                    "type":           content_type,
                    "caption":        row.get("full_text"),
                    "published_at":   row.get("created_at"),
                    "file_path":      file_paths,
                    "cover_url":      cover_url,
                    "duration":       None,
                    "creator": {
                        "username": row.get("username"),
                        "user_id":  row.get("user_id_str"),
                    },
                    "engagement": {
                        "like_count":    safe_int(row.get("favorite_count")),
                        "comment_count": safe_int(row.get("reply_count")),
                        "share_count":   None,
                        "view_count":    safe_int(row.get("views")),
                        "saved_count":   None,
                        "repost_count":  (
                            safe_int(row.get("quote_count"), 0)
                            + safe_int(row.get("retweet_count"), 0)
                        ),
                    },
                })

    logger.info(
        "Selesai proses CSV. Total dokumen siap di-upload: %d", len(documents))
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
        unique_id   = doc["unique_id"]
        local_paths = doc.get("file_path", [])
        minio_paths: list[str] = []

        for local_path in local_paths:
            local_file = Path(local_path)
            if not local_file.exists():
                logger.warning(
                    "File lokal tidak ditemukan, skip: %s", local_path)
                continue

            ext         = local_file.suffix.lstrip(".")
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
        "Menyimpan %d dokumen ke collection '%s'...", len(documents), COLLECTION_NAME
    )
    result = await insert_many_data(
        collection_name=COLLECTION_NAME,
        data_list=documents,
    )
    result["extracted_data"] = documents
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
        description="Twitter Crawler — Scrape tweet via tweet-harvest + Playwright session pool",
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

            # Step 1: Session pool auth + tweet-harvest + download media
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
