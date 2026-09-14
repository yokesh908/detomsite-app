"""Cross-instance read cache, so every Vercel instance serves warm data fast.

The in-process TTL cache only helps requests that land on the *same* serverless
instance, which is why prod reads still show ~900ms while the app is fanned out
across many instances. This layer adds a GLOBALLY-shared cache; a warm hit skips
the heavy list/aggregate queries entirely.

Providers, in priority order (whichever environment is configured wins):
1. ``KV_REST_API_URL`` + ``KV_REST_API_TOKEN`` (Vercel KV / Upstash Redis) —
   single-digit-ms, used when a store is ever connected to the project.
2. Supabase Postgres ``app_cache`` table (the live shared DB this app already
   uses) — cross-instance shared, indexed key lookup, ~20-40ms per hit.

Design rules:
- Everything is BEST-EFFORT and never raises. Any network/DB error on a read
  behaves exactly like a cache miss (recompute); a write is a no-op.
- Keys are namespaced (``detomsite:cache:<hash>`` for Redis / opaque PK for
  Postgres) so clearing only touches our rows.
- Values are JSON-serialised, dates falling back to ISO strings exactly like
  FastAPI's own encoder.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Any

from app.core.config import settings

_PREFIX = "detomsite:cache:"


# ─── shared helpers ───────────────────────────────────────────────────────

def enabled() -> bool:
    return _kv_endpoint() is not None or _pg_enabled()


def _kv_endpoint() -> tuple[str, str] | None:
    url = (os.getenv("KV_REST_API_URL") or "").rstrip("/")
    token = (os.getenv("KV_REST_API_TOKEN") or "")
    if url and token:
        return url, token
    return None


def _pg_enabled() -> bool:
    # Only when the app is NOT using Postgres as its primary store? No — prod
    # uses Supabase for data AND we cache in it. Tests disable it explicitly by
    # clearing SUPABASE_DATABASE_URL in conftest.
    return bool((settings.SUPABASE_DATABASE_URL or "").strip())


def _kv_key(cache_key: str) -> str:
    digest = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()[:24]
    return f"{_PREFIX}{digest}"


# ─── provider: Vercel KV / Upstash Redis ────────────────────────────────

def _kv_rpc(path: str, payload: list[Any]) -> Any:
    """POST a JSON-RPC-style array body to Upstash REST ``/{path}``.

    Returns the parsed result or ``None`` on any failure. Never raises.
    """
    ep = _kv_endpoint()
    if ep is None:
        return None
    import urllib.request  # stdlib, no extra dependency needed

    url, token = ep
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/{path}",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=0.6) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    except Exception:
        return None


def _kv_get(cache_key: str) -> Any | None:
    out = _kv_rpc("get", [_kv_key(cache_key)])
    if isinstance(out, dict):
        out = out.get("result")
    if isinstance(out, (list, tuple)):
        out = out[0] if out else None
    if isinstance(out, str):
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return None
    return None


def _kv_set(cache_key: str, value: Any, ttl: float) -> None:
    _kv_rpc("set", [_kv_key(cache_key), json.dumps(value, default=str), "EX", max(1, int(ttl))])


def _kv_clear() -> None:
    keys = _kv_rpc("keys", [_PREFIX + "*"])
    if isinstance(keys, dict):
        keys = keys.get("result") or keys.get("items") or []
    if not isinstance(keys, list) or not keys:
        return
    keys = [k for k in keys if isinstance(k, str)]
    if keys:
        _kv_rpc("del", keys)


# ─── provider: Supabase Postgres ``app_cache`` table ─────────────────────

_pg_lock = threading.Lock()
_pg_ready = False
_last_pg_sweep = 0.0
_pg_sweep_lock = threading.Lock()


def _pg_maybe_sweep() -> None:
    """Throttled deletion of expired rows so the table never grows unboundedly.

    Runs at most every 5 minutes per instance (a global clear after each write
    already bounds the table, this just tidies up between those clears)."""
    global _last_pg_sweep
    if time.time() - _last_pg_sweep < 300.0:
        return
    with _pg_sweep_lock:
        if time.time() - _last_pg_sweep < 300.0:
            return
        try:
            from app.core.supabase_db import _connect, _release

            conn = _connect()
            try:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM app_cache WHERE expires_at <= now()")
                    conn.commit()
            finally:
                _release(conn)
        except Exception:
            pass
        finally:
            _last_pg_sweep = time.time()


def _pg_ensure() -> bool:
    """Lazily create the app_cache table (idempotent, thread-safe)."""
    global _pg_ready
    if _pg_ready:
        return True
    with _pg_lock:
        if _pg_ready:
            return True
        try:
            from app.core.supabase_db import _connect, _release

            conn = _connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS app_cache (
                            cache_key   text PRIMARY KEY,
                            cache_value text NOT NULL,
                            expires_at  timestamptz NOT NULL
                        )
                        """
                    )
                    cur.execute("CREATE INDEX IF NOT EXISTS app_cache_expires_idx ON app_cache (expires_at)")
                    conn.commit()
            finally:
                _release(conn)
            _pg_ready = True
            return True
        except Exception:
            _pg_ready = False
            return False


def _pg_get(cache_key: str) -> Any | None:
    from app.core.supabase_db import _connect, _release

    _pg_maybe_sweep()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT cache_value FROM app_cache WHERE cache_key = %s AND expires_at > now()",
                (cache_key,),
            )
            row = cur.fetchone()
    finally:
        _release(conn)
    if not row:
        return None
    try:
        return json.loads(row["cache_value"])
    except (json.JSONDecodeError, TypeError, KeyError):
        return None


def _pg_set(cache_key: str, value: Any, ttl: float) -> None:
    from app.core.supabase_db import _connect, _release

    _pg_maybe_sweep()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_cache (cache_key, cache_value, expires_at)
                VALUES (%s, %s, now() + make_interval(secs => %s))
                ON CONFLICT (cache_key) DO UPDATE
                  SET cache_value = EXCLUDED.cache_value,
                      expires_at  = EXCLUDED.expires_at
                """,
                (cache_key, json.dumps(value, default=str), max(1, int(ttl))),
            )
            conn.commit()
    finally:
        _release(conn)


def _pg_clear() -> None:
    from app.core.supabase_db import _connect, _release

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM app_cache")
            conn.commit()
    finally:
        _release(conn)


# ─── public API (used by _cached_read / batch / products-stock / admin) ──

def get(cache_key: str) -> Any | None:
    """Return the cached Python object, or ``None`` on a miss / unavailable
    store. Never raises."""
    try:
        if _kv_endpoint() is not None:
            return _kv_get(cache_key)
        if _pg_enabled() and _pg_ensure():
            return _pg_get(cache_key)
    except Exception:
        return None
    return None


def set_pair(cache_key: str, value: Any, ttl: float) -> None:
    """Store ``value`` under ``cache_key`` for ``ttl`` seconds (best-effort)."""
    try:
        if _kv_endpoint() is not None:
            return _kv_set(cache_key, value, ttl)
        if _pg_enabled() and _pg_ensure():
            return _pg_set(cache_key, value, ttl)
    except Exception:
        return


def clear() -> None:
    """Drop every cached entry (best-effort)."""
    try:
        if _kv_endpoint() is not None:
            return _kv_clear()
        if _pg_enabled() and _pg_ensure():
            return _pg_clear()
    except Exception:
        return