"""Run a real Redis server *inside* the backend process when nothing else is set.

Why
---
The shared read cache (``app/core/redis_cache.py``) normally talks to an external
Redis: Upstash/Vercel KV over REST, or a ``REDIS_URL``. Both need a credential,
which this project does not have, so in production the cache silently fell back
to the Postgres ``app_cache`` table and ``/health`` reported
``redis.enabled: false``.

This module closes that gap with **no credentials at all**: it boots a real
``redis-server`` (via the ``redislite`` wheel, which bundles a static binary) on
a **unix domain socket inside the container**, and hands the resulting
``unix://…`` URL to the normal transport. Nothing is exposed to the network and
nothing is written to disk (persistence is off — this is a cache).

How to turn it off
------------------
* ``DETOMSITE_EMBEDDED_REDIS=0`` (also ``off``/``false``/``no``) — and only
  starts when no external cache is configured, so a real ``REDIS_URL`` or
  ``KV_REST_API_URL`` always wins. An env var is required because the production
  service's environment cannot be edited without dashboard access.

Honest trade-off
----------------
On a **single-instance** host the in-process ``ttl_cache`` already serves most
reads (``/health`` → ``cache.memory.hit_rate`` shows ~0.83), so this second layer
is largely redundant *there* and adds one process to the container. It earns its
place as the shared-cache implementation that becomes correct the moment the
service runs more than one instance, and it makes the real RESP transport
exercised and visible instead of dormant. Memory is capped at 64 MB with
allkeys-lru so it cannot starve the API on a small instance, and every failure
path degrades to the Postgres cache.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# The opt-out switch. Also read at import time by the test suite, which sets it
# to "0" so no server is ever started while testing.
ENV_FLAG = "DETOMSITE_EMBEDDED_REDIS"

# 64 MB is plenty for list snapshots and small enough to be harmless next to a
# 512 MB container. allkeys-lru keeps a burst of large keys from evicting the
# API's own working set.
MAX_MEMORY = "64mb"

_lock = threading.Lock()
_server: Optional[Any] = None      # redislite.Redis — keeps the child alive
_url = ""                          # unix:// URL handed to the cache transport


def _flag() -> str:
    return (os.environ.get(ENV_FLAG) or "").strip().lower()


def wanted() -> bool:
    """True when the embedded server should run (see the module docstring)."""
    if _flag() in ("0", "off", "false", "no"):
        return False

    # An externally managed cache always wins — never shadow a real Redis.
    if (settings.REDIS_URL or "").strip():
        return False
    if (settings.KV_REST_API_URL or "").strip() or (settings.UPSTASH_REDIS_REST_URL or "").strip():
        return False
    return True


def start() -> str:
    """Boot the embedded server; return its URL, or ``""`` if it is not running.

    Idempotent and thread-safe, and never raises: every failure path logs and
    leaves the cache on its Postgres fallback.
    """
    global _server, _url
    with _lock:
        if _url:
            return _url
        if not wanted():
            return ""
        try:
            import redislite  # bundled redis-server binary
        except Exception as e:
            logger.warning("Embedded Redis unavailable (%s) — reads use the Postgres cache", e)
            return ""

        data_dir = Path(tempfile.gettempdir()) / "detomsite-redislite"
        try:
            if data_dir.exists():
                shutil.rmtree(data_dir, ignore_errors=True)
            data_dir.mkdir(parents=True, exist_ok=True)
            # The socket is the only access path, so keep it owner-only.
            os.chmod(data_dir, 0o700)
            _server = redislite.Redis(
                str(data_dir / "cache.db"),
                serverconfig={
                    "save": "",              # cache only: never fsync, never persist
                    "appendonly": "no",
                    "maxmemory": MAX_MEMORY,
                    "maxmemory-policy": "allkeys-lru",
                },
            )
            socket_path = (_server.connection_pool.connection_kwargs or {}).get("path")
            if not socket_path:
                raise RuntimeError("embedded redis exposed no socket path")
            # redis-py reads the socket from the URL path, not a `socket=` arg.
            _url = f"unix://{socket_path}?db=0"
            logger.info("Embedded Redis cache started (%s, maxmemory %s)", _url, MAX_MEMORY)
            return _url
        except Exception as e:
            logger.warning("Embedded Redis failed to start (%s) — reads use the Postgres cache", e)
            _server, _url = None, ""
            return ""


def stop() -> None:
    """Shut the embedded server down (lifespan shutdown)."""
    global _server, _url
    with _lock:
        server, _server, _url = _server, None, ""
        if server is None:
            return
        try:
            server.shutdown()
        except Exception as e:  # never let teardown break shutdown
            logger.debug(f"Embedded Redis shutdown notice: {e}")


def status() -> dict[str, Any]:
    """Small dict for logs/tests — never exposes a path outside the container."""
    return {"running": bool(_url), "maxmemory": MAX_MEMORY}
