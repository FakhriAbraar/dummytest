from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import json
import time
from datetime import datetime

url = "https://trends24.in/indonesia/"

# Setup Chrome
chrome_options = Options()
chrome_options.add_argument("--headless") # Jalankan di latar belakang
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36")

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

try:
    print("Mengakses halaman...")
    driver.get(url)
    wait = WebDriverWait(driver, 20)

    # 1. Navigasi: Klik tab 'Table'
    tab_button = wait.until(EC.element_to_be_clickable((By.ID, "tab-link-table")))
    print("Mengklik tab Table...")
    driver.execute_script("arguments[0].click();", tab_button)

    # 2. Tunggu konten tabel dimuat
    print("Menunggu data dimuat...")
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "tbody.list tr")))
    time.sleep(2) # Jeda tambahan untuk memastikan semua row terisi

    # 3. Parsing Data
    soup = BeautifulSoup(driver.page_source, "html.parser")
    tbody = soup.find("tbody", class_="list")

    results = []
    if tbody:
        rows = tbody.find_all("tr")
        # timestamp saat scraping
        timestamp = datetime.now().isoformat()  # format ISO 8601: 2026-03-10T14:30:00
        for row in rows:
            topic_cell = row.find("td", class_="topic")
            if not topic_cell: continue

            data = {
                "scraped_at": timestamp,
                "topic": topic_cell.get_text(strip=True),
                "rank": row.find("td", class_="rank").get_text(strip=True),
                "history_top_position": row.find("td", class_="position").get_text(strip=True),
                "related_link": topic_cell.find("a")["href"] if topic_cell.find("a") else None,
                "tweet_count": row.find("td", class_="count").get_text(strip=True),
                "trending_duration": row.find("td", class_="duration").get_text(strip=True)
            }
            results.append(data)

        # 4. MENULIS KE FILE JSON
        nama_file = "trends24-scraper/data/trends24_indonesia.json"
        with open(nama_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=4, ensure_ascii=False)
        
        print(f"Berhasil! {len(results)} data telah disimpan ke '{nama_file}'.")
    else:
        print("Gagal mengambil data dari tabel.")

except Exception as e:
    print(f"Terjadi kesalahan: {e}")

finally:
    driver.quit()