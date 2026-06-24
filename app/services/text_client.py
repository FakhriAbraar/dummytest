"""Tim 1 Text classifier client (DEPRECATED - Migrated to itspad).

Semua call dialihkan ke itspad_client.py.
"""
from __future__ import annotations

from app.services.itspad_client import classify_text as _classify_text

async def classify_text(text_content: str = "") -> dict:
    """Klasifikasi teks via endpoint itspad."""
    return await _classify_text(text_content)
