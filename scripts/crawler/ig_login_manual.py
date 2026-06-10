import os
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent
SESSION_DIR = BASE_DIR / "sessions" / "instagram"

def login_manual():
    print("[*] Memulai Playwright dalam mode headed (headless=False)...")
    
    # Pastikan folder session otomatis terbuat jika belum ada
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[*] Folder profil browser disimpan di: {SESSION_DIR}")
    
    with sync_playwright() as p:
        # Jalankan Chromium dengan browser fisik dan context persistent agar user bisa interaksi langsung
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=False
        )
        
        page = context.pages[0] if context.pages else context.new_page()
        
        print("[*] Membuka halaman login Instagram...")
        page.goto("https://www.instagram.com/")
        
        print("\n=======================================================")
        print("  SILAKAN LOGIN SECARA MANUAL DI JENDELA BROWSER")
        print("  - Masukkan Username & Password Anda.")
        print("  - Masukkan kode verifikasi 2FA jika diminta.")
        print("  - Tunggu sampai halaman Beranda/Home Instagram muncul.")
        print("=======================================================")
        print("\n[!] JANGAN TUTUP jendela browser secara manual.")
        print("[!] Tekan [ENTER] pada terminal/console ini setelah berhasil")
        print("    login untuk menutup browser secara aman...")
        
        input("\nTekan [ENTER] di sini setelah login berhasil... ")
        
        # Penutupan context akan menyimpan otomatis seluruh cookies, local storage, dll. ke user_data_dir
        print("\n[*] Menutup browser dan menyimpan sesi...")
        context.close()
        print("[+] Sukses! Sesi login Anda telah tersimpan dalam profil persistent.")

if __name__ == "__main__":
    login_manual()
