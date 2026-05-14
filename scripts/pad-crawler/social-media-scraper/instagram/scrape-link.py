import os
import sys
import json
import time
import random
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# Konfigurasi
IG_USER = None
IG_PASS = None
BASE_DIR = Path(__file__).resolve().parent
SESSION_FILE = BASE_DIR / "ig_session.json"
TARGET_TAGS = ["aniesbaswedan", "prabowosubianto", "ganjarpranowo"] 
MAX_POST_PER_TAG = 20
MAX_EMPTY_SCROLL = 10

def testing_config():
    print(f"IG_USER {IG_USER}, IG_PASS {IG_PASS}")
    print(f"BASE_DIR {BASE_DIR}")
    print(f"SESSION_FILE {SESSION_FILE}")

def human_scroll(page):
    """
    Simulasi scroll manusia: 
    Menggulir sedikit demi sedikit beberapa kali dengan jeda acak, 
    bukan melompat instan.
    """
    # Berapa kali putaran roda mouse yang akan dilakukan? (misal 3-6 kali putaran)
    scroll_steps = random.randint(3, 6)
    
    print("  [Sedang scroll layaknya manusia...]")
    for _ in range(scroll_steps):
        # Berapa piksel per putaran roda? (misal 100-300 piksel)
        distance = random.randint(100, 300)
        
        # Eksekusi putaran roda mouse (0 untuk sumbu X, distance untuk sumbu Y)
        page.mouse.wheel(0, distance)
        
        # Jeda saat jari manusia berhenti sejenak sebelum memutar roda lagi
        time.sleep(random.uniform(0.1, 0.4))
    
    # Jeda agak lama setelah selesai satu sesi scroll (seolah sedang melihat gambar)
    time.sleep(random.uniform(1.5, 3.0))

def handle_popups(page):
    """Menangani edge case munculan 'Save Info' dan 'Notifications'"""
    time.sleep(2)
    selectors = [
        "button:has-text('Not Now')", 
        "button:has-text('Lain Kali')",
    ]
    for selector in selectors:
        try:
            btn = page.query_selector(selector)
            if btn:
                btn.click()
                time.sleep(1)
        except:
            pass

def do_login(page):
    """Proses login dengan Validasi Keberhasilan & Ketikan Manusiawi"""
    print(f"Melakukan login baru untuk @{IG_USER}...")
    page.goto("https://www.instagram.com/accounts/login/")
    
    try:
        # 1. Tunggu kolom username benar-benar muncul dan siap
        page.wait_for_selector('input[name="email"]', timeout=15000)
        time.sleep(2) 
        
        # 2. Locator untuk form
        username_input = page.locator('input[name="email"]')
        password_input = page.locator('input[name="pass"]')

        # 3. Klik dan ketik username satu per satu
        username_input.click()
        time.sleep(0.5)
        username_input.press_sequentially(IG_USER, delay=150) 
        
        time.sleep(1) 
        
        # 4. Klik dan ketik password satu per satu
        password_input.click()
        time.sleep(0.5)
        password_input.press_sequentially(IG_PASS, delay=150)
        
        time.sleep(1)
        
        # 5. KLIK TOMBOL SUBMIT (Diperbarui menggunakan elemen <span>)
        # Menggunakan pseudo-class :text-is untuk memastikan teksnya sama persis "Log in"
        login_button = page.locator('span:text-is("Log in")')
        
        login_button.click()
        
        # Beri waktu Instagram memproses login
        time.sleep(5) 
        
        # --- LANJUTAN VALIDASI LOGIN ---
        if page.query_selector('p[id="slfErrorAlert"]'):
            print("❌ LOGIN GAGAL: Username atau Password salah.")
            return False
            
        if page.query_selector('svg[aria-label="Home"]') or page.query_selector('svg[aria-label="Beranda"]'):
            print("✅ LOGIN BERHASIL!")
            handle_popups(page)
            return True
            
        if "challenge" in page.url or page.query_selector('button:has-text("Send Security Code")'):
            print("⚠️ Peringatan: Akun terkena Checkpoint/Verifikasi OTP.")
            return False

        return False
        
    except Exception as e:
        print(f"❌ Terjadi kesalahan tak terduga saat login: {e}")
        return False

def scrape_instagram():
    hasil_final = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        
        if os.path.exists(SESSION_FILE):
            print("Memuat sesi login lama...")
            context = browser.new_context(storage_state=SESSION_FILE)
        else:
            context = browser.new_context()

        page = context.new_page()
        page.goto("https://www.instagram.com/")
        time.sleep(4)

        is_logged_in = False

        # --- PENGECEKAN STATUS SEBELUM SCRAPING ---
        if page.query_selector('input[name="email"]'):
            # Jika form login muncul, berarti sesi kosong atau kadaluarsa
            is_logged_in = do_login(page)
            if is_logged_in:
                context.storage_state(path=SESSION_FILE)
        else:
            # Jika form tidak ada, pastikan benar-benar sudah masuk (cek ikon home)
            if page.query_selector('svg[aria-label="Home"]') or page.query_selector('svg[aria-label="Beranda"]'):
                print("✅ Berhasil masuk menggunakan sesi tersimpan.")
                handle_popups(page)
                is_logged_in = True
            else:
                print("⚠️ Sesi tidak valid atau halaman tidak termuat sempurna. Mencoba login ulang...")
                is_logged_in = do_login(page)
                if is_logged_in:
                    context.storage_state(path=SESSION_FILE)

        # --- PERINTAH BERHENTI JIKA GAGAL LOGIN ---
        if not is_logged_in:
            print("\n🛑 PROSES DIHENTIKAN: Gagal memverifikasi login. Script tidak akan melakukan scraping tag.")
            browser.close()
            return {} # Kembalikan dictionary kosong

        # ==========================================
        # BAGIAN INI HANYA JALAN JIKA LOGIN SUKSES
        # ==========================================
        for tag in TARGET_TAGS:
            print(f"\n--- Menjelajahi #{tag} ---")
            page.goto(f"https://www.instagram.com/explore/tags/{tag}/")
            # possible endpoint yang lain https://www.instagram.com/web/search/topsearch/?query=anies
            # possible endpoint yang lain https://www.instagram.com/explore/locations/6889842
            
            links_found = set()
            retry_scroll = 0
            
            while len(links_found) < MAX_POST_PER_TAG and retry_scroll < MAX_EMPTY_SCROLL:
                elements = page.query_selector_all("a")
                
                for el in elements:
                    if len(links_found) >= MAX_POST_PER_TAG:
                        break
                    
                    href = el.get_attribute("href")
                    if href and (href.startswith("/p/") or href.startswith("/reel/")):
                        full_url = f"https://www.instagram.com{href}"
                        links_found.add(full_url)

                if len(links_found) < MAX_POST_PER_TAG:
                    # page.evaluate("window.scrollBy(0, 800)")
                    # time.sleep(random.uniform(2, 4))
                    human_scroll(page) # Scrolling seperti manusia
                    retry_scroll += 1
                else:
                    break

            print(f"Selesai. Didapat {len(links_found)} link untuk #{tag}")
            hasil_final[tag] = list(links_found)

        browser.close()
    
    return hasil_final

if __name__ == "__main__":

    load_dotenv()

    IG_USER = os.getenv("IG_USER")
    IG_PASS = os.getenv("IG_PASS")

    # testing_config()

    data = scrape_instagram()
    output = {
        "metadata": {
            "scraped_at": datetime.now().isoformat(),
            "target_tags": TARGET_TAGS,
            "max_post_per_tag": MAX_POST_PER_TAG
        },
        "data": data
    }
    
    # Hanya buat file JSON jika datanya tidak kosong (artinya login sukses dan scraping jalan)
    counter = 6
    output_path = BASE_DIR / "data" / f"hasil_explore_ig_{counter}.json"

    if data:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=4, ensure_ascii=False)
        print("\n" + "="*30)
        print("SCRAPING SELESAI")
        print(f"Data disimpan di: {output_path}")
        print("="*30)