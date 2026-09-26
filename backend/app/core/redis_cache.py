"""Redis-backed shared read cache (Upstash/Vercel KV REST or raw RESP).

Reads are served by up to three cache layers before the database is touched:

    1. ``ttl_cache``    — per-instance memory (microseconds, dies with the instance)
    2. ``redis_cache``  — THIS module: shared by every instance, single-digit ms
    3. ``shared_cache`` — the Postgres ``app_cache`` table (fallback, ~10-30 ms)
    4. the loader       — the real query

Redis matters most on serverless hosts (Vercel), where consecutive requests from
the same portal land on different instances: the in-process cache is cold almost
every time, so the heavy list queries ran on every poll. One shared Redis makes
every instance hit the same warm copy.

Two transports, picked automatically from the environment:

* **Upstash / Vercel KV REST** — ``KV_REST_API_URL`` + ``KV_REST_API_TOKEN``
  (or ``UPSTASH_REDIS_REST_URL`` + ``UPSTASH_REDIS_REST_TOKEN``). Uses ``httpx``,
  which is already a dependency, over HTTPS (no TCP pool to leak in a
  short-lived function).
* **Raw RESP** — ``REDIS_URL=redis://…`` / ``rediss://…`` for Redis Cloud,
  Railway, Render Key Value or a self-hosted server. Needs the optional ``redis``
  package; when it is not installed this transport is skipped and reads fall back
  to the Postgres cache. Nothing breaks.

Design rules (a cache must never take the portal down):

* Every call is best-effort and swallows its own errors.
* A circuit breaker (``REDIS_BREAKER_FAILURES`` consecutive failures → open for
  ``REDIS_BREAKER_COOLDOWN_SECONDS``) stops a dead Redis from adding a connect
  timeout to every single request.
* ``clear()`` deletes only keys under ``REDIS_KEY_PREFIX`` — a shared Redis is
  never wiped with FLUSHDB.
* Values are JSON; a value that cannot be serialised simply skips the cache.

Do we actually need Redis? (read this before adding it)
------------------------------------------------------
It depends on the *deployment*, not on taste, and the current production setup
does not need it:

* **Single-instance host (Render free — what is live today).** Every repeat read
  is already served by the in-process ``ttl_cache`` in microseconds, and the
  Postgres ``app_cache`` table covers the cold start after an idle sleep. A
  shared Redis would add a network hop on top of a cache that is not missing.
  ``/health`` → ``cache.memory.hit_rate`` stays high here, which is the proof.
* **Serverless / multi-instance (Vercel functions, or a service scaled to 2+
  replicas).** Consecutive requests land on *different* instances, so the
  in-process layer is cold almost every time and the heavy list queries re-run on
  every poll. ``hit_rate`` collapses, and that is exactly when a shared Redis
  starts paying for itself.

So: check ``/health`` first. Enable Redis (see ``scripts/enable-redis.sh``) when
``cache.memory.hit_rate`` is low **and** requests are spread over more than one
instance — not simply because the code supports it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# ─── configuration ────────────────────────────────────────────────────────


def _rest_config() -> tuple[str, str]:
    """Return ``(base_url, token)`` for the Upstash/Vercel KV REST transport."""
    url = (settings.KV_REST_API_URL or settings.UPSTASH_REDIS_REST_URL or "").strip().rstrip("/")
    token = (settings.KV_REST_API_TOKEN or settings.UPSTASH_REDIS_REST_TOKEN or "").strip()
    if url.startswith(("http://", "https://")) and token:
        return url, token
    return "", ""


def _resp_url() -> str:
    url = (settings.REDIS_URL or "").strip()
    return url if url.startswith(("redis://", "rediss://", "unix://")) else ""


# ─── circuit breaker ──────────────────────────────────────────────────────

_lock = threading.Lock()
_failures = 0
_open_until = 0.0


def _breaker_open() -> bool:
    with _lock:
        return time.monotonic() < _open_until


def _succeed() -> None:
    global _failures, _open_until
    with _lock:
        _failures = 0
        _open_until = 0.0


def _fail(exc: Exception) -> None:
    global _failures, _open_until
    opened = False
    with _lock:
        _failures += 1
        if _failures >= max(1, int(settings.REDIS_BREAKER_FAILURES)):
            if time.monotonic() >= _open_until:
                opened = True
            _open_until = time.monotonic() + max(1.0, float(settings.REDIS_BREAKER_COOLDOWN_SECONDS))
    if opened:
        logger.warning(
            "Redis cache unreachable (%s) — pausing cache calls for %.0fs; "
            "reads fall back to the Postgres cache",
            exc, max(1.0, float(settings.REDIS_BREAKER_COOLDOWN_SECONDS)),
        )
    else:
        logger.debug(f"Redis cache call failed: {exc}")



# ─── transport 1: Upstash / Vercel KV REST ────────────────────────────────

_http: Optional[httpx.AsyncClient] = None
_http_lock = threading.Lock()


def _http_client() -> httpx.AsyncClient:
    """Lazily create the shared async HTTP client (thread-safe)."""
    global _http
    with _http_lock:
        if _http is None:
            timeout = max(0.2, float(settings.REDIS_TIMEOUT_SECONDS))
            _http = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout),
                limits=httpx.Limits(max_connections=24, max_keepalive_connections=12),
            )
        return _http


async def _rest(commands: list[list[Any]]) -> list[Any]:
    """POST a command pipeline to the Upstash REST API, returning its results.

    Commands travel in the JSON body, so keys/values never need URL encoding.
    Raises on transport errors and on per-command ``{"error": …}`` replies.
    """
    url, token = _rest_config()
    response = await _http_client().post(
        url,
        json=commands,
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict):  # a single command is unwrapped by the API
        payload = [payload]
    results: list[Any] = []
    for item in payload:
        if isinstance(item, dict):
            if "error" in item:
                raise RuntimeError(f"redis error: {item['error']}")
            results.append(item.get("result"))
        else:
            results.append(item)
    return results


async def _rest_cmd(*command: Any) -> Any:
    results = await _rest([list(command)])
    return results[0] if results else None


# ─── transport 2: raw RESP (optional ``redis`` package) ───────────────────

_resp: Any = None
_resp_lock = threading.Lock()
_resp_unavailable = False


def _resp_client():
    """Blocking redis-py client, or ``None`` when the transport is unusable."""
    global _resp, _resp_unavailable
    if _resp_unavailable or not _resp_url():
        return None
    if _resp is not None:
        return _resp
    with _resp_lock:
        if _resp is not None:
            return _resp
        try:
            import redis  # type: ignore  # optional dependency

            timeout = max(0.2, float(settings.REDIS_TIMEOUT_SECONDS))
            _resp = redis.from_url(
                _resp_url(),
                socket_timeout=timeout,
                socket_connect_timeout=timeout,
                decode_responses=True,
                health_check_interval=30,
            )
        except Exception as e:  # package missing, bad URL, …
            logger.warning(f"Redis RESP transport unavailable ({e}); using the Postgres cache")
            _resp_unavailable = True
            return None
        return _resp


def _resp_get(key: str) -> Any:
    client = _resp_client()
    return client.get(key) if client is not None else None


def _resp_set(key: str, payload: str, ttl: int) -> None:
    client = _resp_client()
    if client is not None:
        client.set(key, payload, ex=ttl)


def _resp_clear(prefix: str) -> None:
    client = _resp_client()
    if client is None:
        return
    cursor = 0
    for _ in range(_MAX_SCAN_PAGES):
        cursor, keys = client.scan(cursor=cursor, match=f"{prefix}*", count=_SCAN_COUNT)
        if keys:
            client.delete(*keys)
        if cursor == 0:
            break


# ─── public API ───────────────────────────────────────────────────────────

_SCAN_COUNT = 200
# Upper bound on invalidation work: at most 25 × 200 keys. The cache only ever
# holds a handful of list snapshots, so this is far above what is ever used.
_MAX_SCAN_PAGES = 25
_value_unserialisable_warned = False


def transport() -> str:
    """``"rest"``, ``"resp"`` or ``""`` when no cache is configured."""
    if _rest_config()[0]:
        return "rest"
    if _resp_client() is not None:
        return "resp"
    return ""


def enabled() -> bool:
    """True when a Redis backend is configured and usable."""
    return bool(transport())


def _key(name: str) -> str:
    return f"{settings.REDIS_KEY_PREFIX or 'detomsite:'}{name}"


async def get(name: str) -> Any:
    """Return the cached object for ``name``, or ``None`` on miss/unavailability."""
    if _breaker_open() or not enabled():
        return None
    try:
        if transport() == "rest":
            raw = await _rest_cmd("GET", _key(name))
        else:
            raw = await asyncio.to_thread(_resp_get, _key(name))
    except Exception as e:
        _fail(e)
        return None
    _succeed()
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


async def set_pair(name: str, value: Any, ttl: float) -> None:
    """Cache ``value`` under ``name`` for ``ttl`` seconds (best-effort)."""
    global _value_unserialisable_warned
    if _breaker_open() or not enabled():
        return
    try:
        payload = json.dumps(value, default=str)
    except (TypeError, ValueError) as e:
        if not _value_unserialisable_warned:
            _value_unserialisable_warned = True
            logger.debug(f"Redis cache value not serialisable for {name!r}: {e}")
        return
    ttl_seconds = max(1, int(ttl))
    try:
        if transport() == "rest":
            await _rest_cmd("SET", _key(name), payload, "EX", ttl_seconds)
        else:
            await asyncio.to_thread(_resp_set, _key(name), payload, ttl_seconds)
    except Exception as e:
        _fail(e)
        return
    _succeed()


_tasks: set = set()


def spawn(coro) -> None:
    """Run ``coro`` in the background — current event loop, else a daemon thread.

    Never raises and never blocks the caller: cache maintenance must not sit in
    a request's critical path.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            threading.Thread(target=lambda: asyncio.run(coro), daemon=True).start()
        except Exception:
            pass
        return
    try:
        task = loop.create_task(coro)
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    except Exception:
        pass


def set_pair_bg(name: str, value: Any, ttl: float) -> None:
    """Queue a cache write without waiting for it (never raises).

    The response is already in flight; a cold request should not pay an extra
    cache round-trip just to warm a layer.
    """
    spawn(set_pair(name, value, ttl))



async def _clear_rest(prefix: str) -> None:
    cursor: Any = "0"
    for _ in range(_MAX_SCAN_PAGES):
        scan = await _rest_cmd("SCAN", cursor, "MATCH", f"{prefix}*", "COUNT", _SCAN_COUNT)
        if not isinstance(scan, (list, tuple)) or len(scan) != 2:
            return
        cursor, keys = scan[0], scan[1] or []
        for start in range(0, len(keys), 500):
            await _rest_cmd("DEL", *keys[start:start + 500])
        if str(cursor) == "0":
            return


async def clear() -> None:
    """Drop every key this app wrote (prefix-scoped, best-effort).

    Called after any successful write so a portal never serves a row that was
    just changed. The scan is bounded and only keys under
    ``REDIS_KEY_PREFIX`` are deleted — FLUSHDB is never used.
    """
    if not enabled():
        return
    if _breaker_open():
        # A write just landed: stale data is worse than one probe, so forget the
        # cooldown and try again now.
        _succeed()
    prefix = settings.REDIS_KEY_PREFIX or "detomsite:"
    try:
        if transport() == "rest":
            await _clear_rest(prefix)
        else:
            await asyncio.to_thread(_resp_clear, prefix)
    except Exception as e:
        _fail(e)
        return
    _succeed()


def status() -> dict:
    """Non-sensitive cache state for ``/health`` (no URLs, tokens or keys)."""
    with _lock:
        failures = _failures
        open_until = _open_until
    backend = transport()
    return {
        "enabled": bool(backend),
        "transport": backend or None,
        "breaker_open": time.monotonic() < open_until,
        "consecutive_failures": failures,
    }
