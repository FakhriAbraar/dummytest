from minio import Minio
from app.settings import settings

def test_minio_connection():
    client = Minio(
        endpoint=f"{settings.minio_host}:{settings.minio_port}",
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_use_ssl,
    )
    
    try:
        found = client.bucket_exists(settings.minio_bucket)
        if not found:
            client.make_bucket(settings.minio_bucket)
            print(f"Bucket '{settings.minio_bucket}' berhasil dibuat.")
        else:
            print(f"Bucket '{settings.minio_bucket}' sudah ada.")
            
    except Exception as e:
        print(f"Koneksi gagal: {e}")

if __name__ == "__main__":
    test_minio_connection()