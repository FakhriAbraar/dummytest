"""
test_crawlers.py — Standalone runner untuk menguji crawler via subprocess.

Cara menjalankan dari root project:
    conda run -n aitf python -m tests.test_crawlers

Skrip ini mensimulasikan persis cara AI Agent memanggil crawler:
  - stdout  -> di-parse sebagai JSON
  - stderr  -> ditampilkan sebagai log
  - exit code -> 0 = sukses, 1 = gagal
"""

from dataclasses import dataclass, field
from pathlib import Path
import subprocess
import time
import json
import io
import sys

# Paksa console Windows ke UTF-8 (code page 65001) agar karakter non-ASCII tampil benar
if sys.platform == "win32":
    import ctypes
    ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    ctypes.windll.kernel32.SetConsoleCP(65001)

sys.stdout = io.TextIOWrapper(
    sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(
    sys.stderr.buffer, encoding="utf-8", errors="replace")


# ============================================================
# KONFIGURASI CRAWLER YANG AKAN DIUJI
# ============================================================
# Root project = direktori tempat file ini berada
PROJECT_ROOT = next(p for p in Path(
    __file__).parents if (p / "pyproject.toml").exists())

CRAWLERS = [
    {
        "name":    "Trends24",
        "module":  "scripts.crawler.trends24",
        "args":    ["--region", "indonesia"],
    },
    {
        "name":    "Google Trends",
        "module":  "scripts.crawler.google-trends",
        "args":    [],
    },
    {
        "name":   "Instagram",
        "module": "scripts.crawler.instagram",
        "args":   ["--keyword", "prabowo", "--target_post", "3", "--max_scroll", "3"],
    },
    {
        "name":   "TikTok",
        "module": "scripts.crawler.tiktok",
        "args":   ["--keyword", "komdigi", "--target_post", "20"],
    },
    {
        "name":   "Twitter",
        "module": "scripts.crawler.twitter",
        "args":   ["--keyword", "komdigi", "--target_post", "5"],
    },
    {
        "name":   "YouTube",
        "module": "scripts.crawler.youtube",
        "args":   ["--keyword", "nadiem makarim", "--target_post", "1"],
    },
    {
        "name":   "Screenshot",
        "script": "scripts/crawler/screenshot-evidence.py",
        "args":   ["--url", "https://www.youtube.com/watch?v=6KP2W1djB6c", "https://instagram.com/p/DXtLg_Wk95E", "https://www.tiktok.com/@badan.gerakan.nus/video/7628929672537034005", "https://x.com/scaradeharu/status/2054107944783085888"],
    },
    {
        "name":   "Content Checker",
        "script": "scripts/crawler/content-checker.py",
        "args":   [
            "--url",
            "https://www.youtube.com/watch?v=6KP2W1djB6c",
            "https://www.tiktok.com/@badan.gerakan.nus/video/7628929672537034005",
            "https://instagram.com/p/DXtLg_Wk95E",
            "https://x.com/scaradeharu/status/2054107944783085888",
        ],
    },
]

# ============================================================
# DATA CLASS HASIL UJI
# ============================================================


@dataclass
class TestResult:
    name:       str
    passed:     bool
    duration_s: float
    exit_code:  int
    stdout_raw: str
    stderr:     str
    json_out:   dict = field(default_factory=dict)
    error_msg:  str = ""


# ============================================================
# HELPER: WARNA TERMINAL (ANSI)
# ============================================================
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ok(text): return f"{GREEN}[PASS] {text}{RESET}"
def fail(text): return f"{RED}[FAIL] {text}{RESET}"
def info(text): return f"{CYAN}{text}{RESET}"
def warn(text): return f"{YELLOW}[WARN] {text}{RESET}"
def bold(text): return f"{BOLD}{text}{RESET}"


# ============================================================
# CORE: JALANKAN SATU CRAWLER VIA SUBPROCESS
# ============================================================
def run_crawler(config: dict) -> TestResult:
    name = config["name"]

    # Susun command: gunakan sys.executable agar selalu pakai Python env yang sama
    if "module" in config:
        cmd = [sys.executable, "-m", config["module"]] + config.get("args", [])
    else:
        cmd = [sys.executable, config["script"]] + config.get("args", [])

    print(f"\n{'-' * 60}")
    print(bold(f"  Menjalankan: {name}"))
    print(f"  Command    : {' '.join(cmd)}")
    print(f"  CWD        : {PROJECT_ROOT}")
    print(f"{'-' * 60}")

    start = time.perf_counter()

    # Pastikan project root ada di PYTHONPATH agar `from app.xxx import ...`
    # selalu bisa di-resolve, baik saat dijalankan dengan -m maupun path langsung.
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            env=env,
        )
    except FileNotFoundError as e:
        return TestResult(
            name=name, passed=False, duration_s=0,
            exit_code=-1, stdout_raw="", stderr="",
            error_msg=f"Executable tidak ditemukan: {e}",
        )

    duration = time.perf_counter() - start

    # --- Tampilkan STDERR (log proses) ---
    if result.stderr.strip():
        print(info("\n  [STDERR — Log Proses]"))
        for line in result.stderr.strip().splitlines():
            print(f"  {line}")

    # --- Tampilkan STDOUT mentah ---
    print(info(f"\n  [STDOUT — Raw ({len(result.stdout)} chars)]"))
    # Potong jika terlalu panjang untuk keterbacaan
    preview = result.stdout.strip()
    if len(preview) > 300:
        preview = preview[:300] + f"  ... (+{len(preview)-300} chars)"
    print(f"  {preview}")

    # --- Validasi: STDOUT harus bisa di-parse sebagai JSON ---
    json_out = {}
    error_msg = ""
    passed = False

    stdout_stripped = result.stdout.strip()

    if not stdout_stripped:
        error_msg = "STDOUT kosong — tidak ada output JSON."
    else:
        try:
            json_out = json.loads(stdout_stripped)
        except json.JSONDecodeError as e:
            error_msg = f"STDOUT bukan JSON valid: {e}"

    if not error_msg:
        # --- Validasi: JSON harus memiliki field 'status' ---
        if "status" not in json_out:
            error_msg = "JSON tidak memiliki field 'status'."
        elif json_out["status"] == "error":
            error_msg = f"Crawler melaporkan error: {json_out.get('message', '(no message)')}"
        elif json_out["status"] == "success":
            count = json_out.get("count", 0)
            if count == 0:
                error_msg = "Status sukses tapi 'count' = 0, tidak ada data tersimpan."
            else:
                passed = True
        else:
            error_msg = f"Nilai 'status' tidak dikenal: {json_out['status']!r}"

    # Exit code check (tambahan)
    if passed and result.returncode != 0:
        passed = False
        error_msg = f"JSON menunjukkan sukses tapi exit code = {result.returncode}"

    return TestResult(
        name=name,
        passed=passed,
        duration_s=duration,
        exit_code=result.returncode,
        stdout_raw=result.stdout,
        stderr=result.stderr,
        json_out=json_out,
        error_msg=error_msg,
    )


# ============================================================
# ENTRY POINT
# ============================================================
def main():
    print(bold(f"\n{'=' * 60}"))
    print(bold(f"  CRAWLER SUBPROCESS TEST RUNNER"))
    print(bold(f"  Project: {PROJECT_ROOT}"))
    print(bold(f"  Python : {sys.executable}"))
    print(bold(f"{'=' * 60}"))

    results: list[TestResult] = []

    for config in CRAWLERS:
        result = run_crawler(config)
        results.append(result)

        # --- Ringkasan per crawler ---
        print()
        if result.passed:
            count = result.json_out.get("count", "?")
            print(
                ok(f"  LULUS  | {result.name} — {count} dokumen tersimpan ({result.duration_s:.1f}s)"))
        else:
            print(fail(f"  GAGAL  | {result.name} ({result.duration_s:.1f}s)"))
            print(f"         {RED}Alasan: {result.error_msg}{RESET}")
            print(f"         Exit code: {result.exit_code}")

    # ============================================================
    # SUMMARY AKHIR
    # ============================================================
    passed_count = sum(1 for r in results if r.passed)
    total_count = len(results)
    total_time = sum(r.duration_s for r in results)

    print(f"\n{'=' * 60}")
    print(bold("  HASIL AKHIR"))
    print(f"{'=' * 60}")

    for r in results:
        status_str = ok("LULUS") if r.passed else fail("GAGAL")
        doc_count = r.json_out.get("count", "-") if r.passed else "-"
        print(
            f"  {status_str}  {r.name:<20} | {doc_count:>5} docs | {r.duration_s:>5.1f}s | exit={r.exit_code}")

    print(f"{'-' * 60}")
    print(
        f"  Total: {passed_count}/{total_count} lulus | Waktu total: {total_time:.1f}s")

    if passed_count == total_count:
        print(ok(f"\n  Semua crawler berfungsi dengan benar!"))
    else:
        failed_names = [r.name for r in results if not r.passed]
        print(fail(
            f"\n  {total_count - passed_count} crawler gagal: {', '.join(failed_names)}"))

    print(f"{'=' * 60}\n")

    # Exit code keseluruhan: 0 jika semua lulus, 1 jika ada yang gagal
    sys.exit(0 if passed_count == total_count else 1)


if __name__ == "__main__":
    main()
