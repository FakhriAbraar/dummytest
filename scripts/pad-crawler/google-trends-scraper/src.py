import os
import csv
import json
from datetime import datetime
from playwright.sync_api import Playwright, sync_playwright

def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    page.goto("https://trends.google.com/trending?geo=ID")

    # klik Export
    page.get_by_role("button", name="Export").click()

    # download CSV
    with page.expect_download() as download_info:
        page.get_by_role("menuitem", name="Download CSV").click()
    download = download_info.value

    # simpan CSV
    base_path = "google-trends-scraper/data"
    os.makedirs(base_path, exist_ok=True)
    csv_path = os.path.join(base_path, download.suggested_filename)
    download.save_as(csv_path)
    print("CSV saved:", csv_path)

    # mapping header CSV ke key JSON baru
    key_mapping = {
        "Trends": "topic",
        "Search volume": "search_volume",
        "Started": "trend_started",
        "Ended": "trend_ended",
        "Trend breakdown": "trend_breakdown",
        "Explore link": "explore_link"
    }

    # timestamp saat scraping
    timestamp = datetime.now().isoformat()  # format ISO 8601: 2026-03-10T14:30:00

    # baca CSV dan convert ke JSON
    json_path = os.path.splitext(csv_path)[0] + ".json"
    data = []

    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            new_row = {}
            for csv_key, json_key in key_mapping.items():
                if csv_key in row:
                    # optional: bersihkan karakter aneh di "Started"
                    value = row[csv_key]
                    if csv_key == "Started":
                        value = value.replace("\u202f", " ")
                    new_row[json_key] = value
            new_row["scraped_at"] = timestamp
            data.append(new_row)

    # simpan JSON rapi
    with open(json_path, 'w', encoding='utf-8') as jsonfile:
        json.dump(data, jsonfile, ensure_ascii=False, indent=4)

    print("JSON saved with renamed keys:", json_path)

    os.remove(csv_path)
    print("CSV file removed:", csv_path)

    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)