""" Cara eksekusi yang benar sebagai subprocess dari AI Agent:

import subprocess, json, sys

result = subprocess.run(
    ["python", "scripts/crawler/screenshot-evidence.py",
     "--url", "https://x.com/i/status/123456", "https://www.instagram.com/p/abc123/"],

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
from pathlib import Path
from datetime import datetime

# sys.path.insert WAJIB sebelum semua import app.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv  # noqa: E402
from playwright.async_api import async_playwright  # noqa: E402

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
    format="[screenshot-evidence] %(asctime)s [%(levelname)s] %(message)s",
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


@contextlib.contextmanager
def _output_dir(path: str | None):
    """Yield output directory: pakai path jika diberikan, atau TemporaryDirectory."""
    if path:
        d = Path(path)
        d.mkdir(parents=True, exist_ok=True)
        yield d
    else:
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp)


def _detect_platform(url: str) -> str:
    """Deteksi nama platform dari URL."""
    if "instagram.com" in url:
        return "instagram"
    if "tiktok.com" in url:
        return "tiktok"
    if "x.com" in url or "twitter.com" in url:
        return "twitter"
    if "youtube.com" in url:
        return "youtube"
    if "detik.com" in url:
        return "detik"
    if "cnnindonesia.com" in url:
        return "cnnindonesia"
    return urllib.parse.urlparse(url).netloc


def get_unique_filename(url: str) -> str | None:
    """Ekstrak nama file unik yang bermakna dari URL konten media sosial.

    Mengembalikan string seperti 'twitter_<status_id>' atau 'instagram_<post_id>'.
    Mengembalikan None jika platform tidak dikenali.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    if "instagram.com" in url:
        match = re.search(r"p/([^/]+)/", url)
        return f"instagram_{match.group(1)}" if match else f"instagram_{timestamp}"

    if "tiktok.com" in url:
        match = re.search(r"video/([^/]+)", url)
        return f"tiktok_{match.group(1)}" if match else f"tiktok_{timestamp}"

    if "x.com" in url or "twitter.com" in url:
        match = re.search(r"status/([^/]+)", url)
        return f"twitter_{match.group(1)}" if match else f"twitter_{timestamp}"

    if "youtube.com" in url:
        match = re.search(r"watch\?v=([^&]+)", url)
        return f"youtube_{match.group(1)}" if match else f"youtube_{timestamp}"

    if "detik.com" in url:
        match = re.search(r"/(d-\d+)/", url)
        return f"detik_{match.group(1)}" if match else f"detik_{timestamp}"

    if "cnnindonesia.com" in url:
        match = re.search(r"/([\d-]+)/", url)
        return f"cnn_{match.group(1)}" if match else f"cnn_{timestamp}"

    return None


# ============================================================
# 3. KONSTANTA
# ============================================================
load_dotenv()
MINIO_PREFIX = "evidence/screenshots"


# ============================================================
# 4. SCREENSHOT — Playwright buka setiap URL dan ambil screenshot
# ============================================================
async def process_single_url(url: str, browser, output_dir: Path) -> dict | None:
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 720},
    )
    await context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    page = await context.new_page()

    try:
        logger.info("Memproses: %s", url)
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)

        # --- Per-platform edge case handling ---
        if "x.com" in url or "twitter.com" in url:
            await page.wait_for_selector(
                "span:has-text('Post')", state="visible", timeout=20000)
            await page.wait_for_timeout(3000)

        elif "instagram.com" in url:
            try:
                await page.wait_for_load_state("domcontentloaded")

                try:
                    await page.wait_for_selector(
                        'div[role="dialog"]', state="visible", timeout=15000)
                    await page.wait_for_timeout(3000)
                except Exception:
                    pass

                await page.evaluate("""
                    () => {
                        const closeSvg = document.querySelector('svg[aria-label="Close"]');
                        let isClicked = false;
                        if (closeSvg) {
                            const closeBtn = closeSvg.closest('div[role="button"], button') || closeSvg.parentElement;
                            if (closeBtn) {
                                closeBtn.click();
                                isClicked = true;
                            }
                        }
                        if (!isClicked) {
                            document.querySelectorAll('div[role="dialog"], div[aria-modal="true"]').forEach(el => {
                                el.style.setProperty('display', 'none', 'important');
                            });
                            document.querySelectorAll('div').forEach(el => {
                                const style = window.getComputedStyle(el);
                                if ((style.position === 'fixed' || style.position === 'absolute') && parseInt(style.zIndex) > 10) {
                                    if (!el.innerText.trim()) {
                                        el.style.setProperty('display', 'none', 'important');
                                    }
                                }
                                if (style.position === 'fixed' && style.bottom === '0px' && style.top !== '0px') {
                                    const text = el.innerText || '';
                                    if (text.includes('Log in') || text.includes('Sign Up')) {
                                        el.style.setProperty('display', 'none', 'important');
                                    }
                                }
                            });
                            document.body.style.setProperty('overflow', 'auto', 'important');
                            document.documentElement.style.setProperty('overflow', 'auto', 'important');
                        }
                    }
                """)
                await page.wait_for_timeout(2000)

            except Exception as e:
                logger.warning("Gagal memanipulasi UI Instagram: %s", e)
        
        elif "tiktok.com" in url:
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            
            for _ in range(3):
                try:
                    close_selectors = [
                        "button:has-text('Got it')",
                        "button:has-text('Not now')",
                        "button:has-text('Continue as guest')",
                        "div[data-e2e='modal-close-inner-button']",
                        "div[aria-label='Close']"
                    ]
                    for sel in close_selectors:
                        el = await page.query_selector(sel)
                        if el and await el.is_visible():
                            await el.click()
                except Exception:
                    pass

                await page.evaluate("""
                    () => {
                        document.querySelectorAll('[role="dialog"], [aria-modal="true"]').forEach(el => {
                            el.style.setProperty('display', 'none', 'important');
                        });
                        const specificSelectors = [
                            'div[data-e2e="bottom-banner-container"]',
                            'tiktok-cookie-banner',
                            '#login-modal'
                        ];
                        document.querySelectorAll(specificSelectors.join(', ')).forEach(el => {
                            el.style.setProperty('display', 'none', 'important');
                        });
                        document.querySelectorAll('div').forEach(el => {
                            const style = window.getComputedStyle(el);
                            const zIndex = parseInt(style.zIndex) || 0;
                            if ((style.position === 'fixed' || style.position === 'absolute') && zIndex > 50) {
                                el.style.setProperty('display', 'none', 'important');
                            }
                        });
                        document.body.style.setProperty('overflow', 'auto', 'important');
                        document.documentElement.style.setProperty('overflow', 'auto', 'important');
                    }
                """)
                await page.wait_for_timeout(1500)
        
        else:
            await page.wait_for_timeout(5000)

        unique_name = get_unique_filename(url) or urllib.parse.urlparse(url).netloc
        filename = f"{uuid.uuid4()}_{unique_name}.png"
        local_path = output_dir / filename

        await page.screenshot(path=str(local_path), clip={"x": 0, "y": 0, "width": 1280, "height": 720})
        logger.info("Berhasil disimpan: %s", filename)

        return {
            "url":         url,
            "local_path":  str(local_path),
            "object_name": f"{MINIO_PREFIX}/{filename}",
        }

    except Exception as e:
        logger.warning("Gagal memproses %s: %s", url, e)
        return None
    finally:
        await context.close()

async def take_screenshots(urls: list[str], output_dir: Path) -> list[dict]:
    """Buka setiap URL dengan Playwright dan ambil screenshot full-page.

    Args:
        urls:       Daftar URL yang akan di-screenshot.
        output_dir: Direktori untuk menyimpan file screenshot sementara.

    Returns:
        List dict berisi url, local_path, dan object_name (MinIO destination).
    """
    with _stdout_to_stderr():
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )

            tasks = [process_single_url(url, browser, output_dir) for url in urls]
            raw_results = await asyncio.gather(*tasks)

            await browser.close()
            
            results = [r for r in raw_results if r is not None]
            logger.info("Total screenshot berhasil: %d", len(results))
            return results


# ============================================================
# 5. UPLOAD MINIO + SAVE MONGODB (async)
# ============================================================
async def upload_screenshots(screenshots: list[dict]) -> dict:
    """Upload file screenshot lokal ke MinIO dan catat metadata ke MongoDB.

    Args:
        screenshots: List dict dari take_screenshots() dengan local_path dan object_name.

    Returns:
        Dict hasil upload: {"status": "success", "count": N, "screenshots": [...]}.
    """
    await connect_minio()
    logger.info("Koneksi MinIO berhasil.")

    uploaded: list[dict] = []
    screenshot_at = datetime.now().isoformat()

    for item in screenshots:
        result = await save_from_local(
            source=item["local_path"],
            destination=item["object_name"],
        )
        if result.get("status") == "success":
            uploaded.append({
                "url":           item["url"],
                "minio_path":    result["path"],
                "platform":      _detect_platform(item["url"]),
                "source":        "direct_url",
                "screenshot_at": screenshot_at,
            })
            logger.info("Upload berhasil: %s", item["object_name"])
        else:
            logger.warning(
                "Upload gagal %s: %s", item["object_name"], result.get(
                    "message")
            )

    await disconnect_minio()
    logger.info("Koneksi MinIO ditutup.")

    logger.info("Menginisialisasi koneksi MongoDB...")
    await connect_mongo()

    logger.info(
        "Menyimpan %d dokumen ke collection 'screenshot_evidence'...", len(uploaded))
    mongo_result = await insert_many_data(
        collection_name="screenshot_evidence",
        data_list=uploaded,
    )
    logger.info(
        "Berhasil disimpan! Count: %d | IDs (sample): %s...",
        mongo_result.get("count", 0),
        mongo_result.get("ids", [])[:3],
    )

    await disconnect_mongo()
    logger.info("Koneksi MongoDB ditutup.")

    return {
        "status":      "success",
        "count":       len(uploaded),
        "screenshots": [{"url": s["url"], "minio_path": s["minio_path"]} for s in uploaded],
    }


# ============================================================
# 6. ENTRY POINT — Satu-satunya print() ada di sini (JSON murni)
# ============================================================
async def main():
    parser = argparse.ArgumentParser(
        description="Screenshot Evidence — Ambil screenshot URL konten media sosial, upload ke MinIO",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--url", nargs="+", required=True,
        help="Daftar URL yang akan di-screenshot",
    )
    parser.add_argument(
        "--output_dir", type=str, default=None,
        help="Override direktori output (default: temporary directory yang otomatis dibersihkan)",
    )
    args = parser.parse_args()

    logger.info("=== Screenshot Evidence dimulai ===")
    logger.info(
        "URLs: %d | output_dir: %s", len(
            args.url), args.output_dir or "(tempdir)"
    )

    try:
        with _output_dir(args.output_dir) as output_dir:
            logger.info("Output directory: %s", output_dir)

            # Step 1: Screenshot semua URL via Playwright
            screenshots = await take_screenshots(args.url, output_dir)

            if not screenshots:
                raise RuntimeError(
                    "Tidak ada screenshot yang berhasil diambil.")

            # Step 2: Upload ke MinIO
            response = await upload_screenshots(screenshots)

        logger.info("=== Screenshot Evidence selesai ===")
        sys.stdout = _real_stdout
        print(json.dumps(response, default=str))
        sys.exit(0)

    except Exception as exc:
        logger.error("Eksekusi gagal: %s", exc, exc_info=True)
        sys.stdout = _real_stdout
        print(json.dumps({"status": "error", "message": str(exc)}))
        sys.exit(1)

if __name__ == "__main__":
    # Safety net: redirect sys.stdout → sys.stderr sebelum semua eksekusi.
    _real_stdout = sys.stdout
    sys.stdout = sys.stderr

    asyncio.run(main())
