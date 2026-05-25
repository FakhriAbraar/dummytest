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

    def _run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "scripts/crawler/screenshot-evidence.py", "--url", *urls],
            capture_output=True,
            text=True,
            cwd=cwd_path,
            timeout=300,
        )

    try:
        proc = await asyncio.to_thread(_run)
        if proc.returncode != 0:
            print(f"[-] Screenshot subprocess gagal (exit {proc.returncode}): {proc.stderr[:200]}")
            return {}

        data: Any = json.loads(proc.stdout)
        screenshots: list[dict[str, str]] = data.get("screenshots", [])
        result = {s["url"]: s["minio_path"] for s in screenshots if s.get("url") and s.get("minio_path")}
        print(f"[+] Screenshot evidence siap: {len(result)} URL berhasil.")
        return result
    except Exception as e:
        print(f"[-] Screenshot subprocess error: {repr(e)}")
        return {}
