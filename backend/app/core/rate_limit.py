"""
In-memory rate limiter for authentication endpoints.

Prevents brute-force password guessing and mass account creation without
adding a Redis dependency. The limiter is per (purpose, key) and IPv4/IPv6
host — enough for a campus-scale deployment behind Vercel.

Trade-off: memory-only state resets on cold starts, and behind a shared NAT
multiple students share an IPv4 address. The limits are chosen generously so
legitimate campus users are never blocked while still throttling attacks.
"""

import threading
import time
from collections import defaultdict
from typing import Pattern  # noqa: F401  (kept for type readability)

_lock = threading.Lock()
_hits: dict[str, list[float]] = defaultdict(list)


def _key(purpose: str, ident: str) -> str:
    return f"{purpose}:{ident}"


def allow(purpose: str, ident: str, *, max_attempts: int, window_sec: int = 300) -> bool:
    """Record one attempt; return True when it is within the allowed quota."""
    now = time.time()
    key = _key(purpose, ident)
    with _lock:
        recent = [t for t in _hits[key] if now - t < window_sec]
        _hits[key] = recent
        if len(recent) >= max_attempts:
            return False
        recent.append(now)
        _hits[key] = recent
        return True


def reset(purpose: str, ident: str) -> None:
    """Forget past attempts (e.g. after a successful login)."""
    with _lock:
        _hits.pop(_key(purpose, ident), None)


def client_ip(request) -> str:
    """Best-effort client IP for rate limiting."""
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    host = forwarded or (request.client.host if request.client else "unknown")
    return host or "unknown"