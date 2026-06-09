"""Instagram crawler via Apify (replaces Playwright-based instagram.py which fails on IG anti-bot).

Usage:
    python -m scripts.crawler.instagram_apify --keyword "judi online" --target_post 5

Output (stdout, pure JSON):
    {"extracted_data": [{platform, url, type, caption, file_path, cover_url, creator, ...}, ...]}
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

from apify_client import ApifyClient
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# Force UTF-8 stdout/stderr — output JSON sering punya emoji/non-ASCII
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Log ke stderr supaya stdout tetap JSON murni
logging.basicConfig(
    level=logging.INFO,
    format="[instagram-apify] %(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

load_dotenv()
# Token Apify universal (APIFY_API_TOKEN, akun sadam) dipakai untuk semua crawler
# Apify; APIFY_API_INSTAGRAM/PREMIUM/FREE hanya cadangan kompatibilitas.
APIFY_TOKEN = (
    os.getenv("APIFY_API_TOKEN")
    or os.getenv("APIFY_API_INSTAGRAM")
    or os.getenv("APIFY_API_PREMIUM")
    or os.getenv("APIFY_API_FREE")
)
INSTAGRAM_HASHTAG_ACTOR = "apify/instagram-hashtag-scraper"  # search by hashtag

VIDEO_EXTS = (".mp4", ".webm", ".mkv", ".mov", ".avi")


def scrape_instagram(keyword: str, target_post: int) -> list[dict]:
    """Call Apify Instagram actor and return normalized documents.

    Apify actor outputs items with fields like:
        - url, shortCode, type, caption, displayUrl, videoUrl, ownerUsername, ownerId
        - hashtags, mentions, commentsCount, likesCount, timestamp, images, videoUrl
    """
    if not APIFY_TOKEN:
        logger.error("APIFY_API_PREMIUM / APIFY_API_FREE belum diset di .env")
        return []

    client = ApifyClient(APIFY_TOKEN)

    # Hashtag-search expects keyword without leading "#"
    hashtag = keyword.lstrip("#").strip()
    if not hashtag:
        return []

    run_input = {
        "hashtags": [hashtag],
        "resultsLimit": target_post,
    }

    logger.info("Memanggil Apify actor %s untuk hashtag '%s' (limit %d)",
                INSTAGRAM_HASHTAG_ACTOR, hashtag, target_post)
    try:
        run = client.actor(INSTAGRAM_HASHTAG_ACTOR).call(run_input=run_input)
    except Exception as e:
        logger.error("Apify actor gagal: %s", e)
        return []

    if not run:
        logger.warning("Apify run mengembalikan None.")
        return []

    # apify_client >=3 mengembalikan objek Run (atribut snake_case);
    # versi lama mengembalikan dict ("defaultDatasetId"). Dukung keduanya.
    if isinstance(run, dict):
        dataset_id = run.get("defaultDatasetId")
    else:
        dataset_id = getattr(run, "default_dataset_id", None)
    if not dataset_id:
        logger.warning("Tidak ada defaultDatasetId di response actor.")
        return []

    items = list(client.dataset(dataset_id).iterate_items())
    logger.info("Actor mengembalikan %d item.", len(items))

    batch_id = str(uuid.uuid4())
    scraped_at_iso = datetime.now().isoformat()
    documents: list[dict] = []

    for item in items:
        post_url = item.get("url") or ""
        item_type = (item.get("type") or "").lower()  # "Image" | "Video" | "Sidecar"
        caption = item.get("caption") or ""
        display_url = item.get("displayUrl") or ""
        video_url = item.get("videoUrl") or ""
        owner_username = item.get("ownerUsername") or ""
        owner_id = item.get("ownerId") or ""

        # Map IG type → unified content_type
        if item_type == "video" or video_url:
            content_type = "video"
        elif item_type == "sidecar":
            content_type = "multipleImage"
        elif item_type == "image" or display_url:
            content_type = "image"
        else:
            content_type = "text"

        # Cover URL: prefer displayUrl (always image), fallback to first image in sidecar
        cover_url = display_url
        if not cover_url:
            sidecar_images = item.get("images") or []
            if sidecar_images:
                cover_url = sidecar_images[0] if isinstance(sidecar_images[0], str) else ""

        # file_path: just store the original CDN URLs (no local download for now)
        file_paths: list[str] = []
        if display_url:
            file_paths.append(display_url)
        if video_url:
            file_paths.append(video_url)

        documents.append({
            "batch_id":       batch_id,
            "platform":       "instagram",
            "source":         "keyword_crawl",
            "target_keyword": hashtag,
            "scraped_at":     scraped_at_iso,
            "unique_id":      f"instagram_{item.get('shortCode') or item.get('id') or uuid.uuid4().hex[:12]}",
            "url":            post_url,
            "type":           content_type,
            "caption":        caption,
            "published_at":   item.get("timestamp"),
            "file_path":      file_paths,
            "cover_url":      cover_url,
            "duration":       item.get("videoDuration"),
            "creator": {
                "username": owner_username,
                "user_id":  owner_id,
            },
            "engagement": {
                "like_count":    item.get("likesCount"),
                "comment_count": item.get("commentsCount"),
                "share_count":   None,
                "view_count":    item.get("videoViewCount"),
                "saved_count":   None,
                "repost_count":  None,
            },
        })

    return documents


def main() -> None:
    parser = argparse.ArgumentParser(description="Instagram crawler (Apify-based)")
    parser.add_argument("--keyword", required=True, help="Keyword/hashtag pencarian")
    parser.add_argument("--target_post", type=int, default=5, help="Jumlah post target")
    parser.add_argument("--max_scroll", type=int, default=3, help="Ignored (kompatibilitas dengan IG legacy)")
    args = parser.parse_args()

    try:
        documents = scrape_instagram(args.keyword, args.target_post)
        result = {"extracted_data": documents}
    except Exception as e:
        logger.error("Eksekusi gagal: %s", e)
        result = {"extracted_data": [], "error": str(e)}
        sys.stdout.write(json.dumps(result, ensure_ascii=False))
        sys.exit(1)

    # Output JSON murni ke stdout
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
