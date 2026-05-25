import os
import sys
import json
import asyncio
import random
import subprocess

# Force subprocess child processes to use UTF-8 encoding + redirect Playwright/temp ke D:
_subprocess_env = {
    **os.environ,
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUTF8": "1",
    "PLAYWRIGHT_BROWSERS_PATH": os.environ.get(
        "PLAYWRIGHT_BROWSERS_PATH", "D:/sadam/Dev/.cache/ms-playwright"
    ),
    "TEMP": os.environ.get("TEMP", "D:/sadam/tmp"),
    "TMP": os.environ.get("TMP", "D:/sadam/tmp"),
}


def _run_trend_subprocess_sync(script_module: str, *extra_args) -> list[str]:
    cwd_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
    cmd = [sys.executable, "-m", script_module] + list(extra_args)

    print(f"[*] Triggering subprocess: {' '.join(cmd)}")

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd_path,
        timeout=300,
        env=_subprocess_env,
    )

    if proc.returncode != 0:
        err_preview = proc.stderr.decode("utf-8", errors="replace")[:500]
        print(f"[-] Subprocess {script_module} meledak (Exit {proc.returncode}). Stderr preview: {err_preview!r}")
        return []

    try:
        result = json.loads(proc.stdout.decode("utf-8", errors="replace"))
        topics = []
        for item in result.get("extracted_data", []):
            if "topic" in item and item["topic"]:
                topics.append(str(item["topic"]))
        print(f"[+] {script_module} mengamankan {len(topics)} trending topics.")
        return topics
    except json.JSONDecodeError:
        print(f"[-] Output {script_module} bukan JSON murni.")
        return []
    except Exception as e:
        print(f"[-] Parsing error di {script_module}: {e}")
        return []


async def _run_trend_subprocess(script_module: str, *extra_args) -> list[str]:
    return await asyncio.to_thread(_run_trend_subprocess_sync, script_module, *extra_args)


_DUMMY_TRENDS = [
    "cyberbullying anak sekolah",
    "judi online telegram",
    "konten dewasa tiktok",
    "scam belanja online",
    "pelecehan anak sosmed",
    "hoaks kesehatan viral",
    "kekerasan remaja instagram",
    "narkoba slang sosmed",
    "doxxing data pribadi",
    "phishing whatsapp",
]


async def run_trend_crawlers() -> list:
    print("\n[*] Menjalankan Real Trend Crawlers (Trends24 & Google Trends)...")

    t24_task = _run_trend_subprocess("scripts.crawler.trends24", "--region", "indonesia")
    gtrends_task = _run_trend_subprocess("scripts.crawler.google_trends")

    results = await asyncio.gather(t24_task, gtrends_task)
    combined_trends = results[0] + results[1]

    cleaned_trends = list({t.lower().strip() for t in combined_trends if t.strip()})
    print(f"[=] Total unique trending topics: {len(cleaned_trends)}\n")

    if not cleaned_trends:
        print("[!] WARNING: Trend crawlers gagal total. Fallback ke dummy trends agar pipeline tetap jalan.")
        return random.sample(_DUMMY_TRENDS, k=min(5, len(_DUMMY_TRENDS)))

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
    print(f"[*] Menugaskan Agen {platform_name} untuk: '{keyword}'...")

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
            err_preview = proc.stderr.decode("utf-8", errors="replace")[:500]
            print(f"[-] Agen {platform_name} Gagal (Exit {proc.returncode}). Stderr preview: {err_preview!r}")
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

        print(f"[+] Agen {platform_name} mengamankan {len(formatted_data)} konten.")
        return formatted_data

    except json.JSONDecodeError:
        print(f"[-] Output {platform_name} bukan JSON murni.")
        return []
    except Exception as e:
        print(f"[-] Exception di Agen {platform_name}: {e}")
        return []


async def _run_sosmed_subprocess(script_module: str, keyword: str, limit: int, extra_args: list | None = None) -> list[dict]:
    return await asyncio.to_thread(_run_sosmed_subprocess_sync, script_module, keyword, limit, extra_args)


_DUMMY_CONTENT_TEMPLATES = [
    "Awas ada link {kw} palsu beredar di group WhatsApp! Jangan klik sembarangan, banyak yang kena tipu.",
    "Video terbaru soal {kw} lagi viral banget di sosmed, isinya bikin gelisah orang tua.",
    "Gue nemuin akun yang nyebarin konten {kw} ke anak-anak di bawah umur. Tolong dilaporkan!",
    "Tutorial cara dapetin {kw} gratis, dijamin work 100%! DM aja ya gaes.",
    "BREAKING: Kasus {kw} yang menggemparkan netizen Indonesia, korban sudah puluhan.",
    "Hati-hati! Ada scam berkedok {kw} beredar luas di Instagram dan TikTok.",
    "Komunitas {kw} underground makin besar, sudah ada ribuan member di Telegram.",
    "Anak SD sudah kenal {kw}? Ini fakta mengejutkan yang wajib diketahui orang tua!",
    "Review jujur tentang {kw} dari perspektif yang berbeda, cek dulu sebelum judge.",
    "Kenapa {kw} makin populer di kalangan remaja? Ini penjelasan psikolognya.",
]

_DUMMY_PLATFORMS = ["instagram", "tiktok"]


def _generate_dummy_content(keyword: str, limit: int) -> list[dict]:
    posts = []
    kw_short = keyword.split()[0] if keyword else "ini"
    templates = random.sample(_DUMMY_CONTENT_TEMPLATES, k=min(limit, len(_DUMMY_CONTENT_TEMPLATES)))
    for i, tmpl in enumerate(templates[:limit]):
        platform = _DUMMY_PLATFORMS[i % len(_DUMMY_PLATFORMS)]
        slug = keyword.replace(" ", "_")[:20]
        posts.append({
            "type": random.choice(["text", "image"]),
            "content": tmpl.format(kw=kw_short),
            "source": platform,
            "url": f"https://{platform}.com/p/dummy_{slug}_{i + 1}",
            "username": f"dummy_user_{i + 1}",
            "file_path": [],
            "thumbnail_url": "",
        })
    return posts


async def run_content_crawlers(keyword: str, limit: int = 5) -> list:
    print(f"\n[*] Mengerahkan Crawler untuk keyword: '{keyword}' (limit: {limit})...")

    ig_task = _run_sosmed_subprocess("scripts.crawler.instagram_apify", keyword, limit)
    tiktok_task = _run_sosmed_subprocess("scripts.crawler.tiktok", keyword, limit)
    twitter_task = _run_sosmed_subprocess("scripts.crawler.twitter_apify", keyword, limit)

    results = await asyncio.gather(ig_task, tiktok_task, twitter_task)
    unified_data = results[0] + results[1] + results[2]

    if not unified_data:
        print(f"[!] Semua crawler gagal untuk '{keyword}'. Fallback ke dummy content agar pipeline tetap jalan.")
        unified_data = _generate_dummy_content(keyword, limit)
    else:
        print(f"[=] Total {len(unified_data)} konten diserahkan ke Gatekeeper.")

    return unified_data
