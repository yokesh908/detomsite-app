"""Shared helper for the payment-screenshot upload directory.

Serverless platforms (Vercel) ship a READ-ONLY app directory, so we can never
write under the source tree. We instead put uploads in the platform's writable
temp dir (``/tmp`` on Vercel/Render/Linux, macOS/Linux local dev). ``/uploads``
is still the stable URL — only the backing directory changes.
"""
from __future__ import annotations

import os
import tempfile


def get_uploads_dir() -> str:
    env_dir = os.environ.get("DETOMSITE_UPLOADS_DIR", "").strip()
    if env_dir:
        return env_dir
    return os.path.join(tempfile.gettempdir(), "detomsite_uploads", "payments")


def ensure_uploads_dir() -> str:
    path = get_uploads_dir()
    os.makedirs(path, exist_ok=True)
    return path