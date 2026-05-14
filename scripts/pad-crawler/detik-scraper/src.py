from playwright.sync_api import sync_playwright
from datetime import datetime
import json
import time
import os
import gc

def scrape_detik(playwright, target_link):

    if target_link is None:
        return

    browser = playwright.chromium.launch_persistent_context(
        user_data_dir=r"C:\playwright",
        channel="chrome",
        headless=True,
        no_viewport=True,
    )

    page = browser.new_page()

    print("SCRAPING SEMUA LINK BERITA")

    page.goto(
        target_link,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_selector(".media")

    raw_links = page.locator(".media__title a.media__link")

    links = []

    for i in range(raw_links.count()):
        el = raw_links.nth(i)

        id = el.get_attribute("dtr-id")
        title = el.get_attribute("dtr-ttl")
        href = el.get_attribute("href")

        if not href or target_link not in href: # Jika tidak mengandung target_link skip
            # To do selanjutnya sepertinya membuat penanganan khusus untuk tiap-tiap web di detik.com misal tags bagaimana, misal 20.detik.com bagaiamana, dstnya
            continue

        links.append({
            "unique_id": id,
            "title": title,
            "related_link": href
        })

    del raw_links; gc.collect()

    all_items = []
    timestamp = datetime.now().isoformat()

    for link in links:

        print("SCRAPING DETAIL NEWS PAGE")

        page.goto(
            link["related_link"],
            wait_until="domcontentloaded",
            timeout=60000
        )
        
        time.sleep(2)

        item = {}

        item["scraped_at"] = timestamp
        item["publisher"] = "Detik"
        item["unique_id"] = link["unique_id"]
        item["title"] = link["title"]
        item["news_date"] = ""
        item["content"] = ""
        item["related_link"] = link["related_link"]

        date = page.locator(".detail__header div.detail__date").text_content()
        item["news_date"] = date

        content_locator = page.locator("div.detail__body-text")

        content_locator.evaluate("""node => {
            // Daftar selector yang ingin dibuang
            const selectorsToRemoves = [
                'script', 
                'style', 
                '.parallax', 
                '.itp_body_ads', 
                '.detail__body-tag',
                '.googletag-impl',
                '#div-gpt-ad'
            ];
            
            selectorsToRemoves.forEach(selector => {
                const elements = node.querySelectorAll(selector);
                elements.forEach(el => el.remove());
            });
        }""")

        content = content_locator.inner_text().strip()

        item["content"] = " ".join(content.split())

        all_items.append(item)

    browser.close()

    return all_items


with sync_playwright() as p:

    target_link = "https://news.detik.com"

    result = scrape_detik(p, target_link)

    json_output = json.dumps(result, indent=4, ensure_ascii=False)

    base_path = "detik-scraper"
    base_name = "data/detik"
    ext = ".json"

    i = 1
    filename = f"{base_path}/{base_name}{ext}"

    while os.path.exists(filename):
        filename = f"{base_path}/{base_name}_{i}{ext}"
        i += 1

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("File saved:", filename)