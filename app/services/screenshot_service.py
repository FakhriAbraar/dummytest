"""Wrapper ringan untuk scripts/crawler/screenshot-evidence.py.

Dipanggil satu kali per mission (batch) oleh save_mission_report
untuk mengambil Playwright screenshot semua URL lalu upload ke MinIO.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from typing import Any


async def take_screenshots_for_urls(urls: list[str]) -> dict[str, str]:
    """Jalankan screenshot-evidence.py sebagai subprocess untuk daftar URL.

    Returns:
        {url: minio_path} — hanya URL yang berhasil di-screenshot.
        Kalau gagal total atau tidak ada URL, return {}.
    """
    if not urls:
        return {}

    print(f"[*] Mengambil screenshot evidence untuk {len(urls)} URL...")

    cwd_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../")
    )

    BATCH_SIZE = 15
    final_result = {}

    for i in range(0, len(urls), BATCH_SIZE):
        chunk = urls[i:i + BATCH_SIZE]
        print(f"[*] Memproses batch screenshot {i//BATCH_SIZE + 1} ({len(chunk)} URL)...")

        def _run(current_chunk) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, "scripts/crawler/screenshot-evidence.py", "--url", *current_chunk],
                capture_output=True,
                text=True,
                cwd=cwd_path,
                timeout=300, # 5 minutes is plenty for 15 concurrent URLs
            )

        try:
            proc = await asyncio.to_thread(_run, chunk)
            if proc.returncode != 0:
                print(f"[-] Screenshot subprocess gagal pada batch {i//BATCH_SIZE + 1} (exit {proc.returncode}):\n{proc.stderr}")
                continue

            data: Any = json.loads(proc.stdout)
            screenshots: list[dict[str, str]] = data.get("screenshots", [])
            for s in screenshots:
                if s.get("url") and s.get("minio_path"):
                    final_result[s["url"]] = s["minio_path"]
        except Exception as e:
            print(f"[-] Screenshot subprocess error pada batch {i//BATCH_SIZE + 1}: {repr(e)}")
            continue

    print(f"[+] Screenshot evidence siap: {len(final_result)} dari {len(urls)} URL berhasil.")
    return final_result
