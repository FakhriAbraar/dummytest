import fitz  # PyMuPDF
import re
import os

def extract_and_clean_pdf(pdf_path):
    """
    Fungsi untuk mengekstrak dan membersihkan teks dari dokumen PDF hukum.
    Target: Parsing dan Cleaning (Menghilangkan header, footer, spasi berlebih)
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"Gagal membuka PDF '{pdf_path}': {e}")
        return ""

    full_text = []

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        text = page.get_text("text")
        
        # Jika teks kosong (biasanya karena PDF berupa hasil scan/gambar)
        if not text.strip():
            continue
            
        # Proses pembersihan teks dengan Regex
        text = re.sub(r'(?m)^\s*\d+\s*$', '', text) # Hapus nomor halaman
        text = re.sub(r'(?i)presiden republik indonesia', '', text)
        text = re.sub(r'(?i)salinan', '', text)
        
        text = re.sub(r'\n+', '\n', text)  # Hilangkan baris kosong ganda
        text = re.sub(r' +', ' ', text)    # Hilangkan spasi ganda
        
        full_text.append(text.strip())

    cleaned_document = "\n".join(full_text)
    return cleaned_document

# --- CARA PENGGUNAAN ---
if __name__ == "__main__":
    # Ini adalah daftar nama file yang sesuai dengan folder GitHub kamu
    daftar_pdf = [
        "PP_Nomor_17_Tahun_2025.pdf",
        "UU_Nomor_1_Tahun_2024.pdf",
        "UU_Nomor_27_Tahun_2022.pdf"
    ]
    
    for pdf_file in daftar_pdf:
        print(f"Sedang memproses dokumen: {pdf_file} ...")
        
        # Cek apakah file benar-benar ada di folder
        if not os.path.exists(pdf_file):
            print(f"[-] File {pdf_file} tidak ditemukan di folder ini.\n")
            continue
            
        hasil_teks = extract_and_clean_pdf(pdf_file)
        
        # Pastikan hasil_teks tidak kosong sebelum membuat file .txt
        if hasil_teks.strip():
            nama_file_txt = f"cleaned_{pdf_file.replace('.pdf', '.txt')}"
            with open(nama_file_txt, "w", encoding="utf-8") as f:
                f.write(hasil_teks)
            print(f"[+] Berhasil dibersihkan dan disimpan sebagai: {nama_file_txt}\n")
        else:
            print(f"[-] Gagal memproses {pdf_file} (Mungkin PDF hasil scan gambar atau format tidak terbaca).\n")
            
    print("Semua proses Parsing dan Cleaning selesai!")