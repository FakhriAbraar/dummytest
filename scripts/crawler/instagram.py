""" Cara eksekusi yang benar sebagai subprocess dari AI Agent:

import subprocess, json, sys

result = subprocess.run(
    ["python", "-m", "scripts.crawler.instagram",
     "--keyword", "komdigi", "--target_post", "20", "--max_scroll", "10"],
    capture_output=True,
    text=True,
    cwd="<path-to-aitf-backend>"
)

response = json.loads(result.stdout)   # Dijamin JSON murni
logs      = result.stderr              # Semua log proses ada di sini
exit_code = result.returncode          # 0 = sukses, 1 = gagal
"""

import os
import re
import sys
import time
import json
import uuid
import asyncio
import random
import logging
import tempfile
import argparse
import contextlib
import instaloader
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# Tambahkan parent directory ke sys.path agar bisa import shared modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.db.minio import connect_minio, disconnect_minio
from app.db.mongo import connect_mongo, disconnect_mongo
from app.services.minio import save_from_local
from app.services.mongo import insert_many_data

# ============================================================
# 1. LOGGING — Seluruh output log diarahkan ke STDERR
#    sehingga STDOUT tetap bersih untuk JSON akhir.
# ============================================================
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[instagram] %(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ============================================================
# 2. ARGUMENT PARSING
# ============================================================
parser = argparse.ArgumentParser(
    description="Instagram Crawler — Scrape post dari hashtag Instagram",
    formatter_class=argparse.RawTextHelpFormatter,
)
parser.add_argument("--keyword",     nargs="+", required=True, help="Daftar keyword/hashtag")
parser.add_argument("--target_post", type=int,  required=True, help="Jumlah target post per keyword")
parser.add_argument("--max_scroll",  type=int,  required=True, help="Jumlah maksimum scroll per keyword")
args = parser.parse_args()

# ============================================================
# 3. KONSTANTA
# ============================================================
load_dotenv()
IG_USER = os.getenv("IG_USER")
IG_PASS = os.getenv("IG_PASS")

BASE_DIR         = Path(__file__).resolve().parent
SESSION_FILE     = BASE_DIR / "ig_session.json"   # Persistent antar run
COLLECTION_NAME  = "social_media_posts"
HEADLESS_FLAG    = False
MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".mp4"}

TARGET_TAGS       = args.keyword
MAX_POST_PER_TAG  = args.target_post
MAX_EMPTY_SCROLL  = args.max_scroll

typename_map = {
    "GraphImage":   "image",
    "GraphVideo":   "video",
    "GraphSidecar": "multipleImage",
}


# ============================================================
# 4. HELPER FUNCTIONS
# ============================================================
@contextlib.contextmanager
def _stdout_to_stderr():
    """Redirect sys.stdout → sys.stderr selama blok ini aktif.

    Instaloader memanggil print() langsung di beberapa path (retry 403,
    login checkpoint, 2FA prompt) sehingga quiet=True tidak cukup.
    Context manager ini menjamin tidak ada byte yang mencapai stdout.
    """
    old = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = old


def human_scroll(page) -> None:
    scroll_steps = random.randint(3, 6)
    logger.info("Scroll layaknya manusia (%d langkah)...", scroll_steps)
    for _ in range(scroll_steps):
        distance = random.randint(100, 300)
        page.mouse.wheel(0, distance)
        time.sleep(random.uniform(0.1, 0.4))
    time.sleep(random.uniform(1.5, 3.0))


def handle_popups(page) -> None:
    time.sleep(2)
    for selector in ["button:has-text('Not Now')", "button:has-text('Lain Kali')"]:
        try:
            btn = page.query_selector(selector)
            if btn:
                btn.click()
                time.sleep(1)
        except Exception:
            pass


def do_login(page) -> bool:
    logger.info("Melakukan login baru untuk @%s...", IG_USER)
    page.goto("https://www.instagram.com/accounts/login/")
    try:
        page.wait_for_selector('input[name="email"]', timeout=15000)
        time.sleep(2)
        username_input = page.locator('input[name="email"]')
        password_input = page.locator('input[name="pass"]')
        username_input.click()
        time.sleep(0.5)
        username_input.press_sequentially(IG_USER, delay=150)
        time.sleep(1)
        password_input.click()
        time.sleep(0.5)
        password_input.press_sequentially(IG_PASS, delay=150)
        time.sleep(1)
        page.locator('span:text-is("Log in")').click()
        time.sleep(5)
        if page.query_selector('p[id="slfErrorAlert"]'):
            logger.error("Login gagal: username atau password salah.")
            return False
        if page.query_selector('svg[aria-label="Home"]') or page.query_selector('svg[aria-label="Beranda"]'):
            logger.info("Login berhasil!")
            handle_popups(page)
            return True
        return False
    except Exception as e:
        logger.error("Terjadi kesalahan saat login: %s", e)
        return False


# ============================================================
# 5. SCRAPING — Browser selalu ditutup di finally
# ============================================================
def scrape_instagram() -> dict[str, list[str]]:
    """Scrape link post Instagram per hashtag menggunakan Playwright.

    Returns:
        Dict {tag: [post_url, ...]} untuk semua tag yang di-scrape.

    Raises:
        Exception: Jika login gagal atau terjadi kegagalan Playwright.
    """
    hasil_final: dict[str, list[str]] = {}
    playwright_instance = None
    browser = None

    try:
        logger.info("Memulai Playwright...")
        playwright_instance = sync_playwright().start()

        logger.info("Membuka browser Chromium (headless=%s)...", HEADLESS_FLAG)
        browser = playwright_instance.chromium.launch(headless=HEADLESS_FLAG)

        if SESSION_FILE.exists():
            logger.info("Memuat sesi login dari: %s", SESSION_FILE)
            context = browser.new_context(storage_state=str(SESSION_FILE))
        else:
            context = browser.new_context()

        page = context.new_page()
        page.goto("https://www.instagram.com/")
        time.sleep(4)
        is_logged_in = False

        if page.query_selector('input[name="email"]'):
            is_logged_in = do_login(page)
            if is_logged_in:
                context.storage_state(path=str(SESSION_FILE))
                logger.info("Sesi baru disimpan ke: %s", SESSION_FILE)
        else:
            if page.query_selector('svg[aria-label="Home"]') or page.query_selector('svg[aria-label="Beranda"]'):
                logger.info("Berhasil masuk menggunakan sesi tersimpan.")
                handle_popups(page)
                is_logged_in = True
            else:
                logger.warning("Sesi tidak valid. Mencoba login ulang...")
                is_logged_in = do_login(page)
                if is_logged_in:
                    context.storage_state(path=str(SESSION_FILE))
                    logger.info("Sesi diperbarui di: %s", SESSION_FILE)

        if not is_logged_in:
            raise RuntimeError("Gagal memverifikasi login Instagram.")

        for raw_tag in TARGET_TAGS:
            tag = raw_tag.lstrip("#").replace(" ", "").lower()
            
            if not tag:
                logger.warning("Keyword '%s' menjadi kosong setelah disanitasi. Skip.", raw_tag)
                continue

            logger.info("Menjelajahi #%s (dari original: '%s')...", tag, raw_tag)
            
            page.goto(f"https://www.instagram.com/explore/tags/{tag}/")
            time.sleep(3.5)
            
            links_found: set[str] = set()
            retry_scroll = 0

            while len(links_found) < MAX_POST_PER_TAG and retry_scroll < MAX_EMPTY_SCROLL:
                for el in page.query_selector_all("a"):
                    if len(links_found) >= MAX_POST_PER_TAG:
                        break
                    href = el.get_attribute("href")
                    if href and (href.startswith("/p/") or href.startswith("/reel/")):
                        links_found.add(f"https://www.instagram.com{href}")

                logger.info("  #%s — total sementara: %d link", tag, len(links_found))
                
                if len(links_found) < MAX_POST_PER_TAG:
                    human_scroll(page)
                    retry_scroll += 1
                else:
                    break

            logger.info("Selesai #%s. Didapat %d link.", tag, len(links_found))
            
            hasil_final[raw_tag] = list(links_found)

        return hasil_final

    finally:
        if browser:
            browser.close()
            logger.info("Browser Chromium ditutup.")
        if playwright_instance:
            playwright_instance.stop()
            logger.info("Playwright instance dihentikan.")


# ============================================================
# 6. DOWNLOAD + UPLOAD MINIO + SAVE MONGODB (async)
# ============================================================
async def download_upload_and_save(tag_links: dict[str, list[str]]) -> dict:
    """Download post, upload media ke MinIO, simpan metadata ke MongoDB.

    Args:
        tag_links: Dict {tag: [post_url, ...]} hasil scrape_instagram().

    Returns:
        Dict hasil insert MongoDB (status, count, ids).

    Raises:
        Exception: Jika koneksi MinIO/MongoDB gagal atau operasi I/O gagal.
    """
    await connect_minio()
    logger.info("Koneksi MinIO berhasil.")

    batch_id       = str(uuid.uuid4())
    scraped_at_iso = datetime.now().isoformat()
    documents: list[dict] = []

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        L = instaloader.Instaloader(
            dirname_pattern=str(temp_path / "{target}"),
            quiet=True,
        )
        with _stdout_to_stderr():
            L.login(IG_USER, IG_PASS)
        logger.info("Instaloader login berhasil.")

        for kw, links in tag_links.items():
            logger.info("Mendownload post untuk #%s (%d link)...", kw, len(links))
            for link in links:
                match = re.search(r"(?:p|reel)/([^/]+)/", link)
                if not match:
                    continue

                shortcode = match.group(1)
                unique_id = f"instagram_{shortcode}"

                try:
                    with _stdout_to_stderr():
                        post = instaloader.Post.from_shortcode(L.context, shortcode)
                        L.download_post(post, target=f"{shortcode}")
                except Exception as e:
                    logger.warning("Gagal download post %s: %s", shortcode, e)
                    continue

                # Upload semua file media dari folder temp ke MinIO
                post_temp_dir = temp_path / shortcode
                file_paths: list[str] = []

                if post_temp_dir.exists():
                    media_files = sorted([
                        f for f in post_temp_dir.iterdir()
                        if f.is_file() and f.suffix.lower() in MEDIA_EXTENSIONS
                    ])

                    for idx, media_file in enumerate(media_files):
                        ext = media_file.suffix.lstrip(".")
                        if len(media_files) == 1:
                            object_name = f"crawl/instagram/{unique_id}.{ext}"
                        else:
                            object_name = f"crawl/instagram/{unique_id}/{idx}.{ext}"

                        result = await save_from_local(
                            source=str(media_file),
                            destination=object_name,
                        )
                        if result.get("status") == "success":
                            file_paths.append(result["path"])
                        else:
                            logger.warning("Upload gagal untuk %s: %s", media_file.name, result.get("message"))
                else:
                    logger.warning("Folder temp tidak ditemukan untuk shortcode: %s", shortcode)

                documents.append({
                    "batch_id":        batch_id,
                    "platform":        "instagram",
                    "source":          "keyword_crawl",
                    "target_keyword":  kw,
                    "scraped_at":      scraped_at_iso,
                    "unique_id":       unique_id,
                    "url":             f"https://instagram.com/p/{shortcode}/",
                    "type":            typename_map.get(post.typename, "Unknown"),
                    "caption":         post.caption.replace("\n", " ") if post.caption else None,
                    "published_at":    post.date.isoformat(),
                    "file_path":       file_paths,
                    "duration":        None,
                    "creator": {
                        "username": post.owner_username,
                        "user_id":  str(post.owner_id),
                    },
                    "engagement": {
                        "like_count":    post.likes,
                        "comment_count": post.comments,
                        "share_count":   None,
                        "view_count":    None,
                        "saved_count":   None,
                        "repost_count":  None,
                    },
                })
                time.sleep(1)

            logger.info("Selesai download #%s.", kw)
        # TemporaryDirectory otomatis dibersihkan di sini

    await disconnect_minio()
    logger.info("Koneksi MinIO ditutup.")

    # MongoDB — pola identik dengan trends24.py
    logger.info("Menginisialisasi koneksi MongoDB...")
    await connect_mongo()

    logger.info("Menyimpan %d dokumen ke collection '%s'...", len(documents), COLLECTION_NAME)
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
# 7. ENTRY POINT — Satu-satunya print() ada di sini (JSON murni)
# ============================================================
if __name__ == "__main__":
    logger.info("=== Instagram Crawler dimulai ===")
    logger.info(
        "Target: %s | target_post: %d | max_scroll: %d",
        TARGET_TAGS, MAX_POST_PER_TAG, MAX_EMPTY_SCROLL,
    )

    try:
        # Step 1: Scraping link via Playwright
        tag_links = scrape_instagram()

        if not tag_links or not any(tag_links.values()):
            raise RuntimeError("Scraping selesai namun tidak ada post yang ditemukan.")

        # Step 2: Download, upload MinIO, simpan MongoDB
        response = asyncio.run(download_upload_and_save(tag_links))

        # Step 3: Output JSON murni ke STDOUT — satu-satunya print()
        logger.info("=== Crawler selesai dengan sukses ===")
        print(json.dumps(response, default=str))
        sys.exit(0)

    except Exception as exc:
        logger.error("Eksekusi gagal: %s", exc, exc_info=True)
        print(json.dumps({"status": "error", "message": str(exc)}))
        sys.exit(1)
