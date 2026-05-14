import json
import sys
import os
import glob

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.qdrant_db import client, COLLECTION_NAME, init_qdrant
from sentence_transformers import SentenceTransformer
from qdrant_client.http.models import PointStruct

print("[*] Loading Model Embedding multilingual-e5-large...")
model = SentenceTransformer("intfloat/multilingual-e5-large")

def seed_all_data():
    init_qdrant()
    
    json_files = glob.glob("data/*.json")
    if not json_files:
        print("[-] Tidak ada file JSON ditemukan di folder 'data/'")
        return

    all_points = []
    point_id = 1

    for file_path in json_files:
        print(f"[*] Membaca {file_path}...")
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        for item in data:
            if 'instruction' in item and 'input' in item and 'output' in item:
                text_content = f"passage: Instruksi: {item['instruction']}. Konteks: {item['input']}. Label/Output: {item['output']}"
            else:
                dokumen = item.get('document_title', 'Dokumen Hukum')
                bab = item.get('bab', '')
                pasal = item.get('pasal', '')
                text_content = f"passage: Dokumen: {dokumen}. {bab} {pasal}. Isi: {item.get('konten', '')}"
            
            vector = model.encode(text_content).tolist()
            
            point = PointStruct(
                id=point_id,
                vector=vector,
                payload=item
            )
            all_points.append(point)
            point_id += 1

    print(f"[*] Sending total {len(all_points)} data ke Qdrant Cloud ({COLLECTION_NAME})...")
    
    client.upload_points(
        collection_name=COLLECTION_NAME,
        points=all_points,
        batch_size=50
    )
    print("[+] Seeding Done!")

if __name__ == "__main__":
    seed_all_data()