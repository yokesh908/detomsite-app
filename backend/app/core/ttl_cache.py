"""Tiny thread-safe TTL cache for hot read-only API data.

The portals poll read endpoints constantly (admin every 15s, shopkeeper/student
on refresh), but most of that data changes rarely. This cache serves repeat
reads from memory instead of doing another Supabase round trip. Values hold a
short TTL and every write to the underlying resources calls ``clear()``, so
staleness is bounded to a few seconds at most.

Note: this cache is per serverless instance (in-process). Across instances it
is eventually consistent — acceptable for the short TTLs used here.

Counters
--------
Hits/misses are tracked per layer so ``/health`` can *show* whether the cache is
doing any work. That matters because the right cache depends on the deployment,
not on taste: on a single-instance host (Render free) the in-process layer serves
essentially every repeat read, while a shared Redis only pays off once requests
start landing on different instances (Vercel/serverless, or a scaled service).
"""
from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_store: dict[str, tuple[float, Any]] = {}
_hits = 0
_misses = 0
_evictions = 0


def get(key: str) -> Any | None:
    """Return the cached value or ``None`` (expired entries are dropped)."""
    global _hits, _misses, _evictions
    with _lock:
        item = _store.get(key)
        if not item:
            _misses += 1
            return None
        expires_at, value = item
        if time.monotonic() >= expires_at:
            _store.pop(key, None)
            _evictions += 1
            _misses += 1
            return None
        _hits += 1
        return value


def set(key: str, value: Any, ttl: float) -> None:
    with _lock:
        _store[key] = (time.monotonic() + ttl, value)


def clear() -> None:
    """Drop every entry — call this after any write to cached resources."""
    with _lock:
        _store.clear()


def stats() -> dict[str, Any]:
    """Hit/miss counters plus the live entry count (for ``/health``)."""
    with _lock:
        total = _hits + _misses
        return {
            "entries": len(_store),
            "hits": _hits,
            "misses": _misses,
            "expired": _evictions,
            "hit_rate": round(_hits / total, 3) if total else None,
        }