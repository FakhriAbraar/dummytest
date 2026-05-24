""" Cara eksekusi yang benar sebagai subprocess dari AI Agent:

import subprocess, json, sys

result = subprocess.run(
    ["python", "scripts/crawler/content-checker.py",
     "--url", "https://www.youtube.com/watch?v=6KP2W1djB6c",
               "https://x.com/user/status/123456"],
    capture_output=True,
    text=True,
    cwd="<path-to-aitf-backend>"
)

response = json.loads(result.stdout)   # Dijamin JSON murni
logs      = result.stderr              # Semua log proses ada di sini
exit_code = result.returncode          # 0 = sukses, 1 = gagal

CATATAN: Jalankan sebagai path (bukan -m) karena nama file mengandung tanda hubung.
"""

import re
import sys
import httpx
import json
import uuid
import asyncio
import logging
import tempfile
import argparse
import contextlib
import urllib.parse
import yt_dlp
from pathlib import Path
from datetime import datetime

# sys.path.insert WAJIB sebelum semua import app.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv  # noqa: E402

from app.db.minio import connect_minio, disconnect_minio  # noqa: E402
from app.db.mongo import connect_mongo, disconnect_mongo  # noqa: E402
from app.services.minio import save_from_local  # noqa: E402
from app.services.mongo import insert_many_data  # noqa: E402


# ============================================================
# 1. LOGGING — Seluruh output log diarahkan ke STDERR
#    sehingga STDOUT tetap bersih untuk JSON akhir.
# ============================================================
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[content-checker] %(asctime)s [%(levelname)s] %(message)s",
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


def _detect_platform(url: str) -> str:
    """Deteksi nama platform dari URL."""
    if "instagram.com" in url:
        return "instagram"
    if "tiktok.com" in url:
        return "tiktok"
    if "x.com" in url or "twitter.com" in url:
        return "twitter"
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    if "detik.com" in url:
        return "detik"
    if "cnnindonesia.com" in url:
        return "cnnindonesia"
    return urllib.parse.urlparse(url).netloc


def _build_unique_id(url: str, platform: str) -> str:
    """Bangun unique_id bermakna dari URL dan bersihkan untuk Windows OS."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    
    # Kita benerin Regex-nya biar otomatis berhenti kalau ketemu '?' atau '#'
    patterns: dict[str, tuple[str, str]] = {
        "instagram": (r"p/([^/?#]+)", "instagram_{}"),
        "tiktok":    (r"video/([^/?#]+)", "tiktok_{}"),
        "twitter":   (r"status/([^/?#]+)", "twitter_{}"),
        "youtube":   (r"(?:watch\?v=|youtu\.be/)([^&/?#]+)", "youtube_{}"),
    }
    
    if platform in patterns:
        regex, fmt = patterns[platform]
        match = re.search(regex, url)
        if match:
            raw_id = match.group(1)
            # SANITASI ABSOLUT: Buang semua karakter selain huruf, angka, min, dan underscore
            safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '', raw_id)
            return fmt.format(safe_id)
            
    return f"{platform}_{timestamp}"

# ============================================================
# 3. KONSTANTA
# ============================================================
load_dotenv()
COLLECTION_NAME = "social_media_posts"

def _fallback_extract(url: str, platform: str, batch_id: str, scraped_at: str, unique_id: str, temp_dir: Path | None = None) -> dict | None:
    """Fallback scraper jika yt-dlp gagal (khusus untuk gambar/teks murni)."""

    def _download_images(image_urls: list[str], plat: str, uid: str) -> list[str]:
        """Download gambar dari CDN ke disk lokal agar bisa di-upload ke MinIO."""
        if not temp_dir or not image_urls:
            return []
        local_paths: list[str] = []
        img_dir = temp_dir / uid
        img_dir.mkdir(parents=True, exist_ok=True)
        for idx, img_url in enumerate(image_urls):
            try:
                with httpx.Client(timeout=15.0, follow_redirects=True) as dl_client:
                    resp = dl_client.get(img_url)
                    if resp.status_code == 200:
                        # Deteksi ekstensi dari content-type atau URL
                        ct = resp.headers.get("content-type", "")
                        if "png" in ct:
                            ext = "png"
                        elif "webp" in ct:
                            ext = "webp"
                        elif "gif" in ct:
                            ext = "gif"
                        else:
                            ext = "jpg"
                        fname = img_dir / f"{idx}.{ext}"
                        fname.write_bytes(resp.content)
                        local_paths.append(str(fname))
                        logger.info("  [+] Image downloaded: %s (%d bytes)", fname.name, len(resp.content))
                    else:
                        logger.warning("  [-] Image download gagal (HTTP %d): %s", resp.status_code, img_url[:80])
            except Exception as e:
                logger.error("  [-] Image download error: %s", e)
        return local_paths
    
    if platform == "twitter":
        # Trik vxtwitter: Ubah x.com/twitter.com jadi api.vxtwitter.com untuk dapet JSON murni
        api_url = re.sub(r'(https?://)(www\.)?(twitter\.com|x\.com)', r'\1api.vxtwitter.com', url)
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(api_url)
                if resp.status_code == 200:
                    data = resp.json()
                    media_urls = data.get("mediaURLs", [])
                    
                    # Download gambar ke disk agar bisa di-upload ke MinIO
                    image_only_urls = [u for u in media_urls if not u.endswith(".mp4")]
                    downloaded_paths = _download_images(image_only_urls, platform, unique_id)
                    
                    return {
                        "batch_id": batch_id,
                        "platform": platform,
                        "source": "vxtwitter_api",
                        "target_keyword": None,
                        "scraped_at": scraped_at,
                        "unique_id": unique_id,
                        "url": url,
                        "type": "image" if len(media_urls) == 1 else ("multipleImage" if len(media_urls) > 1 else "text"),
                        "caption": data.get("text", ""),
                        "thumbnail_url": media_urls[0] if media_urls else "",
                        "published_at": data.get("date"),
                        "file_path": downloaded_paths,
                        "duration": None,
                        "creator": {
                            "username": data.get("user_screen_name"),
                            "user_id": data.get("user_screen_name"),
                        },
                        "engagement": {
                            "like_count": data.get("likes"),
                            "comment_count": data.get("replies"),
                            "share_count": data.get("retweets"),
                            "view_count": None,
                            "saved_count": None,
                            "repost_count": data.get("retweets"),
                        },
                    }
        except Exception as e:
            logger.error("Fallback vxtwitter gagal: %s", e)

    elif platform == "instagram":
        # oEmbed API — official Instagram endpoint, jauh lebih stabil daripada ?__a=1 yang udah diblock Meta
        clean_url = url.split("?")[0].rstrip("/")
        oembed_url = f"https://i.instagram.com/api/v1/oembed/?url={clean_url}"
        
        try:
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                resp = client.get(oembed_url)
                if resp.status_code == 200:
                    data = resp.json()
                    
                    thumbnail = data.get("thumbnail_url", "")
                    author = data.get("author_name", "")
                    title = data.get("title", "")
                    
                    # Download thumbnail ke disk agar bisa di-upload ke MinIO
                    image_urls = [thumbnail] if thumbnail else []
                    downloaded_paths = _download_images(image_urls, platform, unique_id)
                    
                    return {
                        "batch_id": batch_id,
                        "platform": platform,
                        "source": "ig_oembed_api",
                        "target_keyword": None,
                        "scraped_at": scraped_at,
                        "unique_id": unique_id,
                        "url": clean_url,
                        "type": "image" if thumbnail else "text",
                        "caption": title or f"Post by {author}",
                        "thumbnail_url": thumbnail,
                        "published_at": None,
                        "file_path": downloaded_paths,
                        "duration": None,
                        "creator": {
                            "username": author,
                            "user_id": str(data.get("author_id", "")),
                        },
                        "engagement": {
                            "like_count": None,
                            "comment_count": None,
                            "share_count": None,
                            "view_count": None,
                            "saved_count": None,
                            "repost_count": None,
                        },
                    }
                else:
                    logger.error("IG oEmbed gagal (HTTP %d)", resp.status_code)
        except Exception as e:
            logger.error("Fallback IG oEmbed gagal: %s", e)

    return None

# ============================================================
# 4. EKSTRAKSI KONTEN — yt_dlp sebagai unified extractor
# ============================================================
def extract_content(
    url: str,
    temp_dir: Path,
    batch_id: str,
    scraped_at: str,
) -> dict | None:
    platform  = _detect_platform(url)
    unique_id = _build_unique_id(url, platform)

    url_dir = temp_dir / unique_id
    url_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "outtmpl":             str(url_dir / "%(id)s.%(ext)s"),
        "format":              "bestvideo+bestaudio/best" if platform == "youtube" else "best",
        "merge_output_format": "mp4",
        "quiet":               True,
        "no_warnings":         True,
        "logtostderr":         True,
        "logger":              _YdlLogger(),
    }

    info                   = None
    local_paths: list[str] = []

    try:
        with _stdout_to_stderr():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # type: ignore[arg-type]
                info = ydl.extract_info(url, download=True)
                if info:
                    entries = info.get("entries") if info.get("_type") == "playlist" else [info]
                    for entry in (entries or []):
                        if not entry:
                            continue
                        fname = Path(ydl.prepare_filename(entry))  # type: ignore[arg-type]
                        for candidate in [fname.with_suffix(".mp4"), fname]:
                            if candidate.exists():
                                local_paths.append(str(candidate))
                                break
    except Exception as e:
        logger.warning("Download gagal (%s), mencoba metadata saja: %s", url, e)

        if info is None:
            try:
                meta_opts = {**ydl_opts, "skip_download": True}
                with _stdout_to_stderr():
                    with yt_dlp.YoutubeDL(meta_opts) as ydl:  # type: ignore[arg-type]
                        info = ydl.extract_info(url, download=False)
            except Exception as e2:
                logger.warning("Gagal mengekstrak metadata %s: %s", url, e2)

    if not info:
        logger.warning("yt-dlp total gagal, mencoba fallback extractor untuk URL: %s", url)
        
        # Panggil Fallback
        fallback_data = _fallback_extract(url, platform, batch_id, scraped_at, unique_id, temp_dir)
        if fallback_data:
            logger.info("Fallback berhasil diekstrak: %s (%s)", unique_id, fallback_data["type"])
            return fallback_data
            
        logger.warning("URL benar-benar mati/gagal diekstrak oleh semua metode: %s", url)
        return None

    # Cek file yang berhasil di-download yt-dlp
    if not local_paths:
        local_paths = [str(f) for f in url_dir.iterdir() if f.is_file()]

    # KRITIS: yt-dlp sering dapet metadata (caption/title) tapi GAGAL download file
    # gambar dari IG/Twitter. Kalau ini terjadi, panggil fallback extractor
    # yang bisa download gambar via API platform.
    _visual_platforms = {"instagram", "twitter", "tiktok"}
    if not local_paths and platform in _visual_platforms:
        logger.warning(
            "yt-dlp dapet metadata tapi 0 file media di-download untuk %s. "
            "Mencoba fallback extractor...", platform
        )
        fallback_data = _fallback_extract(url, platform, batch_id, scraped_at, unique_id, temp_dir)
        if fallback_data:
            # Gabungin: pakai caption dari yt-dlp (biasanya lebih lengkap) + file dari fallback
            ydl_caption = info.get("title") or info.get("description") or ""
            fallback_caption = fallback_data.get("caption", "")
            # Ambil caption terpanjang (yang paling informatif)
            if len(ydl_caption) > len(fallback_caption):
                fallback_data["caption"] = ydl_caption
            logger.info(
                "Fallback berhasil! Tipe: %s, File: %d",
                fallback_data["type"], len(fallback_data.get("file_path", []))
            )
            return fallback_data
        logger.warning("Fallback juga gagal — lanjut dengan data yt-dlp tanpa media.")

    if len(local_paths) > 1:
        content_type = "multipleImage"
    elif len(local_paths) == 1:
        ext = Path(local_paths[0]).suffix.lower().lstrip(".")
        content_type = "video" if ext in {"mp4", "webm", "mkv", "mov"} else "image"
    else:
        content_type = "text" 

    upload_date  = info.get("upload_date")
    published_at = None
    if upload_date:
        try:
            published_at = datetime.strptime(upload_date, "%Y%m%d").isoformat()
        except ValueError:
            pass

    logger.info(
        "Berhasil diekstrak: %s (%s, %d file)", unique_id, content_type, len(local_paths)
    )

    return {
        "batch_id":       batch_id,
        "platform":       platform,
        "source":         "direct_url",
        "target_keyword": None,
        "scraped_at":     scraped_at,
        "unique_id":      unique_id,
        "url":            info.get("webpage_url") or url,
        "type":           content_type,
        "caption":        info.get("title") or info.get("description") or "",
        "thumbnail_url":  info.get("thumbnail") or "",
        "published_at":   published_at,
        "file_path":      local_paths,  
        "duration":       info.get("duration"),
        "creator": {
            "username": info.get("uploader") or info.get("uploader_id"),
            "user_id":  info.get("channel_id") or info.get("uploader_id"),
        },
        "engagement": {
            "like_count":    info.get("like_count"),
            "comment_count": info.get("comment_count"),
            "share_count":   info.get("repost_count"),
            "view_count":    info.get("view_count"),
            "saved_count":   None,
            "repost_count":  info.get("repost_count"),
        },
    }


# ============================================================
# 5. UPLOAD MINIO + SAVE MONGODB (async)
# ============================================================
async def upload_and_save(documents: list[dict]) -> dict:
    await connect_minio()
    logger.info("Koneksi MinIO berhasil.")

    for doc in documents:
        unique_id   = doc["unique_id"]
        platform    = doc["platform"]
        local_paths = doc.get("file_path", [])
        minio_paths: list[str] = []
        is_multi    = doc["type"] == "multipleImage"

        for idx, local_path in enumerate(local_paths):
            local_file = Path(local_path)
            if not local_file.exists():
                logger.warning("File lokal tidak ditemukan, skip: %s", local_path)
                continue

            ext = local_file.suffix.lstrip(".")
            object_name = (
                f"crawl/{platform}/{unique_id}/{idx}.{ext}" if is_multi
                else f"crawl/{platform}/{unique_id}.{ext}"
            )
            result = await save_from_local(source=local_path, destination=object_name)
            if result.get("status") == "success":
                minio_paths.append(result["path"])
            else:
                logger.warning("Upload gagal %s: %s", object_name, result.get("message"))

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

    result["extracted_data"] = documents

    return result


# ============================================================
# 6. ENTRY POINT
# ============================================================
if __name__ == "__main__":
    _real_stdout = sys.stdout
    sys.stdout   = sys.stderr

    parser = argparse.ArgumentParser(
        description="Content Checker — Ekstrak konten media sosial dari URL langsung ke MinIO + MongoDB",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--url", nargs="+", required=True,
        help="Daftar URL konten media sosial yang akan diekstrak",
    )
    args = parser.parse_args()

    logger.info("=== Content Checker dimulai ===")
    logger.info("URLs: %d", len(args.url))

    batch_id   = str(uuid.uuid4())
    scraped_at = datetime.now().isoformat()

    try:
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir  = Path(tmp)
            logger.info("Temporary directory: %s", temp_dir)

            documents: list[dict] = []
            for url in args.url:
                doc = extract_content(url, temp_dir, batch_id, scraped_at)
                if doc:
                    documents.append(doc)
                else:
                    logger.warning("URL dilewati (gagal diekstrak): %s", url)

            if not documents:
                raise RuntimeError("Tidak ada konten yang berhasil diekstrak.")

            response = asyncio.run(upload_and_save(documents))

        logger.info("=== Content Checker selesai ===")
        sys.stdout = _real_stdout
        print(json.dumps(response, default=str))
        sys.exit(0)

    except Exception as exc:
        logger.error("Eksekusi gagal: %s", exc, exc_info=True)
        sys.stdout = _real_stdout
        print(json.dumps({"status": "error", "message": str(exc)}))
        sys.exit(1)