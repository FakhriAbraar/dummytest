# Crawler Scripts — Technical Documentation

Kumpulan script Python untuk mengumpulkan data dari platform media sosial dan
sumber tren. Setiap script mengikuti **I/O contract** yang seragam sehingga bisa
dipanggil sebagai subprocess oleh AI Agent.

---

## Daftar Script

| Script | Fungsi | Input | MongoDB Collection | MinIO |
|--------|--------|-------|--------------------|-------|
| [trends24.py](#trends24py) | Scrape trending topics dari Trends24 | `--region` | `trends24_keyword` | Tidak |
| [google-trends.py](#google-trendspy) | Scrape Google Trends Indonesia | — | `google_trends_keyword` | Tidak |
| [instagram.py](#instagrampy) | Crawl posts Instagram by keyword | `--keyword`, `--target_post`, `--max_scroll` | `social_media_posts` | `crawl/instagram/` |
| [tiktok.py](#tiktokpy) | Crawl posts TikTok by keyword via Apify | `--keyword`, `--target_post` | `social_media_posts` | `crawl/tiktok/` |
| [twitter.py](#twitterpy) | Crawl tweets by keyword via tweet-harvest | `--keyword`, `--target_post` | `social_media_posts` | `crawl/twitter/` |
| [youtube.py](#youtubepy) | Crawl & download video YouTube by keyword | `--keyword`, `--target_post`, `--max_scroll` | `social_media_posts` | `crawl/youtube/` |
| [screenshot-evidence.py](#screenshot-evidencepy) | Screenshot URL konten media sosial sebagai bukti | `--url`, `--output_dir` | `screenshot_evidence` | `evidence/screenshots/` |
| [content-checker.py](#content-checkerpy) | Ekstrak konten dari URL langsung (metadata + media) | `--url` | `social_media_posts` | `crawl/<platform>/` |

---

## I/O Contract

Semua script mengikuti kontrak yang sama:

```
STDOUT  → JSON murni (satu baris), hanya satu print() di __main__
STDERR  → Semua log proses dengan prefix [nama-script]
Exit 0  → Sukses
Exit 1  → Gagal (JSON error tetap dicetak ke STDOUT)
```

### Cara Memanggil sebagai Subprocess

```python
import subprocess, json

result = subprocess.run(
    ["python", "-m", "scripts.crawler.tiktok",
     "--keyword", "komdigi", "--target_post", "20"],
    capture_output=True,
    text=True,
    cwd="/path/to/aitf-backend",
)

response  = json.loads(result.stdout)  # JSON sukses/error
logs      = result.stderr              # Log proses
exit_code = result.returncode          # 0 = sukses, 1 = gagal
```

> **Perhatian:** Script dengan tanda hubung di nama file (`screenshot-evidence.py`,
> `content-checker.py`, `google-trends.py`) **tidak bisa dijalankan dengan `-m`**.
> Gunakan path langsung: `["python", "scripts/crawler/screenshot-evidence.py", ...]`
<br>
> Jujur bisa-bisa aja sih pakai -m (aku juga gatau kenapa AI bilang gabisa)

### Format Output JSON

**Sukses (script keyword-based & content-checker):**
```json
{ "status": "success", "count": 5, "ids": ["..."] }
```

**Sukses (screenshot-evidence):**
```json
{
  "status": "success",
  "count": 2,
  "screenshots": [
    { "url": "https://x.com/...", "minio_path": "evidence/screenshots/..." }
  ]
}
```

**Gagal:**
```json
{ "status": "error", "message": "Deskripsi error" }
```

---

## MongoDB Collections

### `social_media_posts`

Digunakan oleh: `instagram.py`, `tiktok.py`, `twitter.py`, `youtube.py`, `content-checker.py`

```json
{
  "_id":            "ObjectId",
  "batch_id":       "uuid-string",
  "platform":       "instagram | tiktok | twitter | youtube | ...",
  "source":         "keyword_crawl | direct_url",
  "target_keyword": "string | null",
  "scraped_at":     "ISO 8601",
  "unique_id":      "platform_<id>",
  "url":            "https://...",
  "type":           "video | image | multipleImage | text",
  "caption":        "string | null",
  "published_at":   "ISO 8601 | null",
  "file_path":      ["minio/path/to/file.mp4"],
  "duration":       123,
  "creator": {
    "username": "string",
    "user_id":  "string"
  },
  "engagement": {
    "like_count":    0,
    "comment_count": 0,
    "share_count":   0,
    "view_count":    0,
    "saved_count":   0,
    "repost_count":  0
  }
}
```

Field `source` memungkinkan filtering berdasarkan asal crawl:
```js
db.social_media_posts.find({ source: "keyword_crawl" })
db.social_media_posts.find({ source: "direct_url" })
```

### `screenshot_evidence`

Digunakan oleh: `screenshot-evidence.py`

```json
{
  "_id":           "ObjectId",
  "url":           "https://...",
  "minio_path":    "evidence/screenshots/<uuid>_<id>.png",
  "platform":      "twitter | instagram | tiktok | youtube | ...",
  "source":        "direct_url",
  "screenshot_at": "ISO 8601"
}
```

### `trends24_keyword`

Digunakan oleh: `trends24.py`

```json
{
  "scraped_at":           "ISO 8601",
  "topic":                "string",
  "rank":                 "string",
  "history_top_position": "string",
  "related_link":         "https://...",
  "tweet_count":          "string",
  "trending_duration":    "string"
}
```

### `google_trends_keyword`

Digunakan oleh: `google-trends.py`

```json
{
  "scraped_at":      "ISO 8601",
  "topic":           "string",
  "search_volume":   "string",
  "trend_started":   "string",
  "trend_ended":     "string",
  "trend_breakdown": "string",
  "explore_link":    "https://..."
}
```

---

## MinIO Path Conventions

| Script | Path Pattern |
|--------|-------------|
| `instagram.py` | `crawl/instagram/<unique_id>.<ext>` (single) / `crawl/instagram/<unique_id>/<idx>.<ext>` (carousel) |
| `tiktok.py` | `crawl/tiktok/<unique_id>.<ext>` (video) / `crawl/tiktok/<unique_id>/<idx>.jpeg` (slideshow) |
| `twitter.py` | `crawl/twitter/<unique_id>.<ext>` |
| `youtube.py` | `crawl/youtube/<unique_id>.mp4` |
| `content-checker.py` | `crawl/<platform>/<unique_id>.<ext>` (single) / `crawl/<platform>/<unique_id>/<idx>.<ext>` (multi) |
| `screenshot-evidence.py` | `evidence/screenshots/<uuid>_<platform_id>.png` |

---

## Referensi Per Script

---

### `trends24.py`

Scrape trending topics dari [trends24.in](https://trends24.in).

**Library utama:** `playwright`, `beautifulsoup4`

**Args:**

| Arg | Type | Required | Default | Keterangan |
|-----|------|----------|---------|------------|
| `--region` | str | Tidak | `indonesia` | Region yang di-scrape (contoh: `global`, `united-states`) |
| `--headless` | bool | Tidak | `True` | Mode headless browser |

**Cara eksekusi:**
```bash
python -m scripts.crawler.trends24 --region indonesia
```

**Alur kerja:**
1. Playwright buka `trends24.in/<region>/`
2. Klik tab "Table" → tunggu data ter-render (`tbody.list tr`)
3. BeautifulSoup parse HTML → ekstrak `topic`, `rank`, `tweet_count`, dll.
4. Insert ke MongoDB `trends24_keyword`

---

### `google-trends.py`

Scrape trending topics dari Google Trends Indonesia via export CSV.

**Library utama:** `playwright`

**Args:** Tidak ada (hardcoded ke Indonesia, `geo=ID`)

**Cara eksekusi:**
```bash
python scripts/crawler/google-trends.py
```

**Alur kerja:**
1. Playwright buka `trends.google.com/trending?geo=ID`
2. Tunggu tabel trending ter-render (`tr.enOdEe-*`)
3. Klik tombol "Export" → "Download CSV" via Playwright download API
4. Parse CSV dengan `csv.DictReader` → mapping header ke field MongoDB
5. Insert ke MongoDB `google_trends_keyword`

---

### `instagram.py`

Crawl posts Instagram berdasarkan keyword menggunakan Playwright + Instaloader.

**Library utama:** `playwright`, `instaloader`, `python-dotenv`

**Args:**

| Arg | Type | Required | Default | Keterangan |
|-----|------|----------|---------|------------|
| `--keyword` | str+ | Ya | — | Satu atau lebih keyword pencarian |
| `--target_post` | int | Ya | — | Jumlah target post per keyword |
| `--max_scroll` | int | Tidak | `10` | Maksimum scroll per keyword |

**Cara eksekusi:**
```bash
python -m scripts.crawler.instagram --keyword prabowo --target_post 20 --max_scroll 10
```

**Alur kerja:**
1. Playwright scrape URL post dari halaman hasil pencarian Instagram
2. Instaloader download media (gambar/video/carousel) dari URL yang ditemukan
3. Upload file ke MinIO → path `crawl/instagram/`
4. Insert metadata ke MongoDB `social_media_posts` (`source: "keyword_crawl"`)

**Env vars:** `INSTAGRAM_USERNAME`, `INSTAGRAM_PASSWORD`

---

### `tiktok.py`

Crawl posts TikTok berdasarkan keyword menggunakan Apify actor + yt-dlp.

**Library utama:** `apify-client`, `yt-dlp`, `requests`, `python-dotenv`

**Args:**

| Arg | Type | Required | Default | Keterangan |
|-----|------|----------|---------|------------|
| `--keyword` | str+ | Ya | — | Satu atau lebih keyword pencarian |
| `--target_post` | int | Ya | — | Jumlah target post per keyword |

**Cara eksekusi:**
```bash
python -m scripts.crawler.tiktok --keyword komdigi --target_post 20
```

**Alur kerja:**
1. Apify actor `GdWCkxBtKWOsKjdch` scrape TikTok berdasarkan keyword
2. Iterasi hasil dataset Apify:
   - Video: download via yt-dlp
   - Slideshow: download setiap gambar via `requests.get()`
3. Upload file ke MinIO → `crawl/tiktok/`
4. Insert metadata ke MongoDB `social_media_posts` (`source: "keyword_crawl"`)

**Env vars:** `APIFY_API_FREE`, `APIFY_API_PREMIUM`

---

### `twitter.py`

Crawl tweets berdasarkan keyword menggunakan Playwright (auth) + tweet-harvest + yt-dlp.

**Library utama:** `playwright`, `yt-dlp`, `requests`, `python-dotenv`

**Dependensi eksternal:** Node.js + `npx tweet-harvest` (dipanggil via `subprocess`)

**Args:**

| Arg | Type | Required | Default | Keterangan |
|-----|------|----------|---------|------------|
| `--keyword` | str+ | Ya | — | Satu atau lebih keyword pencarian |
| `--target_post` | int | Ya | — | Jumlah target tweet |

**Cara eksekusi:**
```bash
python -m scripts.crawler.twitter --keyword komdigi --target_post 20
```

**Alur kerja:**
1. Playwright buka Twitter/X → ekstrak auth token dari browser storage
2. `npx tweet-harvest` dipanggil via `subprocess` dengan token → hasilkan CSV
3. Parse CSV (`csv.DictReader`) → untuk setiap tweet:
   - Gambar: download via `requests.get()`
   - Video: download via yt-dlp
4. Upload file ke MinIO → `crawl/twitter/`
5. Insert metadata ke MongoDB `social_media_posts` (`source: "keyword_crawl"`)

---

### `youtube.py`

Crawl dan download video YouTube berdasarkan keyword menggunakan Playwright + yt-dlp.

**Library utama:** `playwright`, `yt-dlp`, `python-dotenv`

**Args:**

| Arg | Type | Required | Default | Keterangan |
|-----|------|----------|---------|------------|
| `--keyword` | str+ | Ya | — | Satu atau lebih keyword pencarian |
| `--target_post` | int | Ya | — | Jumlah target video |
| `--max_scroll` | int | Tidak | `10` | Maksimum scroll per keyword |

**Cara eksekusi:**
```bash
python -m scripts.crawler.youtube --keyword "nadiem makarim" --target_post 5
```

**Alur kerja:**
1. Playwright stealth: buka `google.com` → `youtube.com` → hasil pencarian keyword
2. Scroll + ekstrak URL `/watch?v=...` hingga `target_post` terpenuhi
3. yt-dlp download video (format: `bestvideo+bestaudio`, merge ke `.mp4`)
4. Upload ke MinIO → `crawl/youtube/<unique_id>.mp4`
5. Insert metadata ke MongoDB `social_media_posts` (`source: "keyword_crawl"`)

---

### `screenshot-evidence.py`

Ambil screenshot halaman URL konten media sosial sebagai bukti visual, lalu simpan ke MinIO + MongoDB.

**Library utama:** `playwright`, `python-dotenv`

> Jalankan dengan **path langsung** (bukan `-m`) karena nama file mengandung tanda hubung.

**Args:**

| Arg | Type | Required | Default | Keterangan |
|-----|------|----------|---------|------------|
| `--url` | str+ | Ya | — | Satu atau lebih URL yang di-screenshot |
| `--output_dir` | str | Tidak | `None` (tempdir) | Override direktori output lokal |

**Cara eksekusi:**
```bash
python scripts/crawler/screenshot-evidence.py \
    --url "https://x.com/user/status/123" "https://instagram.com/p/abc/"
```

**Alur kerja:**
1. Untuk setiap URL, buat browser context baru (isolasi antar URL)
2. Per-platform edge case handling:
   - **Twitter/X**: tunggu `span:has-text('Post')` → wait 3s
   - **Instagram**: tunggu `div[role="dialog"]` → hybrid JS (klik `svg[aria-label="Close"]` atau hide overlay DOM)
   - **Lainnya**: wait 5000ms
3. `page.screenshot(full_page=True)` → simpan sebagai `<uuid>_<platform_id>.png`
4. Upload ke MinIO → `evidence/screenshots/`
5. Insert metadata ke MongoDB `screenshot_evidence` (`source: "direct_url"`)

**Deteksi filename dari URL:**

| Platform | Pattern URL | Format Filename |
|----------|-------------|----------------|
| Instagram | `/p/<shortcode>/` | `instagram_<shortcode>.png` |
| TikTok | `/video/<id>` | `tiktok_<id>.png` |
| Twitter/X | `/status/<id>` | `twitter_<id>.png` |
| YouTube | `watch?v=<id>` | `youtube_<id>.png` |
| Detik | `/d-<id>/` | `detik_d-<id>.png` |
| CNN Indonesia | `/<id>/` | `cnn_<id>.png` |

---

### `content-checker.py`

Ekstrak metadata + media dari URL konten media sosial secara langsung (tanpa keyword search).
Menggunakan yt-dlp sebagai unified extractor untuk semua platform.

**Library utama:** `yt-dlp`, `python-dotenv`

> Jalankan dengan **path langsung** (bukan `-m`) karena nama file mengandung tanda hubung.

**Args:**

| Arg | Type | Required | Default | Keterangan |
|-----|------|----------|---------|------------|
| `--url` | str+ | Ya | — | Satu atau lebih URL konten yang diekstrak |

**Cara eksekusi:**
```bash
python scripts/crawler/content-checker.py \
    --url "https://www.youtube.com/watch?v=..." \
          "https://www.tiktok.com/@user/video/..."
```

**Platform yang didukung:** YouTube, TikTok, Instagram (public), Twitter/X

**Alur kerja:**
1. Untuk setiap URL: deteksi platform → buat subdirektori temp per URL (`temp/<unique_id>/`)
2. **Step 1 — Download penuh:** `yt_dlp.extract_info(url, download=True)`
   - Handle playlist/carousel: iterasi `info["entries"]`
   - Kumpulkan path file yang berhasil didownload
3. **Step 2 — Fallback metadata-only** (jika Step 1 gagal):
   - `yt_dlp.extract_info(url, download=False)` dengan `skip_download=True`
   - Text-only tweets (tanpa media) → disimpan sebagai `type="text"`, `file_path=[]`
4. Upload file ke MinIO → `crawl/<platform>/<unique_id>.<ext>`
5. Insert metadata ke MongoDB `social_media_posts` (`source: "direct_url"`)

**Deteksi `unique_id` dari URL:**

| Platform | Pattern | Format |
|----------|---------|--------|
| Instagram | `/p/<shortcode>/` | `instagram_<shortcode>` |
| TikTok | `/video/<id>` | `tiktok_<id>` |
| Twitter/X | `/status/<id>` | `twitter_<id>` |
| YouTube | `watch?v=<id>` | `youtube_<id>` |

---

## Setup & Instalasi

### 1. Python Dependencies

```bash
pip install -r scripts/crawler/requirements.txt
```

Atau dengan conda:
```bash
conda run -n aitf pip install -r scripts/crawler/requirements.txt
```

### 2. Playwright Browser

```bash
playwright install chromium
```

### 3. Node.js (untuk `twitter.py`)

Pastikan Node.js terinstall, lalu verifikasi tweet-harvest tersedia:
```bash
npx tweet-harvest --help
```

### 4. Environment Variables

Buat file `.env` di root project (`aitf-backend/.env`):

```env
# MongoDB
PAD_MONGO_HOST=
PAD_MONGO_PORT=
PAD_MONGO_USER=
PAD_MONGO_PASS=
PAD_MONGO_DB=

# MinIO
MINIO_ENDPOINT=...
MINIO_ACCESS_KEY=...
MINIO_SECRET_KEY=...
MINIO_BUCKET_NAME=...

# Instagram (untuk instagram.py)
INSTAGRAM_USERNAME=...
INSTAGRAM_PASSWORD=...

# Apify (untuk tiktok.py)
APIFY_API_FREE=apify_api_...
APIFY_API_PREMIUM=apify_api_...
```

---

## Menjalankan Tests

Test runner di `tests/test_crawlers.py` mensimulasikan cara AI Agent memanggil crawler:

```bash
conda run -n aitf python -m tests.test_crawlers
```

Runner memvalidasi:
- STDOUT dapat di-parse sebagai JSON valid
- JSON memiliki field `status`
- Jika `status == "success"`, maka `count > 0`
- Exit code = 0

---

## Arsitektur & Pola Desain

### Safety Net stdout

Setiap script dengan MinIO/MongoDB redirect stdout ke stderr di awal `__main__`,
memastikan tidak ada byte yang mencapai stdout kecuali satu `print()` terakhir:

```python
_real_stdout = sys.stdout
sys.stdout   = sys.stderr          # safety net aktif
# ... semua eksekusi di sini ...
sys.stdout = _real_stdout
print(json.dumps(response))        # satu-satunya output ke stdout
```

### `_stdout_to_stderr()` Context Manager

Digunakan untuk membungkus library pihak ketiga yang bisa print ke stdout
(Playwright, yt-dlp, Apify client):

```python
with _stdout_to_stderr():
    result = some_library_that_might_print()
```

### Temporary Directory

Semua file media didownload ke `tempfile.TemporaryDirectory()` yang otomatis
dibersihkan setelah upload ke MinIO selesai — tidak ada file sisa di disk:

```python
with tempfile.TemporaryDirectory() as tmp:
    temp_dir = Path(tmp)
    # download → upload MinIO
# temp_dir otomatis dihapus di sini
```

### Per-URL Subdirectory (`content-checker.py`)

Untuk menghindari konflik file antar URL dalam satu batch run:
```
temp/
├── youtube_6KP2W1djB6c/
│   └── 6KP2W1djB6c.mp4
└── tiktok_7628929672537034005/
    └── 7628929672537034005.mp4
```
