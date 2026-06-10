import requests
import json

# Test vxtwitter
url = "https://api.vxtwitter.com/Twitter/status/1785507742183575971"
res = requests.get(url)
print("VXTWITTER JSON:")
print(json.dumps(res.json(), indent=2))

from yt_dlp import YoutubeDL
tiktok_url = "https://www.tiktok.com/@tiktok/video/7106594312292453675"
ydl_opts = {"quiet": True}
with YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info(tiktok_url, download=False)
    print("YT-DLP TIKTOK DESC:", info.get("description"))
