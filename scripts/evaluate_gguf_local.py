import json
import time
import os
from llama_cpp import Llama
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

MODEL_PATH = BASE_DIR / "models" / "keyword_generator" / "ministral-3b-base-f16.gguf"
DATASET_FILE = BASE_DIR / "scripts" / "keygen_stresstest.json"
REPORT_FILE = "laporan_evaluasi_2.5_1.5b_instruct_REVISI.md"

def run_gguf_evaluation():
    if not MODEL_PATH.exists():
        print(f"[-] ERROR FATAL: File model {MODEL_PATH} tidak ditemukan!")
        return
        
    if not DATASET_FILE.exists():
        print(f"[-] ERROR FATAL: File dataset {DATASET_FILE} tidak ditemukan!")
        return
    
    print(f"[*] Memuat Model GGUF ke RAM... (Kipas laptop lo bakal berisik bentar)")
    llm = Llama(
        model_path=str(MODEL_PATH),
        n_gpu_layers=-1, 
        n_ctx=2048,
        chat_format="chatml", # <--- BUAT QWEN INSTRUCT!
        verbose=False
    )

    with open(DATASET_FILE, "r", encoding="utf-8") as f:
        test_cases = json.load(f)

    print(f"[*] Memulai Evaluasi Model Chat untuk {len(test_cases)} baris data...\n")

    report_content = "# Laporan Stress Test Model GGUF Lokal (Qwen 2.5 Instruct)\n\n"
    report_content += "| No | Input Teks (Snippet) | Ekspektasi | Prediksi Model | Latency (s) |\n"
    report_content += "|---|---|---|---|---|\n"

    total_waktu = 0

    for idx, case in enumerate(test_cases, 1):
        input_text = case.get("input") or case.get("query", "")
        # Ambil instruksi asli dari dataset kalo ada, kalo nggak pakai default
        instruction_text = case.get("instruction", "Ekstrak kata kunci, slang, atau modus baru dari konten berikut.")
        
        expected_output = case.get("output", [])
        if not expected_output:
            expected_output = [case.get("expected_action", "N/A")]
        
        print(f"[{idx}/{len(test_cases)}] Mengeksekusi model...")
        
        # 2. PROMPT WAJIB PAKAI FORMAT CHAT (SYSTEM & USER)
        messages = [
            {"role": "system", "content": "Anda adalah sistem ekstraksi kata kunci. Keluarkan hasil HANYA dalam format JSON array of strings."},
            {"role": "user", "content": f"{instruction_text}\n\n{input_text}"}
        ]
        
        start_time = time.time()
        
        try:
            # 3. TEMBAK PAKAI CHAT COMPLETION
            response = llm.create_chat_completion(
                messages=messages,
                max_tokens=128, # Kasih ruang nafas buat nulis JSON
                temperature=0.1
            )
            
            raw_output = response['choices'][0]['message']['content']
            
            # 4. PARSING JSON YANG BENER (Buang markdown ```json)
            clean_str = raw_output.replace('```json', '').replace('```', '').strip()
            
            try:
                parsed_list = json.loads(clean_str)
                if isinstance(parsed_list, list):
                    model_output_list = [str(x) for x in parsed_list]
                else:
                    model_output_list = [clean_str]
            except json.JSONDecodeError:
                # Fallback kalau format AI masih agak ngaco
                model_output_list = [clean_str]
                
        except Exception as e:
            model_output_list = [f"ERROR: {e}"]
            
        latency = time.time() - start_time
        total_waktu += latency
        
        # Rapihkan teks buat tabel Markdown
        clean_input = input_text.replace('\n', ' ')[:80] + "..." 
        str_expected = ", ".join(expected_output)
        str_model = ", ".join(model_output_list)
        
        report_content += f"| {idx} | `{clean_input}` | *{str_expected}* | **{str_model}** | {latency:.2f} |\n"
        print(f"    -> Hasil: {str_model} ({latency:.2f}s)")

    # Tulis Report
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(report_content)

    print("\n" + "="*50)
    print("EVALUASI GGUF SELESAI!")
    print(f"Total Data Evaluasi : {len(test_cases)}")
    print(f"Rata-rata Latency   : {(total_waktu/len(test_cases)):.2f} detik/request")
    print(f"Laporan Markdown    : {REPORT_FILE}")
    print("="*50)

if __name__ == "__main__":
    run_gguf_evaluation()