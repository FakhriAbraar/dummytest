""" Cara eksekusi yang benar sebagai subprocess dari AI Agent:

import subprocess, json, sys

result = subprocess.run(
    ["python", "-m", "scripts.crawler.youtube",
     "--keyword", "komdigi", "--target_post", "5"],
    capture_output=True,
    text=True,
    cwd="<path-to-aitf-backend>"
)

response = json.loads(result.stdout)   # Dijamin JSON murni
logs      = result.stderr              # Semua log proses ada di sini
exit_code = result.returncode          # 0 = sukses, 1 = gagal
"""

import re
import sys
import json
import time
import uuid
import random
import asyncio
import logging
import tempfile
import argparse
import contextlib
import yt_dlp
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# sys.path.insert WAJIB sebelum semua import app.*
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
    format="[youtube] %(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)
logger = logging.getLogger(__name__)


# ============================================================
# 2. HELPERS
# ============================================================
@contextlib.contextmanager
def _stdout_to_stderr():
    """Redirect sys.stdout → sys.stderr selama blok ini aktif."""
    old = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = old


class _YdlLogger:
    def debug(self, _: str) -> None: pass
    def info(self, _: str) -> None: pass
    def warning(self, msg: str) -> None: logger.warning("[yt_dlp] %s", msg)
    def error(self, msg: str) -> None: logger.error("[yt_dlp] %s", msg)


# ============================================================
# 3. KONSTANTA
# ============================================================
load_dotenv()
COLLECTION_NAME = "social_media_posts"


# ============================================================
# 4. PLAYWRIGHT HELPERS
# ============================================================
def human_scroll(page) -> None:
    scroll_steps = random.randint(6, 12)
    logger.info("  [Scroll seperti manusia... %d langkah]", scroll_steps)
    for _ in range(scroll_steps):
        distance = random.randint(400, 1000)
        page.mouse.wheel(0, distance)
        time.sleep(random.uniform(0.2, 0.5))
    time.sleep(random.uniform(1.5, 3.0))


# ============================================================
# 5. SCRAPING — Playwright kumpulkan URL, return flat list
# ============================================================
def scrape_youtube(keyword: list[str], target_post: int, max_scroll: int) -> list[str]:
    """Scrape URL video YouTube via Playwright berdasarkan keyword.

    Args:
        keyword:     Daftar keyword pencarian.
        target_post: Jumlah target video per keyword.
        max_scroll:  Maksimum jumlah scroll per keyword.

    Returns:
        Flat list URL video YouTube yang ditemukan.
    """
    all_urls: list[str] = []

    with _stdout_to_stderr():
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-web-security",
                    "--lang=id-ID",
                ],
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/123.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 768},
                locale="id-ID",
                timezone_id="Asia/Jakarta",
            )
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['id-ID','id','en-US','en']});
                window.chrome = {runtime: {}};
            """)
            page = context.new_page()

            # Stealth: buka google.com dulu sebelum ke YouTube
            page.goto("https://www.google.com")
            time.sleep(2)
            page.goto("https://www.youtube.com/")
            logger.info("Berada di root YouTube, menunggu...")
            time.sleep(10)

            for kw in keyword:
                tag = kw.replace(" ", "+")
                logger.info("--- Menjelajahi keyword: %s ---", kw)

                page.goto(f"https://www.youtube.com/results?search_query={tag}")
                time.sleep(5)

                links_found: set[str] = set()
                retry_scroll = 0

                while len(links_found) < target_post and retry_scroll < max_scroll:
                    for el in page.query_selector_all("a"):
                        if len(links_found) >= target_post:
                            break
                        href = el.get_attribute("href")
                        if not href:
                            continue
                        if "/watch" in href:
                            match = re.search(r"v=([^&]+)", href)
                            if match:
                                links_found.add(
                                    f"https://www.youtube.com/watch?v={match.group(1)}"
                                )

                    logger.info("  Sementara: %d URL ditemukan", len(links_found))

                    if len(links_found) < target_post:
                        try:
                            page.locator(
                                "ytd-search.style-scope.ytd-page-manager"
                            ).scroll_into_view_if_needed()
                        except Exception:
                            pass
                        human_scroll(page)
                        retry_scroll += 1
                    else:
                        break

                logger.info("Selesai '%s': %d URL ditemukan", kw, len(links_found))
                all_urls.extend(links_found)

            browser.close()

    logger.info("Total URL terkumpul: %d", len(all_urls))
    return all_urls


# ============================================================
# 6. DOWNLOAD — yt_dlp download dari URL hasil scraping
# ============================================================
def download_videos(
    urls: list[str],
    keyword_label: str,
    target_post: int,
    temp_dir: Path,
) -> list[dict]:
    """Download video dari URL menggunakan yt_dlp.

    Args:
        urls:          List URL video YouTube.
        keyword_label: Label keyword untuk field target_keyword di MongoDB.
        target_post:   Batas jumlah video yang didownload.
        temp_dir:      Direktori sementara untuk menyimpan file yang diunduh.

    Returns:
        List dokumen MongoDB-ready dengan file_path berisi path lokal sementara.
    """
    batch_id = str(uuid.uuid4())
    scraped_at_iso = datetime.now().isoformat()
    documents: list[dict] = []

    ydl_opts: dict = {
        "outtmpl": str(temp_dir / "%(id)s.%(ext)s"),
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "logtostderr": True,
        "logger": _YdlLogger(),
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # type: ignore[arg-type]
        for i, link in enumerate(urls[:target_post]):
            logger.info(
                "Mendownload %d/%d: %s", i + 1, min(len(urls), target_post), link
            )
            try:
                info = ydl.extract_info(link, download=True)
            except Exception as e:
                logger.warning("Gagal download %s: %s", link, e)
                continue

            if not info:
                continue

            unique_id = f"youtube_{info.get('id')}"
            local_path = str(Path(ydl.prepare_filename(info)).with_suffix(".mp4"))

            upload_date = info.get("upload_date")
            published_at = None
            if upload_date:
                try:
                    published_at = datetime.strptime(upload_date, "%Y%m%d").isoformat()
                except ValueError:
                    pass

            documents.append({
                "batch_id":       batch_id,
                "platform":       "youtube",
                "target_keyword": keyword_label,
                "scraped_at":     scraped_at_iso,
                "unique_id":      unique_id,
                "url":            info.get("webpage_url"),
                "type":           "video",
                "caption":        info.get("title"),
                "published_at":   published_at,
                "file_path":      [local_path],  # lokal sementara — diganti MinIO di upload_and_save()
                "duration":       info.get("duration"),
                "creator": {
                    "username": info.get("uploader"),
                    "user_id":  info.get("channel_id"),
                },
                "engagement": {
                    "like_count":    info.get("like_count"),
                    "comment_count": info.get("comment_count"),
                    "share_count":   None,
                    "view_count":    info.get("view_count"),
                    "saved_count":   None,
                    "repost_count":  None,
                },
            })
            logger.info("Dokumen ditambahkan: %s", unique_id)

    logger.info("Download selesai. Total dokumen: %d", len(documents))
    return documents


# ============================================================
# 7. UPLOAD MINIO + SAVE MONGODB (async)
# ============================================================
async def upload_and_save(documents: list[dict]) -> dict:
    """Upload file lokal ke MinIO dan simpan metadata ke MongoDB.

    Args:
        documents: List dokumen dengan file_path berisi path lokal sementara.

    Returns:
        Dict hasil insert MongoDB (status, count, ids).
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
                logger.warning("File lokal tidak ditemukan, skip: %s", local_path)
                continue

            object_name = f"crawl/youtube/{unique_id}.mp4"
            result = await save_from_local(
                source=local_path,
                destination=object_name,
            )
            if result.get("status") == "success":
                minio_paths.append(result["path"])
            else:
                logger.warning(
                    "Upload gagal untuk %s: %s",
                    local_file.name,
                    result.get("message"),
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
    logger.info(
        "Berhasil disimpan! Count: %d | IDs (sample): %s...",
        result.get("count", 0),
        result.get("ids", [])[:3],
    )

    await disconnect_mongo()
    logger.info("Koneksi MongoDB ditutup.")

    return result


# ============================================================
# 8. ENTRY POINT — Satu-satunya print() ada di sini (JSON murni)
# ============================================================
if __name__ == "__main__":
    # Safety net: redirect sys.stdout → sys.stderr sebelum semua eksekusi.
    _real_stdout = sys.stdout
    sys.stdout = sys.stderr

    parser = argparse.ArgumentParser(
        description="YouTube Crawler — Scrape dan download video YouTube via Playwright + yt_dlp",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--keyword",     nargs="+", required=True,
                        help="Daftar keyword pencarian")
    parser.add_argument("--target_post", type=int,  required=True,
                        help="Jumlah target video")
    parser.add_argument("--max_scroll",  type=int,  default=10,
                        help="Jumlah maksimum scroll per keyword (default: 10)")
    args = parser.parse_args()

    logger.info("=== YouTube Crawler dimulai ===")
    logger.info(
        "Keyword: %s | target_post: %d | max_scroll: %d",
        args.keyword, args.target_post, args.max_scroll,
    )

    try:
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)
            logger.info("Temporary directory: %s", temp_dir)

            # Step 1: Scrape URL via Playwright
            urls = scrape_youtube(args.keyword, args.target_post, args.max_scroll)
            if not urls:
                raise RuntimeError("Tidak ada URL video yang ditemukan.")

            # Step 2: Download video via yt_dlp
            documents = download_videos(
                urls, " ".join(args.keyword), args.target_post, temp_dir
            )
            if not documents:
                raise RuntimeError("Tidak ada video yang berhasil didownload.")

            # Step 3: Upload MinIO, simpan MongoDB
            response = asyncio.run(upload_and_save(documents))

        logger.info("=== Crawler selesai dengan sukses ===")
        sys.stdout = _real_stdout
        print(json.dumps(response, default=str))
        sys.exit(0)

    except Exception as exc:
        logger.error("Eksekusi gagal: %s", exc, exc_info=True)
        sys.stdout = _real_stdout
        print(json.dumps({"status": "error", "message": str(exc)}))
        sys.exit(1)
