"""
In-memory rate limiter for authentication endpoints.

Prevents brute-force password guessing and mass account creation without
adding a Redis dependency. The limiter is per (purpose, key) and IPv4/IPv6
host — enough for a campus-scale deployment behind Vercel.

Trade-off: memory-only state resets on cold starts, and behind a shared NAT
multiple students share an IPv4 address. The limits are chosen generously so
legitimate campus users are never blocked while still throttling attacks.
"""

import re
import threading
import time
from collections import defaultdict
from typing import Pattern  # noqa: F401  (kept for type readability)

_lock = threading.Lock()
_hits: dict[str, list[float]] = defaultdict(list)

# A bucket key has to look like an address and stay short: it becomes a dict key,
# so an unbounded header value would be a cheap way to grow this map's memory.
_IP_LIKE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$|^[0-9a-fA-F:]{2,45}$")
_MAX_IP_LEN = 45


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
    """The client address to bucket a rate limit by.

    PENTEST FIX: this used to take the FIRST ``x-forwarded-for`` entry. That
    header is supplied by the caller, so rotating it minted a fresh bucket per
    request and bypassed *every* limit in the app - proven live: 10 login
    attempts with a different spoofed XFF each produced zero 429s, leaving the
    admin-login lockout, the agent-key throttle and the registration cap all
    decorative.

    Behind Render the edge *appends* the real client address, so the LAST entry
    is the one we can trust; anything to its left is attacker-supplied and must
    not decide the bucket. When the header is absent (running directly, no
    proxy) or unusable, fall back to the socket peer - which buckets everyone
    together rather than trusting a caller-controlled string.
    """
    peer = request.client.host if request.client else ""

    entries = (request.headers.get("x-forwarded-for") or "").split(",")
    candidate = entries[-1].strip() if entries else ""

    if candidate and len(candidate) <= _MAX_IP_LEN and _IP_LIKE.match(candidate):
        return candidate
    return peer or "unknown"
