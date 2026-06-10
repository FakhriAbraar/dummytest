import os
import sys
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent
POOL_SIZE = 5

def main():
    parser = argparse.ArgumentParser(description="Manual Twitter Login for Session Pool Slot")
    parser.add_argument(
        "--slot",
        type=int,
        required=True,
        choices=range(1, POOL_SIZE + 1),
        help="Slot index (1-5) to login and save session."
    )
    args = parser.parse_args()
    
    session_dir = BASE_DIR / "sessions" / "twitter" / f"twitter_session_{args.slot}"
    
    print(f"[*] Memulai Playwright headed untuk Twitter Slot {args.slot}...")
    print(f"[*] Folder profil browser disimpan di: {session_dir}")
    
    # Pastikan folder session otomatis terbuat jika belum ada
    session_dir.mkdir(parents=True, exist_ok=True)
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(session_dir),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        page = context.pages[0] if context.pages else context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        
        print("[*] Membuka halaman login X/Twitter...")
        page.goto("https://x.com/i/flow/login")
        
        print("\n=======================================================")
        print(f"  SILAKAN LOGIN SECARA MANUAL DI JENDELA BROWSER (SLOT {args.slot})")
        print("  - Masukkan Username & Password Anda.")
        print("  - Selesaikan kode verifikasi 2FA jika diminta.")
        print("  - Tunggu sampai halaman Beranda/Home X/Twitter muncul.")
        print("=======================================================")
        print("\n[!] JANGAN TUTUP jendela browser secara manual.")
        print("[!] Tekan [ENTER] pada terminal/console ini setelah berhasil")
        print("    login untuk menutup browser secara aman...")
        
        input(f"\nTekan [ENTER] di sini setelah login slot {args.slot} berhasil... ")
        
        # Penutupan context akan menyimpan otomatis seluruh cookies, local storage, dll. ke user_data_dir
        print("\n[*] Menutup browser dan menyimpan sesi...")
        context.close()
        print(f"[+] Sukses! Sesi login Twitter slot {args.slot} telah tersimpan.")

if __name__ == "__main__":
    main()
