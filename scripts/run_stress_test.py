import json
import requests
import time
import os

# Konfigurasi
API_URL = "http://localhost:8000/api/pad/v1/chat"
JSON_FILE = "chatbot_stress_test.json"
REPORT_FILE = "chatbot_evaluation_report.md"

def run_stress_test():
    if not os.path.exists(JSON_FILE):
        print(f"[-] File {JSON_FILE} tidak ditemukan! Bikin dulu sesuai format tadi.")
        return

    with open(JSON_FILE, "r", encoding="utf-8") as f:
        test_cases = json.load(f)

    print(f"[*] Memulai Stress Test untuk {len(test_cases)} skenario...")
    print(f"[*] Target Endpoint: {API_URL}\n")

    report_content = "# Laporan Hasil Stress Test RAG Chatbot PAD\n\n"
    report_content += "| No | Vektor Serangan | Pertanyaan | Ekspektasi | Jawaban Bot |\n"
    report_content += "|---|---|---|---|---|\n"

    success_count = 0
    failed_requests = 0

    for idx, case in enumerate(test_cases, 1):
        vektor = case["vektor_serangan"]
        query = case["query"]
        expected = case["expected_behavior"]
        
        print(f"[{idx}/{len(test_cases)}] Menguji vektor: {vektor}...")
        
        payload = {
            "user_message": query,
            "chat_history": []
        }

        try:
            start_time = time.time()
            response = requests.post(API_URL, json=payload, timeout=30)
            latency = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                bot_reply = data.get("data", {}).get("reply", "KOSONG")
                success_count += 1
            else:
                bot_reply = f"ERROR {response.status_code}: {response.text}"
                failed_requests += 1
                
        except Exception as e:
            bot_reply = f"REQUEST FAILED: {str(e)}"
            failed_requests += 1
            latency = 0

        # Bersihin enter/newline biar rapi pas dimasukin ke tabel Markdown
        clean_query = query.replace('\n', ' ')
        clean_expected = expected.replace('\n', ' ')
        clean_reply = bot_reply.replace('\n', '<br>')

        report_content += f"| {idx} | `{vektor}` | {clean_query} | *{clean_expected}* | **{clean_reply}** |\n"
        
        print(f"    -> Selesai dalam {latency:.2f} detik.")
        
        # Kasih jeda dikit biar API Hugging Face lo nggak kena rate limit (Too Many Requests)
        time.sleep(2)

    # Tulis ke file report
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(report_content)

    print("\n" + "="*50)
    print("STRESS TEST SELESAI!")
    print(f"Total Test     : {len(test_cases)}")
    print(f"Request Sukses : {success_count}")
    print(f"Request Gagal  : {failed_requests}")
    print(f"Laporan disimpan di: {REPORT_FILE}")
    print("="*50)
    print("\n[TUGAS QA]: Buka file Markdown tersebut, baca manual jawaban bot-nya, dan tentukan mana yang PASS dan FAIL berdasarkan ekspektasi!")

if __name__ == "__main__":
    run_stress_test()