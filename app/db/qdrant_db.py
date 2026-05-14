import os
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models

load_dotenv()

APP_ENV = os.getenv("APP_ENV", "development")
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

if APP_ENV == "production":
    COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_PROD", "pad_hukum_prod")
else:
    COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_DEV", "pad_hukum_dev")

client = QdrantClient(
    url=QDRANT_URL,
    api_key=QDRANT_API_KEY,
    timeout=60.0
)

def init_qdrant():
    try:
        if not client.collection_exists(COLLECTION_NAME):
            print(f"[*] Membuat Collection Baru: {COLLECTION_NAME}...")
            client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=models.VectorParams(
                    size=1024, 
                    distance=models.Distance.COSINE
                ),
            )
            print("[+] Collection sukses dibuat!")
        else:
            print(f"[+] Collection '{COLLECTION_NAME}' sudah siap.")
    except Exception as e:
        print(f"[-] Gagal konek ke Qdrant: {e}")