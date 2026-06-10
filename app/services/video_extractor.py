"""Video Keyframe Extractor via Scene Detection (Production Mode).

Memecah video menjadi beberapa keyframe berdasarkan perubahan scene,
menyimpan keyframe ke MinIO sebagai bukti audit (evidence),
lalu mengembalikan array of Presigned URLs siap kirim ke LLM Vision API.
"""

from __future__ import annotations

import asyncio
import io
import os
import tempfile
import uuid
from datetime import timedelta

import cv2
import httpx
from minio.error import S3Error
from scenedetect import ContentDetector, detect

VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".mkv", ".avi")
MAX_KEYFRAMES = 10  
KEYFRAME_EXPIRE_SECONDS = 3600  


def _extract_keyframes_to_buffers(
    video_path: str,
    threshold: float = 27.0,
    max_frames: int = MAX_KEYFRAMES,
) -> list[bytes]:
    """Sinkron: Ekstrak keyframe dari video lokal, return list of JPEG bytes."""

    if not os.path.exists(video_path):
        print(f"[-] Video tidak ditemukan: {video_path}")
        return []

    print(f"[🎬] Menganalisis scene pada video: {video_path}")

    scene_list = detect(video_path, ContentDetector(threshold=threshold))

    if not scene_list:
        print("[🎬] Tidak ada perubahan scene drastis. Mengambil 1 frame di tengah video.")
        cap = cv2.VideoCapture(video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        if total_frames <= 0:
            print("[-] Video corrupt / 0 frame.")
            return []
        scene_list = [(0, total_frames)]  

    scenes_to_process = scene_list[:max_frames]
    extracted_buffers: list[bytes] = []
    cap = cv2.VideoCapture(video_path)

    for i, scene in enumerate(scenes_to_process):
        start_frame = scene[0].get_frames() if hasattr(scene[0], "get_frames") else scene[0]
        end_frame = scene[1].get_frames() if hasattr(scene[1], "get_frames") else scene[1]

        mid_frame = (int(start_frame) + int(end_frame)) // 2

        cap.set(cv2.CAP_PROP_POS_FRAMES, mid_frame)
        success, frame = cap.read()

        if success:
            encode_param = [cv2.IMWRITE_JPEG_QUALITY, 80]
            _, buffer = cv2.imencode(".jpg", frame, encode_param)
            extracted_buffers.append(buffer.tobytes())

    cap.release()
    print(f"[🎬] Berhasil mengekstrak {len(extracted_buffers)} keyframes dari {len(scenes_to_process)} scene.")

    return extracted_buffers


async def _upload_keyframes_to_minio(
    jpeg_buffers: list[bytes],
    video_source_name: str,
) -> list[str]:
    """Upload keyframe JPEG bytes ke MinIO, return list of object names."""
    from app.db.minio import get_minio_client
    from app.settings import settings

    minio_client = get_minio_client()
    bucket = settings.minio_bucket

    video_base = os.path.splitext(os.path.basename(video_source_name))[0]
    batch_id = uuid.uuid4().hex[:8]

    uploaded_object_names: list[str] = []

    for i, jpeg_bytes in enumerate(jpeg_buffers):
        object_name = f"keyframes/{video_base}/{batch_id}_scene_{i + 1}.jpg"
        stream = io.BytesIO(jpeg_bytes)

        try:
            await asyncio.to_thread(
                minio_client.put_object,
                bucket_name=bucket,
                object_name=object_name,
                data=stream,
                length=len(jpeg_bytes),
                content_type="image/jpeg",
            )
            uploaded_object_names.append(object_name)
            print(f"[📦] Keyframe {i + 1} disimpan ke MinIO: {object_name}")
        except S3Error as e:
            print(f"[-] Gagal upload keyframe {i + 1} ke MinIO: {e}")

    return uploaded_object_names


async def _get_presigned_urls(
    object_names: list[str],
    expire_seconds: int = KEYFRAME_EXPIRE_SECONDS,
) -> list[str]:
    """Generate presigned URLs untuk list of MinIO object names."""
    from app.db.minio import get_minio_client
    from app.settings import settings

    minio_client = get_minio_client()
    presigned_urls: list[str] = []

    for obj_name in object_names:
        try:
            url = await asyncio.to_thread(
                minio_client.presigned_get_object,
                bucket_name=settings.minio_bucket,
                object_name=obj_name,
                expires=timedelta(seconds=expire_seconds),
            )
            presigned_urls.append(url)
        except S3Error as e:
            print(f"[-] Gagal generate presigned URL untuk {obj_name}: {e}")

    return presigned_urls


async def process_video_from_minio(
    object_name: str,
    threshold: float = 27.0,
    max_frames: int = MAX_KEYFRAMES,
) -> list[str]:
    """Production pipeline: Download video dari MinIO → Ekstrak keyframe
    → Upload keyframe ke MinIO → Return presigned URLs."""
    from app.db.minio import get_minio_client
    from app.settings import settings

    print(f"[🎬] Downloading video dari MinIO: {object_name}")

    try:
        minio_client = get_minio_client()

        suffix = ".mp4"
        for ext in VIDEO_EXTENSIONS:
            if object_name.lower().endswith(ext):
                suffix = ext
                break

        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix, prefix="pad_minio_video_"
        ) as tmp:
            tmp_path = tmp.name

        await asyncio.to_thread(
            minio_client.fget_object,
            bucket_name=settings.minio_bucket,
            object_name=object_name,
            file_path=tmp_path,
        )
        print(f"[🎬] Video MinIO tersimpan di: {tmp_path}")

        jpeg_buffers = await asyncio.to_thread(
            _extract_keyframes_to_buffers, tmp_path, threshold, max_frames
        )

        try:
            os.unlink(tmp_path)
        except OSError:
            pass

        if not jpeg_buffers:
            return []

        object_names = await _upload_keyframes_to_minio(jpeg_buffers, object_name)

        import base64
        b64_uris = []
        for buf in jpeg_buffers:
            b64_str = base64.b64encode(buf).decode("utf-8")
            b64_uris.append(f"data:image/jpeg;base64,{b64_str}")

        print(f"[🎬] {len(b64_uris)} keyframes tersimpan di MinIO & siap dikirim sebagai Base64.")
        return b64_uris

    except Exception as e:
        print(f"[-] Gagal proses video dari MinIO: {e}")
        return []


async def process_video_from_url(
    video_url: str,
    threshold: float = 27.0,
    max_frames: int = MAX_KEYFRAMES,
) -> list[str]:
    """Production pipeline: Download video dari URL publik → Ekstrak keyframe
    → Upload keyframe ke MinIO → Return presigned URLs."""

    print(f"[🎬] Downloading video dari URL: {video_url[:80]}...")

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            resp = await client.get(video_url)
            resp.raise_for_status()

        suffix = ".mp4"
        for ext in VIDEO_EXTENSIONS:
            if video_url.lower().endswith(ext):
                suffix = ext
                break

        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix, prefix="pad_video_"
        ) as tmp:
            tmp.write(resp.content)
            tmp_path = tmp.name

        print(f"[🎬] Video tersimpan sementara di: {tmp_path} ({len(resp.content)} bytes)")

        jpeg_buffers = await asyncio.to_thread(
            _extract_keyframes_to_buffers, tmp_path, threshold, max_frames
        )

        try:
            os.unlink(tmp_path)
        except OSError:
            pass

        if not jpeg_buffers:
            return []

        ref_name = os.path.basename(video_url.split("?")[0]) or "remote_video"
        object_names = await _upload_keyframes_to_minio(jpeg_buffers, ref_name)
        
        import base64
        b64_uris = []
        for buf in jpeg_buffers:
            b64_str = base64.b64encode(buf).decode("utf-8")
            b64_uris.append(f"data:image/jpeg;base64,{b64_str}")

        print(f"[🎬] {len(b64_uris)} keyframes tersimpan di MinIO & siap dikirim sebagai Base64.")
        return b64_uris

    except Exception as e:
        print(f"[-] Gagal download/extract video dari URL: {e}")
        return []


async def process_media_url(url: str) -> list[str]:
    """Dispatcher utama: deteksi apakah URL adalah video atau gambar.

    - Video → scene detection → keyframes disimpan ke MinIO → presigned URLs
    - Gambar → return kosong (di-handle oleh caller pakai presigned URL)
    """
    is_video = url.lower().endswith(VIDEO_EXTENSIONS)

    if is_video:
        if url.startswith("http"):
            return await process_video_from_url(url)
        else:
            return await process_video_from_minio(url)

    return []


async def get_presigned_url_for_image(object_name: str) -> str | None:
    """Helper: Generate presigned URL untuk gambar yang sudah ada di MinIO."""
    from app.db.minio import get_minio_client
    from app.settings import settings

    try:
        minio_client = get_minio_client()
        url = await asyncio.to_thread(
            minio_client.presigned_get_object,
            bucket_name=settings.minio_bucket,
            object_name=object_name,
            expires=timedelta(seconds=KEYFRAME_EXPIRE_SECONDS),
        )
        return url
    except S3Error as e:
        print(f"[-] Gagal generate presigned URL untuk image {object_name}: {e}")
        return None
