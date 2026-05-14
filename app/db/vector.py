import os
import logging
from qdrant_client import AsyncQdrantClient

logger = logging.getLogger(__name__)

qdrant_client: AsyncQdrantClient | None = None

async def connect_qdrant() -> None:
    global qdrant_client
    
    host = os.getenv("PAD_QDRANT_HOST", "localhost")
    port = int(os.getenv("PAD_QDRANT_PORT", 6333))
    
    logger.info(f"Mencoba koneksi ke Qdrant di {host}:{port}...")
    
    try:
        qdrant_client = AsyncQdrantClient(host=host, port=port)
        
        await qdrant_client.get_collections()
        
        logger.info("✅ Qdrant berhasil terkoneksi!")
    except Exception as e:
        logger.error(f"❌ Gagal konek ke Qdrant: {e}")
        raise e

async def disconnect_qdrant() -> None:
    global qdrant_client
    if qdrant_client is not None:
        logger.info("Menutup koneksi Qdrant...")
        await qdrant_client.close()
        qdrant_client = None
        logger.info("✅ Koneksi Qdrant ditutup.")