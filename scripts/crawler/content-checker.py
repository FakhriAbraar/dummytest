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
    """Bangun unique_id bermakna dari URL (misal: twitter_<status_id>)."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    patterns: dict[str, tuple[str, str]] = {
        "instagram": (r"p/([^/]+)/", "instagram_{}"),
        "tiktok":    (r"video/([^/]+)", "tiktok_{}"),
        "twitter":   (r"status/([^/?]+)", "twitter_{}"),
        "youtube":   (r"(?:watch\?v=|youtu\.be/)([^&/]+)", "youtube_{}"),
    }
    if platform in patterns:
        regex, fmt = patterns[platform]
        match = re.search(regex, url)
        return fmt.format(match.group(1)) if match else f"{platform}_{timestamp}"
    return f"{platform}_{timestamp}"


# ============================================================
# 3. KONSTANTA
# ============================================================
load_dotenv()
COLLECTION_NAME = "social_media_posts"


# ============================================================
# 4. EKSTRAKSI KONTEN — yt_dlp sebagai unified extractor
# ============================================================
def extract_content(
    url: str,
    temp_dir: Path,
    batch_id: str,
    scraped_at: str,
) -> dict | None:
    """Ekstrak metadata + media dari URL menggunakan yt_dlp.

    Two-step strategy:
    1. Coba download penuh (media + metadata).
    2. Jika download gagal, fallback ke metadata-only (skip_download=True).
       Berguna untuk text-only tweets atau konten tanpa media.

    Args:
        url:        URL konten media sosial.
        temp_dir:   Direktori sementara root; subdirektori per URL dibuat di sini.
        batch_id:   UUID batch run saat ini.
        scraped_at: Timestamp ISO saat crawl dimulai.

    Returns:
        Dokumen MongoDB-ready, atau None jika ekstraksi gagal total.
    """
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

    # Step 1: Download penuh (media + metadata)
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

        # Step 2: Fallback metadata-only — untuk text-only tweets, platform tanpa media, dll.
        if info is None:
            try:
                meta_opts = {**ydl_opts, "skip_download": True}
                with _stdout_to_stderr():
                    with yt_dlp.YoutubeDL(meta_opts) as ydl:  # type: ignore[arg-type]
                        info = ydl.extract_info(url, download=False)
            except Exception as e2:
                logger.warning("Gagal mengekstrak metadata %s: %s", url, e2)

    if not info:
        logger.warning("URL dilewati — tidak ada info yang dapat diekstrak: %s", url)
        return None

    # Fallback scan url_dir jika prepare_filename tidak akurat (edge case yt_dlp)
    if not local_paths:
        local_paths = [str(f) for f in url_dir.iterdir() if f.is_file()]

    # Deteksi content type dari file yang berhasil didownload
    if len(local_paths) > 1:
        content_type = "multipleImage"
    elif len(local_paths) == 1:
        ext = Path(local_paths[0]).suffix.lower().lstrip(".")
        content_type = "video" if ext in {"mp4", "webm", "mkv", "mov"} else "image"
    else:
        content_type = "text"  # Text-only: tweet tanpa media, dll.

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
        "caption":        info.get("title") or info.get("description"),
        "published_at":   published_at,
        "file_path":      local_paths,  # lokal sementara — diganti MinIO di upload_and_save()
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
    """Upload file lokal ke MinIO dan simpan metadata ke MongoDB.

    Args:
        documents: List dokumen dari extract_content() dengan file_path lokal sementara.

    Returns:
        Dict hasil insert MongoDB (status, count, ids).
    """
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

    return result


# ============================================================
# 6. ENTRY POINT — Satu-satunya print() ada di sini (JSON murni)
# ============================================================
if __name__ == "__main__":
    # Safety net: redirect sys.stdout → sys.stderr sebelum semua eksekusi.
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
