import yt_dlp
import json
import os
import time

# ==========================================
# KONFIGURASI PROTOTYPE
# ==========================================
FILE_KEYWORD_INPUT = "data/input_keywords.json" 
JUMLAH_VIDEO_PER_KEYWORD = 10                 
DOWNLOAD_VIDEO_FISIK = True                 

# ==========================================
# FUNGSI 1: SCRAPING METADATA (FILTER KATA PER KATA)
# ==========================================
def scrape_youtube_metadata(keyword, max_results=5):
    ydl_opts = {
        'quiet': True,              
        'extract_flat': False,      
        'ignoreerrors': True,       
        'no_warnings': True
    }

    limit_pencarian = max_results * 3 
    search_query = f"ytsearch{limit_pencarian}:{keyword}"
    timestamp = datetime.now().isoformat()
    data_list = []
    
    folder_induk = f"data/youtube_{keyword.replace(' ', '_')}_assets"
    os.makedirs(folder_induk, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"🎬 TAHAP 1: MENCARI VIDEO RELEVAN UNTUK '{keyword}'")
    print(f"{'='*60}")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            result = ydl.extract_info(search_query, download=False)
            
            if result and 'entries' in result:
                valid_count = 0 
                
                # ----------------------------------------------------
                # PERSIAPAN FILTER: Memecah keyword menjadi list kata
                # Contoh: "kasus cyberbullying" -> ["kasus", "cyberbullying"]
                # ----------------------------------------------------
                kata_kunci_list = keyword.lower().split()
                
                for video in result['entries']:
                    if not video: continue
                    if valid_count >= max_results: break
                        
                    judul_asli = video.get('title', 'Tanpa Judul')
                    deskripsi = video.get('description', '')
                    creator = video.get('uploader', '')
                    
                    # Gabungkan semua teks video menjadi satu blok teks panjang
                    teks_gabungan = f"{judul_asli} {deskripsi} {creator}".lower()
                    
                    # ----------------------------------------------------
                    # LOGIKA FILTER BARU: Cek apakah ada kata yang cocok
                    # ----------------------------------------------------
                    lolos_filter = False
                    for kata in kata_kunci_list:
                        # Abaikan kata sambung pendek (seperti 'di', 'ke', 'dan')
                        # Cek apakah kata kunci (panjang > 2) ada di teks gabungan
                        if len(kata) > 2 and kata in teks_gabungan:
                            lolos_filter = True
                            break # Cukup 1 kata cocok, langsung loloskan!
                    
                    if not lolos_filter:
                        print(f"  -> 🚫 SKIP (Tidak Relevan): {judul_asli[:30]}...")
                        continue 
                    
                    valid_count += 1
                    raw_date = video.get('upload_date', '')
                    formatted_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}" if len(raw_date) == 8 else raw_date
                    video_id = video.get('id')
                    
                    path_video = os.path.join(folder_induk, str(video_id)).replace("\\", "/")
                    os.makedirs(path_video, exist_ok=True) 

                    item = {
                        "scraped_at": timestamp,
                        "platform": "YouTube",
                        "keyword_pencarian": keyword,
                        "video_id": video_id,
                        "judul": judul_asli,
                        "related_link": video.get('webpage_url') or f"https://www.youtube.com/watch?v={video_id}",
                        "creator": creator,
                        "tanggal_upload": formatted_date,
                        "views": video.get('view_count'),
                        "likes": video.get('like_count', 0) if video.get('like_count') is not None else 0,
                        "jumlah_komentar": video.get('comment_count', 0) if video.get('comment_count') is not None else 0,
                        "caption": deskripsi,
                        "Path": path_video
                    }
                    data_list.append(item)
                    
                    file_metadata_lokal = f"{path_video}/metadata.json"
                    with open(file_metadata_lokal, "w", encoding="utf-8") as f:
                        json.dump(item, f, indent=4, ensure_ascii=False)

                    print(f"[{valid_count}/{max_results}] ✔️ TERSIMPAN (Folder: {video_id})")
                
                if valid_count < max_results:
                    print(f"⚠️ PENCARIAN DIHENTIKAN: Hanya menemukan {valid_count} video relevan.")

        except Exception as e:
            print(f"❌ Error saat scraping metadata: {e}")

    return data_list

# ==========================================
# FUNGSI 2: SCRAPING KOMENTAR
# ==========================================
def scrape_komentar_ke_folder(video_data_list): # Menerima list data di memori
    ydl_opts_comments = {
        'quiet': True, 'extract_flat': False, 'skip_download': True, 
        'getcomments': True, 'extractor_args': {'youtube': {'comment_sort': ['top'], 'max_comments': ['30,all,all']}},
        'ignoreerrors': True, 'no_warnings': True
    }

    print(f"\n💬 TAHAP 2: KOMENTAR")
    with yt_dlp.YoutubeDL(ydl_opts_comments) as ydl:
        for index, video in enumerate(video_data_list, start=1):
            video_id = video.get('video_id')
            lokasi = video.get('Path') # Membaca key 'Path'
            
            print(f"[{index}/{len(video_data_list)}] Menarik komentar dari ID: {video_id}...")
            
            try:
                info = ydl.extract_info(video_id, download=False)
                if not info: continue
                comments = info.get('comments', [])
                if not comments: 
                    print("  -> ⚠️ Tidak ada komentar / Dinonaktifkan.")
                    continue
                
                hasil_komentar = [{"video_id": video_id, "id_komentar": c.get('id'), "id_parent": c.get('parent'), "tipe": "Komentar Utama" if (c.get('parent') == 'root' or c.get('parent') is None) else "Balasan", "nama_channel": c.get('author'), "isi_komentar": c.get('text')} for c in comments]
                
                with open(os.path.join(lokasi, "komentar.json"), "w", encoding="utf-8") as f:
                    json.dump(hasil_komentar, f, indent=4, ensure_ascii=False)
                print(f"  -> ✔️ Berhasil menyimpan {len(comments)} komentar.")
            except:
                print("  -> ❌ Gagal menarik komentar.")

# ==========================================
# FUNGSI 3: DOWNLOAD VIDEO (BISA DIMATIKAN)
# ==========================================
def download_video_ke_folder(video_data_list): # Menerima list data di memori
    if not DOWNLOAD_VIDEO_FISIK:
        print("\n⏭️ TAHAP 3: UNDUH VIDEO DILOMPATI (Set DOWNLOAD_VIDEO_FISIK = True untuk mengunduh)")
        return

    print(f"\n⬇️ TAHAP 3: UNDUH VIDEO FISIK")
    for index, video in enumerate(video_data_list, start=1):
        url = video.get('related_link')
        lokasi = video.get('Path') # Membaca key 'Path'
        
        print(f"[{index}/{len(video_data_list)}] Mengunduh video ke folder {lokasi}...")
        
        ydl_opts_dl = {'format': 'best', 'outtmpl': f'{lokasi}/video_lengkap.%(ext)s', 'quiet': True, 'ignoreerrors': True, 'no_warnings': True}
        with yt_dlp.YoutubeDL(ydl_opts_dl) as ydl:
            try: 
                ydl.download([url])
                print("  -> ✔️ Download berhasil.")
            except: 
                print("  -> ❌ Gagal mengunduh.")

# ==========================================
# EKSEKUSI PROTOTYPE (PIPELINE IN-MEMORY)
# ==========================================
from datetime import datetime

# 1. Buat file dummy output model jika belum ada
os.makedirs(os.path.dirname(FILE_KEYWORD_INPUT), exist_ok=True)
if not os.path.exists(FILE_KEYWORD_INPUT):
    with open(FILE_KEYWORD_INPUT, "w", encoding="utf-8") as f:
        json.dump(["prabowo", "jokowi"], f, indent=4)

# 2. Baca keyword
with open(FILE_KEYWORD_INPUT, "r", encoding="utf-8") as f:
    daftar_keyword_dari_model = json.load(f)

print(f"🚀 MEMULAI PROTOTYPE CRAWLER...")

# 3. Eksekusi Berurutan tanpa Index File
for kw in daftar_keyword_dari_model:
    # list_data_video akan berisi LIST of DICTIONARY dari Tahap 1
    list_data_video = scrape_youtube_metadata(kw, max_results=JUMLAH_VIDEO_PER_KEYWORD)
    
    # Jika list tidak kosong, langsung oper list tersebut ke fungsi selanjutnya
    if list_data_video:
        scrape_komentar_ke_folder(list_data_video)
        download_video_ke_folder(list_data_video)

print("\n🏁 PROTOTYPE SELESAI DIEKSEKUSI!")