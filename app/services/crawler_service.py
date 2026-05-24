import os
import sys
import json
import asyncio
import subprocess

# Force subprocess child processes to use UTF-8 encoding on Windows
_subprocess_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


def _run_trend_subprocess_sync(script_module: str, *extra_args) -> list[str]:
    """Synchronous version — akan di-dispatch ke thread oleh wrapper async."""
    cwd_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
    cmd = [sys.executable, "-m", script_module] + list(extra_args)
    
    print(f"[*] Triggering subprocess: {' '.join(cmd)}")
    
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd_path,
        timeout=300,
        env=_subprocess_env
    )
    
    if proc.returncode != 0:
        print(f"[-] Subprocess {script_module} meledak (Exit {proc.returncode}):\n{proc.stderr.decode('utf-8', errors='replace')}")
        return []
        
    try:
        result = json.loads(proc.stdout.decode('utf-8', errors='replace'))
        topics = []
        
        # Ekstrak field 'topic' dari data yang udah ditambal tadi
        extracted_data = result.get("extracted_data", [])
        for item in extracted_data:
            if "topic" in item and item["topic"]:
                topics.append(str(item["topic"]))
                
        print(f"[+] {script_module} mengamankan {len(topics)} trending topics.")
        return topics
        
    except json.JSONDecodeError:
        print(f"[-] Output {script_module} bukan JSON murni. Pastikan tidak ada print() liar di scraper.")
        return []
    except Exception as e:
        print(f"[-] Parsing error di {script_module}: {e}")
        return []


async def _run_trend_subprocess(script_module: str, *extra_args) -> list[str]:
    return await asyncio.to_thread(_run_trend_subprocess_sync, script_module, *extra_args)


async def run_trend_crawlers() -> list: 
    print("\n[*] Menjalankan Integrasi Real Trend Crawlers (Trends24 & Google Trends)...")
    
    t24_task = _run_trend_subprocess("scripts.crawler.trends24", "--region", "indonesia")
    gtrends_task = _run_trend_subprocess("scripts.crawler.google_trends")
    
    results = await asyncio.gather(t24_task, gtrends_task)
    
    combined_trends = results[0] + results[1]
    
    cleaned_trends = list(set(
        t.lower().strip() for t in combined_trends if t.strip()
    ))
    
    print(f"[=] Total unique trending topics siap di-crawl: {len(cleaned_trends)}\n")
    
    if not cleaned_trends:
        print("[!] WARNING: Trend crawlers gagal total. Fallback ke seed default.")
        return ["kasus doxxing telegram"]
        
    return cleaned_trends


def _run_sosmed_subprocess_sync(script_module: str, keyword: str, limit: int, extra_args: list = None) -> list[dict]:
    """Synchronous version — akan di-dispatch ke thread oleh wrapper async."""
    cwd_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
    cmd = [
        sys.executable, "-m", script_module,
        "--keyword", keyword,
        "--target_post", str(limit)
    ]
    if extra_args:
        cmd.extend(extra_args)
        
    platform_name = script_module.split('.')[-1].upper()
    print(f"[*] Menugaskan Agen {platform_name} untuk: '{keyword}'...")
    
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd_path,
            timeout=300,
            env=_subprocess_env
        )
        
        if proc.returncode != 0:
            print(f"[-] Agen {platform_name} Gagal (Exit {proc.returncode}):\n{proc.stderr.decode('utf-8', errors='replace')}")
            return []
            
        result = json.loads(proc.stdout.decode('utf-8', errors='replace'))
        extracted_data = result.get("extracted_data", [])
        
        # Mapping Schema
        formatted_data = []
        for doc in extracted_data:
            formatted_data.append({
                "type": doc.get("type", "text"),
                "content": doc.get("caption", ""), 
                "source": doc.get("platform", platform_name.lower()),
                "url": doc.get("url", "")
            })
            
        print(f"[+] Agen {platform_name} mengamankan {len(formatted_data)} konten.")
        return formatted_data
        
    except json.JSONDecodeError:
        print(f"[-] Output {platform_name} bukan JSON murni. Cek log error:\n{proc.stdout.decode('utf-8', errors='replace')}")
        return []
    except Exception as e:
        print(f"[-] Exception di Agen {platform_name}: {e}")
        return []


async def _run_sosmed_subprocess(script_module: str, keyword: str, limit: int, extra_args: list = None) -> list[dict]:
    """Fungsi generic buat manggil scraper Twitter/IG sebagai subprocess."""
    return await asyncio.to_thread(_run_sosmed_subprocess_sync, script_module, keyword, limit, extra_args)


async def run_content_crawlers(keyword: str, limit: int = 5) -> list:
    print(f"\n[*] Mengerahkan Pasukan Crawler untuk keyword: '{keyword}' (Limit per platform: {limit})...")
    
    # Hantam Instagram dan TikTok berbarengan! (Twitter dinonaktifkan sementara)
    # twitter_task = _run_sosmed_subprocess("scripts.crawler.twitter", keyword, limit)
    
    # Kasih max_scroll 3 biar Playwright IG nggak muter-muter kelamaan di tag kosong
    ig_task = _run_sosmed_subprocess("scripts.crawler.instagram", keyword, limit, ["--max_scroll", "3"])
    
    # TikTok via Apify
    tiktok_task = _run_sosmed_subprocess("scripts.crawler.tiktok", keyword, limit)
    
    # Hanya tunggu IG dan TikTok
    results = await asyncio.gather(ig_task, tiktok_task)
    
    unified_data = results[0] + results[1]
    
    # Fallback kalau ketiga-tiganya meledak/rate-limited
    if not unified_data:
        print(f"[!] WARNING: Semua crawler gagal untuk '{keyword}'. Fallback ke data kosong.")
        return []
        
    print(f"[=] Total {len(unified_data)} konten diserahkan ke Gatekeeper.")
    return unified_data