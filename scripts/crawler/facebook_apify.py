"""Facebook crawler via Apify (danek/facebook-search-scraper).

- Foto  : CDN URL dari field images[].uri — request langsung (signed URL, tidak perlu login).
- Reels : yt-dlp download → upload MinIO (CDN video publik).
- Teks  : caption saja, tidak ada file.

Usage:
    python -m scripts.crawler.facebook_apify --keyword "PLN" --target_post 10
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

import requests
import yt_dlp
from apify_client import ApifyClient
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[facebook-apify] %(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)
logger = logging.getLogger(__name__)

load_dotenv()

APIFY_TOKEN = (
    os.getenv("APIFY_API_TOKEN")
    or os.getenv("APIFY_API_PREMIUM")
    or os.getenv("APIFY_API_FREE")
)
FACEBOOK_ACTOR = os.getenv("FACEBOOK_ACTOR", "danek/facebook-search-scraper")
COLLECTION_NAME = "social_media_posts"


@contextlib.contextmanager
def _stdout_to_stderr():
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


def _is_reel(url: str) -> bool:
    return "/reel/" in url or "fb.watch" in url or "/videos/" in url


def _download_reel(post_url: str, temp_dir: Path, unique_id: str) -> str | None:
    """Download Reel via yt-dlp ke temp_dir, return path lokal atau None."""
    out_path = temp_dir / f"{unique_id}.mp4"
    ydl_opts = {
        "outtmpl": str(out_path.with_suffix("")),
        "format": "best",
        "quiet": True,
        "no_warnings": True,
        "logtostderr": True,
        "logger": _YdlLogger(),
        "merge_output_format": "mp4",
    }
    try:
        with _stdout_to_stderr():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([post_url])
        # yt-dlp kadang tambah ekstensi sendiri
        for candidate in [out_path, out_path.with_suffix(".mp4")]:
            if candidate.exists():
                logger.info("Reel berhasil didownload: %s", candidate.name)
                return str(candidate)
        # Cari file apapun yang dihasilkan di temp_dir dengan prefix unique_id
        matches = list(temp_dir.glob(f"{unique_id}*"))
        if matches:
            return str(matches[0])
    except Exception as e:
        logger.warning("yt-dlp gagal untuk %s: %s", post_url, e)
    return None


def scrape_facebook(keyword: str, target_post: int, temp_dir: Path) -> list[dict]:
    if not APIFY_TOKEN:
        logger.error("APIFY_API_TOKEN belum diset di .env")
        return []

    client = ApifyClient(APIFY_TOKEN)

    run_input = {
        "query": keyword,
        "maxResults": target_post,
    }

    logger.info("Memanggil Apify actor '%s' keyword='%s' limit=%d",
                FACEBOOK_ACTOR, keyword, target_post)
    try:
        with _stdout_to_stderr():
            run = client.actor(FACEBOOK_ACTOR).call(run_input=run_input)
    except Exception as e:
        logger.error("Apify actor gagal: %s", e)
        return []

    if not run:
        logger.warning("Apify run mengembalikan None.")
        return []

    dataset_id = run.get("defaultDatasetId") if isinstance(run, dict) else run.default_dataset_id
    if not dataset_id:
        logger.warning("Tidak ada defaultDatasetId.")
        return []

    with _stdout_to_stderr():
        items = list(client.dataset(dataset_id).iterate_items())

    logger.info("Actor mengembalikan %d item mentah.", len(items))

    batch_id = str(uuid.uuid4())
    scraped_at_iso = datetime.now().isoformat()
    documents: list[dict] = []

    for item in items:
        post_url = item.get("url") or item.get("postUrl") or ""
        text = (
            item.get("message")
            or item.get("text")
            or item.get("story")
            or ""
        )

        if not text and not post_url:
            continue

        author = item.get("user") or item.get("author") or {}
        if isinstance(author, str):
            username, user_id = author, ""
        else:
            username = (
                author.get("name") or author.get("username")
                or item.get("pageName") or ""
            )
            user_id = str(
                author.get("id") or author.get("userId")
                or item.get("userId") or item.get("pageId") or ""
            )

        post_id = item.get("postId") or item.get("id") or uuid.uuid4().hex[:12]
        unique_id = f"facebook_{post_id}"

        # --- Media ---
        file_paths: list[str] = []
        cover_url = ""
        content_type = "text"

        # Foto: ambil CDN URL dari field images[].uri
        images = item.get("images") or []
        for img in images:
            uri = img.get("uri") or img.get("url") or (img if isinstance(img, str) else "")
            if uri:
                file_paths.append(uri)
        if file_paths:
            cover_url = file_paths[0]
            content_type = "image" if len(file_paths) == 1 else "multipleImage"

        # Reels / Video: yt-dlp download
        if post_url and _is_reel(post_url):
            # Simpan thumbnail dari images[].uri sebelum file_paths ditimpa video
            reel_thumbnail = cover_url
            local_path = _download_reel(post_url, temp_dir, unique_id)
            if local_path:
                file_paths = [local_path]
                cover_url = reel_thumbnail  # thumbnail tetap dari gambar actor
                content_type = "video"
            else:
                # Fallback: tetap text-only kalau yt-dlp gagal
                logger.warning("Reel download gagal, lanjut text-only: %s", post_url)
                if not file_paths:
                    content_type = "text"

        documents.append({
            "batch_id":       batch_id,
            "platform":       "facebook",
            "source":         "keyword_crawl",
            "target_keyword": keyword,
            "scraped_at":     scraped_at_iso,
            "unique_id":      unique_id,
            "url":            post_url,
            "type":           content_type,
            "caption":        text,
            "published_at":   item.get("time") or item.get("timestamp") or item.get("publishedAt"),
            "file_path":      file_paths,
            "cover_url":      cover_url,
            "duration":       None,
            "creator": {
                "username": username,
                "user_id":  user_id,
            },
            "engagement": {
                "like_count":    item.get("likes") or item.get("likesCount") or item.get("reactionsCount"),
                "comment_count": item.get("comments") or item.get("commentsCount"),
                "share_count":   item.get("shares") or item.get("sharesCount"),
                "view_count":    item.get("views") or item.get("viewsCount"),
                "saved_count":   None,
                "repost_count":  None,
            },
        })

    logger.info("Dokumen valid: %d", len(documents))
    return documents


# ============================================================
# UPLOAD MINIO + SAVE MONGODB (async) — hanya untuk Reels (path lokal)
# ============================================================
async def upload_and_save(documents: list[dict]) -> dict:
    from app.db.minio import connect_minio, disconnect_minio
    from app.db.mongo import connect_mongo, disconnect_mongo
    from app.services.minio import save_from_local
    from app.services.mongo import insert_many_data

    await connect_minio()

    for doc in documents:
        if doc["type"] != "video":
            continue  # foto: CDN URL sudah cukup, tidak perlu upload

        local_paths = doc.get("file_path", [])
        minio_paths: list[str] = []

        for local_path in local_paths:
            local_file = Path(local_path)
            if not local_file.exists():
                logger.warning("File lokal tidak ditemukan: %s", local_path)
                continue
            ext = local_file.suffix.lstrip(".")
            object_name = f"crawl/facebook/{doc['unique_id']}.{ext}"
            result = await save_from_local(source=local_path, destination=object_name)
            if result.get("status") == "success":
                minio_paths.append(result["path"])
            else:
                logger.warning("Upload gagal %s: %s", object_name, result.get("message"))

        if minio_paths:
            doc["file_path"] = minio_paths

    await disconnect_minio()

    await connect_mongo()
    result = await insert_many_data(collection_name=COLLECTION_NAME, data_list=documents)
    result["extracted_data"] = documents
    logger.info("Disimpan %d dokumen.", result.get("count", 0))
    await disconnect_mongo()

    return result


# ============================================================
# ENTRY POINT
# ============================================================
def main() -> None:
    parser = argparse.ArgumentParser(description="Facebook crawler (Apify + yt-dlp untuk Reels)")
    parser.add_argument("--keyword", required=True)
    parser.add_argument("--target_post", type=int, default=10)
    args = parser.parse_args()

    _real_stdout = sys.stdout
    sys.stdout = sys.stderr

    logger.info("=== Facebook Crawler dimulai ===")

    try:
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)
            documents = scrape_facebook(args.keyword, args.target_post, temp_dir)

            if not documents:
                raise RuntimeError("Tidak ada post yang ditemukan.")

            response = asyncio.run(upload_and_save(documents))

        logger.info("=== Facebook Crawler selesai ===")
        sys.stdout = _real_stdout
        sys.stdout.write(json.dumps(response, default=str, ensure_ascii=False))
        sys.exit(0)

    except Exception as e:
        logger.error("Eksekusi gagal: %s", e)
        sys.stdout = _real_stdout
        sys.stdout.write(json.dumps({"extracted_data": [], "error": str(e)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
