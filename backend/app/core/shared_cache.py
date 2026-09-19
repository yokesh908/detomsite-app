"""Best-effort shared cache in the same Supabase database as application data."""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from app.core.config import settings

def enabled() -> bool:
    return _pg_enabled()


def _pg_enabled() -> bool:
    return bool(settings.SUPABASE_DATABASE_URL or
                (settings.SUPABASE_DB_HOST and settings.SUPABASE_DB_PASSWORD))


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
        if _pg_enabled() and _pg_ensure():
            return _pg_get(cache_key)
    except Exception:
        return None
    return None


def set_pair(cache_key: str, value: Any, ttl: float) -> None:
    """Store ``value`` under ``cache_key`` for ``ttl`` seconds (best-effort)."""
    try:
        if _pg_enabled() and _pg_ensure():
            return _pg_set(cache_key, value, ttl)
    except Exception:
        return


def clear() -> None:
    """Drop every cached entry (best-effort)."""
    try:
        if _pg_enabled() and _pg_ensure():
            return _pg_clear()
    except Exception:
        return