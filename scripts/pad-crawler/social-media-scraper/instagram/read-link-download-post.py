import os
import re
import json
import time
import instaloader
from pathlib import Path
from dotenv import load_dotenv

# Konfigurasi
BASE_DIR = Path(__file__).resolve().parent

DOWNLOAD_PATH = BASE_DIR / "downloads"

NOMOR_FILE = 6
LINK_FILE_NAME = f"hasil_explore_ig_{NOMOR_FILE}.json"
LINK_DATA_PATH = BASE_DIR / "data" / LINK_FILE_NAME

NOMOR_SCRAPING_FILE = 1
SCRAPING_FILE_NAME = f"final_{NOMOR_SCRAPING_FILE}.json"
SCRAPING_PATH = BASE_DIR / "data" / SCRAPING_FILE_NAME

if __name__ == "__main__":

    load_dotenv()

    username = os.getenv("IG_USER")
    password = os.getenv("IG_PASS")

    L = instaloader.Instaloader(
        dirname_pattern=str(DOWNLOAD_PATH / "{target}"),
        quiet=True
    )

    L.login(username, password)

    with open(LINK_DATA_PATH, "r") as file:
        data = json.load(file)

    all_data = []
    scraped_at = data["metadata"]["scraped_at"]
    typename_map = {
        "GraphImage": "Photo",
        "GraphVideo": "Video",
        "GraphSidecar": "Carousel"
    }

    for keyword, links in data["data"].items():
        print(f"Keyword: {keyword}")
        for link in links:
            match = re.search(r"p/([^/]+)/", link)
            
            if match:
                shortcode = match.group(1)
                post = instaloader.Post.from_shortcode(L.context, shortcode)

                item = {
                    "scraped_at": scraped_at,
                    "platform": "instagram",
                    "file_path": str(DOWNLOAD_PATH / shortcode),
                    "detail":{
                        "post_link": f"https://instagram.com/p/{shortcode}/",
                        "mediacount": post.mediacount,
                        "owner_username": post.owner_username,
                        "comment_count": post.comments,
                        "like_count": post.likes,
                        "date": post.date.isoformat(),
                        "date_local": post.date_local.isoformat(),
                        "typename": post.typename,
                        "caption": post.caption.replace("\n", " ") if post.caption else None,
                        "content_type": typename_map.get(post.typename, "Unknown")
                    }
                }
                all_data.append(item)

                L.download_post(post, target=f"{shortcode}")
                time.sleep(1)
    
    with open(SCRAPING_PATH, "w", encoding="utf-8") as f:
        json.dump(all_data, f, indent=4, ensure_ascii=False)