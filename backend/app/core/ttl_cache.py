"""Tiny thread-safe TTL cache for hot read-only API data.

The portals poll read endpoints constantly (admin every 15s, shopkeeper/student
on refresh), but most of that data changes rarely. This cache serves repeat
reads from memory instead of doing another Supabase round trip. Values hold a
short TTL and every write to the underlying resources calls ``clear()``, so
staleness is bounded to a few seconds at most.

Note: this cache is per serverless instance (in-process). Across instances it
is eventually consistent — acceptable for the short TTLs used here.
"""
from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_store: dict[str, tuple[float, Any]] = {}


def get(key: str) -> Any | None:
    """Return the cached value or ``None`` (expired entries are dropped)."""
    with _lock:
        item = _store.get(key)
        if not item:
            return None
        expires_at, value = item
        if time.monotonic() >= expires_at:
            _store.pop(key, None)
            return None
        return value


def set(key: str, value: Any, ttl: float) -> None:
    with _lock:
        _store[key] = (time.monotonic() + ttl, value)


def clear() -> None:
    """Drop every entry — call this after any write to cached resources."""
    with _lock:
        _store.clear()