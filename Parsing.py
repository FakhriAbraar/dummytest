import fitz  # PyMuPDF
import re

def extract_and_clean_pdf(pdf_path):
    """
    Fungsi untuk mengekstrak dan membersihkan teks dari dokumen PDF hukum.
    Target: Parsing dan Cleaning (Menghilangkan header, footer, spasi berlebih)
    """
    # 1. PDF Parsing: Membuka dokumen PDF
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"Gagal membuka PDF: {e}")
        return ""

    full_text = []

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        text = page.get_text("text")
        
        # 2. PDF Cleaning: Proses pembersihan teks dengan Regex
        
        # a. Hapus nomor halaman (biasanya angka tunggal di atas atau bawah halaman)
        text = re.sub(r'(?m)^\s*\d+\s*$', '', text)
        
        # b. Hapus header/footer dokumen yang berulang (contoh disesuaikan dengan dokumen)
        # Misalnya: "PRESIDEN REPUBLIK INDONESIA", "SALINAN", dll.
        text = re.sub(r'(?i)presiden republik indonesia', '', text)
        text = re.sub(r'(?i)salinan', '', text)
        
        # c. Perbaiki spasi yang berantakan (multiple spaces atau newlines berlebih)
        text = re.sub(r'\n+', '\n', text)  # Hilangkan baris kosong ganda
        text = re.sub(r' +', ' ', text)    # Hilangkan spasi ganda
        
        full_text.append(text.strip())

    # Gabungkan seluruh teks menjadi satu string panjang
    cleaned_document = "\n".join(full_text)
    
    return cleaned_document

# --- CARA PENGGUNAAN ---
if __name__ == "__main__":
    # Ganti dengan path PDF hukum kamu (misal: "PP_TUNAS_No_17_2025.pdf")
    pdf_file_path = "UU_Nomor_17_Tahun_2025.pdf" 
    
    hasil_teks = extract_and_clean_pdf(pdf_file_path)
    
    # Simpan hasil teks bersih ke file .txt
    with open("cleaned_dokumen_hukum.txt", "w", encoding="utf-8") as f:
        f.write(hasil_teks)
        
    print("PDF Parsing dan Cleaning selesai!")