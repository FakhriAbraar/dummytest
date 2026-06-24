"""Tim 3 Visual classifier client (DEPRECATED - Migrated to itspad).

Semua call dialihkan ke itspad_client.py.
"""
from __future__ import annotations

from app.services.itspad_client import classify_visual as _classify_visual

async def classify_visual(
    context_text: str = "",
    image_urls: list[str] | None = None,
    content_type: str = "image",
) -> dict:
    """Klasifikasi visual via endpoint itspad."""
    return await _classify_visual(context_text, image_urls, content_type)
