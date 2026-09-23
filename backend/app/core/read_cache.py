"""Three-layer read cache shared by every portal polling endpoint.

    layer 1  ``ttl_cache``    — per-instance memory (microseconds)
    layer 2  ``redis_cache``  — shared Redis (single-digit ms, warms every instance)
    layer 3  ``shared_cache`` — the Postgres ``app_cache`` table (fallback)
    layer 4  the loader       — the real query

``cached_read`` replaces the hand-rolled copies of this pattern that had drifted
apart across ``local.py`` and ``local_admin.py`` (some wrote only the in-process
layer, some only Postgres) with one predictable order, so a warm Redis is shared
by every serverless instance instead of every instance paying for the same query.

Cache keys embed a SHA-256 digest of the call arguments instead of their raw
``repr``: those arguments include the authenticated user row (name, e-mail,
phone), and a cache store is not the place for personal data. The digest keeps
per-user / per-filter results isolated while persisting no PII.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import threading
from typing import Any

from app.core import redis_cache, shared_cache, ttl_cache

logger = logging.getLogger(__name__)


def cache_key(key: str, args: tuple = (), kwargs: dict | None = None) -> str:
    """Namespace ``key`` by a stable digest of the call arguments.

    Two students asking for ``/orders`` must never share an entry, and the raw
    arguments (which carry names and phone numbers) must not be written into a
    shared cache store — hence the digest. ``repr`` of the usual argument types
    (str/int/None/bool/datetime/dict/list rows) is stable across processes, so
    the digest is too and every instance builds the same key.
    """
    if not args and not kwargs:
        return key
    material = f"{args!r}|{sorted((kwargs or {}).items())!r}"
    digest = hashlib.sha256(material.encode("utf-8", "replace")).hexdigest()[:16]
    return f"{key}:{digest}"


async def cached_read(ttl: float, key: str, loader, *args, **kwargs) -> Any:
    """Return ``loader(*args, **kwargs)``, serving it from a warm cache if possible.

    ``key`` must identify the resource and every argument that changes the
    result (they are folded into the key), otherwise filtered lists cross wires.
    Synchronous loaders (the store) run in a worker thread; an async loader that
    merges several sources is awaited instead — both are supported.
    """
    store_key = cache_key(key, args, kwargs)

    value = ttl_cache.get(store_key)
    if value is not None:
        return value

    value = await redis_cache.get(store_key)
    if value is not None:
        # Promote the shared entry into this instance's memory for free hits.
        ttl_cache.set(store_key, value, ttl)
        return value

    if shared_cache.enabled():
        value = await asyncio.to_thread(shared_cache.get, store_key)
        if value is not None:
            ttl_cache.set(store_key, value, ttl)
            redis_cache.set_pair_bg(store_key, value, ttl)
            return value

    value = await asyncio.to_thread(loader, *args, **kwargs)
    if inspect.isawaitable(value):
        value = await value

    ttl_cache.set(store_key, value, ttl)
    redis_cache.set_pair_bg(store_key, value, ttl)
    if shared_cache.enabled():
        # Fire-and-forget so a cold load never waits on the fallback layer.
        try:
            threading.Thread(
                target=shared_cache.set_pair, args=(store_key, value, ttl), daemon=True
            ).start()
        except Exception as e:
            logger.debug(f"shared cache write skipped: {e}")
    return value


def clear_local() -> None:
    """Drop the in-process layer only — the cheap half of :func:`clear`.

    Used where a caller needs this instance to be fresh *immediately* and the
    shared layers can follow on their own (see ``redis_cache.spawn``).
    """
    ttl_cache.clear()


async def clear() -> None:
    """Invalidate every layer — call after any write to a cached resource."""
    ttl_cache.clear()
    await redis_cache.clear()
    if shared_cache.enabled():
        try:
            await asyncio.to_thread(shared_cache.clear)
        except Exception as e:
            logger.debug(f"shared cache clear skipped: {e}")


def clear_bg() -> None:
    """Schedule :func:`clear` without waiting for the shared stores (never raises).

    The in-process layer is dropped synchronously, so the instance that handled
    the write already serves fresh data; the Redis/Postgres copies follow within
    milliseconds.
    """
    ttl_cache.clear()
    redis_cache.spawn(clear())
