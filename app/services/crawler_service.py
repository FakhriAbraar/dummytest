import os
import sys
import json
import asyncio
import subprocess

# Force subprocess child processes to use UTF-8 encoding. Tidak ada override
# TEMP/TMP/PLAYWRIGHT_BROWSERS_PATH ke path device lokal: aplikasi deploy di VPS
# (Linux container), jadi Playwright pakai /tmp + lokasi browser default. Bila
# perlu kustom, set env var tsb di environment container (bukan hardcode di sini).
_subprocess_env = {
    **os.environ,
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUTF8": "1",
}


def _run_trend_subprocess_sync(script_module: str, *extra_args) -> list[str]:
    cwd_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
    cmd = [sys.executable, "-m", script_module] + list(extra_args)

    print(f"[trend_crawler] exec: {' '.join(cmd)}")

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd_path,
        timeout=300,
        env=_subprocess_env,
    )

    if proc.returncode != 0:
        err_full = proc.stderr.decode("utf-8", errors="replace").strip()
        print(f"[trend_crawler] subprocess FAILED module={script_module} exit={proc.returncode} stderr:\n{err_full}")
        return []

    try:
        result = json.loads(proc.stdout.decode("utf-8", errors="replace"))
        topics = []
        for item in result.get("extracted_data", []):
            if "topic" in item and item["topic"]:
                topics.append(str(item["topic"]))
        print(f"[trend_crawler] module={script_module} OK topics={len(topics)}")
        return topics
    except json.JSONDecodeError:
        print(f"[trend_crawler] module={script_module} ERROR: stdout is not valid JSON")
        return []
    except Exception as e:
        print(f"[trend_crawler] module={script_module} parse error: {e}")
        return []


async def _run_trend_subprocess(script_module: str, *extra_args) -> list[str]:
    return await asyncio.to_thread(_run_trend_subprocess_sync, script_module, *extra_args)


async def run_trend_crawlers() -> list:
    print("\n[trend_crawler] START sources=[trends24, google_trends]")

    t24_task = _run_trend_subprocess("scripts.crawler.trends24", "--region", "indonesia")
    gtrends_task = _run_trend_subprocess("scripts.crawler.google_trends")

    results = await asyncio.gather(t24_task, gtrends_task)
    combined_trends = results[0] + results[1]

    cleaned_trends = list({t.lower().strip() for t in combined_trends if t.strip()})
    print(f"[trend_crawler] unique topics={len(cleaned_trends)}\n")

    if not cleaned_trends:
        # Tidak ada fallback dummy: biarkan kosong dan log dengan jelas agar
        # kegagalan trend crawler terlihat (bukan disamarkan dengan data palsu).
        print(
            "[trend_crawler] ERROR: 0 topics returned from all sources "
            "(see subprocess stderr above)"
        )

    return cleaned_trends


def _run_sosmed_subprocess_sync(script_module: str, keyword: str, limit: int, extra_args: list | None = None) -> list[dict]:
    cwd_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
    cmd = [
        sys.executable, "-m", script_module,
        "--keyword", keyword,
        "--target_post", str(limit),
    ]
    if extra_args:
        cmd.extend(extra_args)

    platform_name = script_module.split(".")[-1].upper()
    print(f"[content_crawler] exec module={script_module} keyword={keyword!r} target_post={limit}")

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd_path,
            timeout=300,
            env=_subprocess_env,
        )

        if proc.returncode != 0:
            err_full = proc.stderr.decode("utf-8", errors="replace").strip()
            print(f"[content_crawler] subprocess FAILED platform={platform_name} exit={proc.returncode} stderr:\n{err_full}")
            return []

        result = json.loads(proc.stdout.decode("utf-8", errors="replace"))
        formatted_data = []
        for doc in result.get("extracted_data", []):
            creator = doc.get("creator") or doc.get("user_info") or {}
            file_paths = doc.get("file_path") or []
            # Prefer dedicated cover/thumbnail URL (real image), then non-video file path
            thumb = (
                doc.get("cover_url")
                or doc.get("thumbnail_url")
                or doc.get("coverUrl")
                or next(
                    (
                        fp for fp in file_paths
                        if not fp.lower().endswith((".mp4", ".webm", ".mkv", ".mov", ".avi"))
                    ),
                    "",
                )
            )
            formatted_data.append({
                "type": doc.get("type", "text"),
                "content": doc.get("caption", ""),
                "source": doc.get("platform", platform_name.lower()),
                "url": doc.get("url", ""),
                "username": creator.get("username") or doc.get("username") or "",
                "file_path": file_paths,
                "thumbnail_url": thumb,
            })

        print(f"[content_crawler] platform={platform_name} OK items={len(formatted_data)}")
        return formatted_data

    except json.JSONDecodeError:
        print(f"[content_crawler] platform={platform_name} ERROR: stdout is not valid JSON")
        return []
    except Exception as e:
        print(f"[content_crawler] platform={platform_name} exception: {e}")
        return []


async def _run_sosmed_subprocess(script_module: str, keyword: str, limit: int, extra_args: list | None = None) -> list[dict]:
    return await asyncio.to_thread(_run_sosmed_subprocess_sync, script_module, keyword, limit, extra_args)


async def _crawl_one_platform(
    source: str,
    script_module: str,
    keyword: str,
    limit: int,
    progress=None,
    extra_args: list | None = None,
) -> list[dict]:
    """Crawl a single platform, reporting its stage status to `progress`.

    `source` is the platform key (x / instagram / tiktok) the job tracker maps to
    a UI stage. The underlying subprocess swallows its own errors and returns [],
    so a hard failure here is rare but still surfaced as a failed stage.
    """
    if progress:
        progress.start_platform(source)
    try:
        data = await _run_sosmed_subprocess(script_module, keyword, limit, extra_args)
        if progress:
            progress.complete_platform(source)
        return data
    except Exception as exc:
        if progress:
            progress.fail_platform(source, exc)
        return []


async def _crawl_instagram_with_fallback(
    keyword: str,
    limit: int,
    ig_max_scroll: int,
    progress=None,
) -> list[dict]:
    """Instagram: coba Playwright (scripts.crawler.instagram) dulu; bila 0 item,
    fallback ke Apify (scripts.crawler.instagram_apify, pakai APIFY_API_TOKEN).

    IG anti-bot sering membuat Playwright pulang dengan 0 link; Apify hashtag
    scraper jauh lebih stabil sebagai cadangan. Satu stage UI "instagram" dipakai
    untuk seluruh upaya (primary + fallback).
    """
    if progress:
        progress.start_platform("instagram")
    try:
        data = await _run_sosmed_subprocess(
            "scripts.crawler.instagram", keyword, limit,
            ["--max_scroll", str(ig_max_scroll)],
        )
        if not data:
            print("[content_crawler] instagram (Playwright) 0 item -> fallback ke Apify")
            data = await _run_sosmed_subprocess(
                "scripts.crawler.instagram_apify", keyword, limit,
                ["--max_scroll", str(ig_max_scroll)],
            )
            if data:
                print(f"[content_crawler] instagram Apify fallback OK items={len(data)}")
            else:
                print("[content_crawler] instagram Apify fallback juga 0 item")
        if progress:
            progress.complete_platform("instagram")
        return data
    except Exception as exc:
        if progress:
            progress.fail_platform("instagram", exc)
        return []


async def run_content_crawlers(
    keyword: str,
    limit: int = 5,
    platform_limits: dict[str, int] | None = None,
    progress=None,
) -> list:
    limits: dict[str, int] = platform_limits or {}
    ig_limit = int(limits.get("instagram", limit))
    tiktok_limit = int(limits.get("tiktok", limit))
    x_limit = int(limits.get("x", limits.get("twitter", limit)))
    print(
        f"\n[content_crawler] START keyword={keyword!r} "
        f"limits(x={x_limit}, ig={ig_limit}, tiktok={tiktok_limit})"
    )

    # Pembagian engine (sesuai kebutuhan operasional):
    #   - Instagram   -> Playwright, fallback Apify (instagram_apify) bila 0 item
    #   - Twitter/X   -> Playwright (scripts.crawler.twitter)
    #   - TikTok      -> Apify      (scripts.crawler.tiktok)
    # instagram.py butuh --max_scroll (jumlah scroll kosong sebelum menyerah);
    # diturunkan dari target post agar cukup menjangkau target.
    ig_max_scroll = max(5, ig_limit * 2)

    ig_task = _crawl_instagram_with_fallback(keyword, ig_limit, ig_max_scroll, progress)
    tiktok_task = _crawl_one_platform(
        "tiktok", "scripts.crawler.tiktok", keyword, tiktok_limit, progress
    )
    twitter_task = _crawl_one_platform(
        "x", "scripts.crawler.twitter", keyword, x_limit, progress
    )

    results = await asyncio.gather(ig_task, tiktok_task, twitter_task)
    unified_data = results[0] + results[1] + results[2]

    # Tidak ada fallback dummy: bila semua crawler gagal, kembalikan kosong dan
    # log dengan jelas. Kegagalan dibiarkan terlihat (lihat stderr subprocess).
    if not unified_data:
        print(
            f"[content_crawler] ERROR: all crawlers returned 0 items for "
            f"keyword={keyword!r} (nothing forwarded to gatekeeper)"
        )
    else:
        print(f"[content_crawler] total items={len(unified_data)} -> gatekeeper")

    return unified_data
