"""Twitter/X crawler via Apify (replaces session-pool twitter.py).

Usage:
    python -m scripts.crawler.twitter_apify --keyword "judi online" --target_post 5
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

logging.basicConfig(
    level=logging.INFO,
    format="[twitter-apify] %(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

load_dotenv()
# Token Apify universal (akun sadam) diutamakan untuk semua crawler Apify.
APIFY_TOKEN = (
    os.getenv("APIFY_API_TOKEN")
    or os.getenv("APIFY_API_PREMIUM")
    or os.getenv("APIFY_API_FREE")
)
TWITTER_ACTOR = os.getenv("TWITTER_ACTOR", "quacker/twitter-scraper")


def scrape_twitter(keyword: str, target_post: int) -> list[dict]:
    if not APIFY_TOKEN:
        logger.error("APIFY_API_PREMIUM / APIFY_API_FREE belum diset di .env")
        return []

    client = ApifyClient(APIFY_TOKEN)

    run_input = {
        "searchTerms": [keyword],
        "maxItems": target_post,
        "lang": "id",
        "sort": "Top",
    }

    logger.info("Memanggil Apify actor %s untuk keyword '%s' (limit %d)",
                TWITTER_ACTOR, keyword, target_post)
    try:
        run = client.actor(TWITTER_ACTOR).call(run_input=run_input)
    except Exception as e:
        logger.error("Apify actor gagal: %s", e)
        return []

    if not run:
        logger.warning("Apify run mengembalikan None.")
        return []

    dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        logger.warning("Tidak ada defaultDatasetId di response actor.")
        return []

    items = list(client.dataset(dataset_id).iterate_items())

    # apidojo/tweet-scraper returns [{"noResults": true}] for free-plan users.
    # Filter out placeholder/error items.
    items = [
        it for it in items
        if not it.get("noResults") and (it.get("url") or it.get("twitterUrl") or it.get("text"))
    ]
    logger.info("Actor mengembalikan %d item valid.", len(items))

    if not items:
        logger.warning(
            "Twitter scraper tidak menghasilkan data. Actor 'apidojo/tweet-scraper' "
            "membutuhkan Apify paid plan. Upgrade Apify subscription untuk mengaktifkan Twitter."
        )

    batch_id = str(uuid.uuid4())
    scraped_at_iso = datetime.now().isoformat()
    documents: list[dict] = []

    for item in items:
        tweet_url = item.get("url") or item.get("twitterUrl") or ""
        text = item.get("text") or item.get("fullText") or ""

        author = item.get("author") or {}
        username = (
            author.get("userName")
            or author.get("username")
            or item.get("user", {}).get("screen_name")
            or ""
        )
        user_id = author.get("id") or author.get("userId") or item.get("user", {}).get("id_str") or ""

        # Media: apidojo returns extendedEntities.media or just media
        media_list = []
        extended = item.get("extendedEntities") or {}
        if extended.get("media"):
            media_list = extended["media"]
        elif item.get("media"):
            media_list = item["media"]

        file_paths: list[str] = []
        cover_url = ""
        for m in media_list:
            mtype = (m.get("type") or "").lower()
            if mtype == "photo":
                u = m.get("media_url_https") or m.get("mediaUrlHttps") or m.get("url") or ""
                if u:
                    file_paths.append(u)
                    if not cover_url:
                        cover_url = u
            elif mtype in {"video", "animated_gif"}:
                # Use the photo cover for video tweets
                cover = m.get("media_url_https") or m.get("mediaUrlHttps") or ""
                if cover and not cover_url:
                    cover_url = cover
                # Get best variant URL
                variants = (m.get("videoInfo") or {}).get("variants") or m.get("video_info", {}).get("variants") or []
                mp4_variants = [v for v in variants if (v.get("contentType") or v.get("content_type") or "").startswith("video/mp4")]
                if mp4_variants:
                    best = max(mp4_variants, key=lambda v: v.get("bitrate") or 0)
                    if best.get("url"):
                        file_paths.append(best["url"])

        # Determine type
        if any(p.endswith((".mp4", ".webm")) for p in file_paths):
            content_type = "video"
        elif len(file_paths) > 1:
            content_type = "multipleImage"
        elif len(file_paths) == 1:
            content_type = "image"
        else:
            content_type = "text"

        documents.append({
            "batch_id":       batch_id,
            "platform":       "twitter",
            "source":         "keyword_crawl",
            "target_keyword": keyword,
            "scraped_at":     scraped_at_iso,
            "unique_id":      f"twitter_{item.get('id') or item.get('rest_id') or uuid.uuid4().hex[:12]}",
            "url":            tweet_url,
            "type":           content_type,
            "caption":        text,
            "published_at":   item.get("createdAt") or item.get("created_at"),
            "file_path":      file_paths,
            "cover_url":      cover_url,
            "duration":       None,
            "creator": {
                "username": username,
                "user_id":  user_id,
            },
            "engagement": {
                "like_count":    item.get("likeCount") or item.get("favorite_count"),
                "comment_count": item.get("replyCount") or item.get("reply_count"),
                "share_count":   None,
                "view_count":    item.get("viewCount") or item.get("views"),
                "saved_count":   None,
                "repost_count":  item.get("retweetCount") or item.get("retweet_count"),
            },
        })

    return documents


def main() -> None:
    parser = argparse.ArgumentParser(description="Twitter crawler (Apify-based)")
    parser.add_argument("--keyword", required=True)
    parser.add_argument("--target_post", type=int, default=5)
    args = parser.parse_args()

    try:
        documents = scrape_twitter(args.keyword, args.target_post)
        result = {"extracted_data": documents}
    except Exception as e:
        logger.error("Eksekusi gagal: %s", e)
        result = {"extracted_data": [], "error": str(e)}
        sys.stdout.write(json.dumps(result, ensure_ascii=False))
        sys.exit(1)

    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
