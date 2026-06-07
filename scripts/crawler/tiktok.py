""" Cara eksekusi yang benar sebagai subprocess dari AI Agent:

import subprocess, json, sys

result = subprocess.run(
	["python", "-m", "scripts.crawler.tiktok",
	 "--keyword", "komdigi", "--target_post", "20"],
	capture_output=True,
	text=True,
	cwd="<path-to-aitf-backend>"
)

response = json.loads(result.stdout)   # Dijamin JSON murni
logs      = result.stderr              # Semua log proses ada di sini
exit_code = result.returncode          # 0 = sukses, 1 = gagal
"""

import os
import sys
import json
import uuid
import asyncio
import logging
import tempfile
import argparse
import contextlib
import requests
import yt_dlp
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from apify_client import ApifyClient

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
    format="[tiktok] %(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,  # apify_client mengkonfigurasi root logger saat import; force=True memastikan basicConfig tidak jadi no-op
)
logger = logging.getLogger(__name__)


# ============================================================
# 2. HELPER
# ============================================================
@contextlib.contextmanager
def _stdout_to_stderr():
    """Redirect sys.stdout → sys.stderr selama blok ini aktif.

    ApifyClient mencetak progress ke stdout pada beberapa path sehingga
    context manager ini menjamin tidak ada byte yang mencapai stdout.
    """
    old = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = old


# ============================================================
# 3. KONSTANTA
# ============================================================
load_dotenv()
APIFY_API_FREE = os.getenv("APIFY_API_FREE")
APIFY_API_PREMIUM = os.getenv("APIFY_API_PREMIUM")
COLLECTION_NAME = "social_media_posts"


# ============================================================
# 3. SCRAPING + DOWNLOAD (synchronous)
# ============================================================
def scrape_tiktok(keyword: list[str], target_post: int, temp_dir: Path) -> list[dict]:
    """Jalankan Apify actor, download video/slideshow ke temp_dir, kembalikan dokumen mentah.

    Args:
            keyword:     Daftar keyword pencarian TikTok.
            target_post: Jumlah target post per keyword.
            temp_dir:    Direktori sementara untuk menyimpan file yang diunduh.

    Returns:
            List dokumen dengan field file_path berisi path lokal sementara.

    Raises:
            Exception: Jika Apify actor gagal dipanggil.
    """
    api_key = APIFY_API_FREE
    if not api_key:
        raise RuntimeError("APIFY_API_FREE harus diset di .env")
    client = ApifyClient(api_key)
    run_input = {
        "searchQueries": keyword,
        "resultsPerPage": target_post,
        "shouldDownloadVideos": False,
    }

    logger.info("Menjalankan Apify actor untuk keyword: %s", keyword)
    with _stdout_to_stderr():
        run = client.actor("GdWCkxBtKWOsKjdch").call(run_input=run_input)
    if not run:
        raise RuntimeError("Apify actor tidak mengembalikan run object (None). Cek token dan quota.")
    dataset_id = run["defaultDatasetId"]
    logger.info("Actor selesai. Dataset ID: %s", dataset_id)

    batch_id = str(uuid.uuid4())
    scraped_at_iso = datetime.now().isoformat()
    documents: list[dict] = []

    class _YdlLogger:
        def debug(self, _: str) -> None: pass
        def info(self, _: str) -> None: pass
        def warning(self, msg: str) -> None: logger.warning("[yt_dlp] %s", msg)
        def error(self, msg: str) -> None: logger.error("[yt_dlp] %s", msg)

    ydl_opts: dict = {
        "outtmpl": str(temp_dir / "%(id)s.%(ext)s"),
        "format": "best",
        "quiet": True,
        "no_warnings": True,
        "logtostderr": True,   # arahkan _out_files.out ke stderr, bukan stdout
        "logger": _YdlLogger(),  # semua output yt_dlp melalui logger kita
    }

    with _stdout_to_stderr():
        items = list(client.dataset(dataset_id).iterate_items())

    for index, item in enumerate(items):
        video_url = item.get("webVideoUrl", "")
        is_slideshow = item.get("isSlideshow", False)
        unique_id = f"tiktok_{item.get('id')}"
        file_paths: list[str] = []
        content_type = "text"

        if is_slideshow:
            content_type = "multipleImage"
            slideshow_links = item.get("slideshowImageLinks", [])
            slide_dir = temp_dir / unique_id
            slide_dir.mkdir(parents=True, exist_ok=True)

            for i, link_obj in enumerate(slideshow_links):
                img_url = link_obj.get("downloadLink")
                if not img_url:
                    continue
                try:
                    img_res = requests.get(img_url, timeout=10)
                    if img_res.status_code == 200:
                        img_path = slide_dir / f"image_{i}.jpeg"
                        img_path.write_bytes(img_res.content)
                        file_paths.append(str(img_path))
                        logger.info(
                            "Slideshow %s: gambar %d berhasil didownload.", unique_id, i)
                except Exception as e:
                    logger.warning(
                        "Gagal download slideshow image %d untuk %s: %s", i, unique_id, e)

        elif video_url:
            content_type = "video" if "/video/" in video_url else "text"
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(video_url, download=True)
                    if info:
                        filename = ydl.prepare_filename(info)
                        file_paths.append(str(Path(filename)))
                        logger.info(
                            "Video %d berhasil didownload: %s", index, video_url)
            except Exception as e:
                logger.warning("Gagal download video %d (%s): %s",
                               index, video_url, e)

        documents.append({
            "batch_id":       batch_id,
            "platform":       "tiktok",
            "source":         "keyword_crawl",
            "target_keyword": item.get("input"),
            "scraped_at":     scraped_at_iso,
            "unique_id":      unique_id,
            "url":            video_url,
            "type":           content_type,
            "caption":        item.get("text"),
            "published_at":   item.get("createTimeISO"),
            "file_path":      file_paths,  # lokal sementara — diganti MinIO di upload_and_save()
            "cover_url":      item.get("videoMeta", {}).get("coverUrl") or item.get("videoMeta", {}).get("originalCoverUrl") or "",
            "duration":       item.get("videoMeta", {}).get("duration"),
            "creator": {
                "username": item.get("authorMeta", {}).get("name"),
                "user_id":  item.get("authorMeta", {}).get("id"),
            },
            "engagement": {
                "like_count":    item.get("diggCount"),
                "comment_count": item.get("commentCount"),
                "share_count":   item.get("shareCount"),
                "view_count":    item.get("playCount"),
                "saved_count":   item.get("collectCount"),
                "repost_count":  item.get("repostCount"),
            },
        })

    logger.info("Scraping selesai. Total dokumen: %d", len(documents))
    return documents


# ============================================================
# 4. UPLOAD MINIO + SAVE MONGODB (async)
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
        is_slideshow = doc["type"] == "multipleImage"

        for idx, local_path in enumerate(local_paths):
            local_file = Path(local_path)
            if not local_file.exists():
                logger.warning(
                    "File lokal tidak ditemukan, skip: %s", local_path)
                continue

            ext = local_file.suffix.lstrip(".")
            if is_slideshow:
                object_name = f"crawl/tiktok/{unique_id}/{idx}.jpeg"
            else:
                object_name = f"crawl/tiktok/{unique_id}.{ext}"

            result = await save_from_local(
                source=local_path,
                destination=object_name,
            )
            if result.get("status") == "success":
                minio_paths.append(result["path"])
            else:
                logger.warning("Upload gagal untuk %s: %s",
                               local_file.name, result.get("message"))

        doc["file_path"] = minio_paths

    await disconnect_minio()
    logger.info("Koneksi MinIO ditutup.")

    logger.info("Menginisialisasi koneksi MongoDB...")
    await connect_mongo()

    logger.info("Menyimpan %d dokumen ke collection '%s'...",
                len(documents), COLLECTION_NAME)
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
# 5. ENTRY POINT — Satu-satunya print() ada di sini (JSON murni)
# ============================================================
if __name__ == "__main__":
    # Safety net: redirect sys.stdout → sys.stderr sebelum semua eksekusi.
    # Ini menangkap sisa output yang lolos dari force=True basicConfig dan _YdlLogger.
    _real_stdout = sys.stdout
    sys.stdout = sys.stderr

    parser = argparse.ArgumentParser(
        description="TikTok Crawler — Scrape post dari TikTok via Apify",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--keyword",     nargs="+",
                        required=True, help="Daftar keyword pencarian")
    parser.add_argument("--target_post", type=int,
                        required=True, help="Jumlah target post per keyword")
    args = parser.parse_args()

    logger.info("=== TikTok Crawler dimulai ===")
    logger.info("Target: %s | target_post: %d", args.keyword, args.target_post)

    try:
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)
            logger.info("Temporary directory: %s", temp_dir)

            # Step 1: Scraping + download via Apify & yt_dlp
            documents = scrape_tiktok(args.keyword, args.target_post, temp_dir)

            if not documents:
                raise RuntimeError(
                    "Scraping selesai namun tidak ada post yang ditemukan.")

            # Step 2: Upload MinIO, simpan MongoDB
            response = asyncio.run(upload_and_save(documents))

        # Step 3: Output JSON murni ke STDOUT — satu-satunya print()
        logger.info("=== Crawler selesai dengan sukses ===")
        sys.stdout = _real_stdout
        print(json.dumps(response, default=str))
        sys.exit(0)

    except Exception as exc:
        logger.error("Eksekusi gagal: %s", exc, exc_info=True)
        sys.stdout = _real_stdout
        print(json.dumps({"status": "error", "message": str(exc)}))
        sys.exit(1)
