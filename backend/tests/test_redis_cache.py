"""Redis read-cache tests — no Redis server required.

The app supports the Upstash/Vercel KV REST transport (``httpx``) and the raw
RESP transport (optional ``redis`` package). These tests start a tiny in-process
server that speaks the Upstash REST protocol and wire the cache to it over real
HTTP, so request handling, JSON value encoding, TTL propagation, prefix-scoped
invalidation, argument-digest cache keys and the layered ``read_cache`` order are
all exercised end to end. The RESP transport is covered by protocol-level tests
over a stub client.
"""
from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response

from app.core import read_cache, redis_cache, ttl_cache
from app.main import cache_invalidation_middleware


class FakeUpstash:
    """Minimal Upstash-compatible REST server: ``POST /`` with a command array."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.expiries: dict[str, int | None] = {}
        self.commands: list[list[str]] = []
        self.broken = False
        self._server: ThreadingHTTPServer | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────
    def start(self) -> "FakeUpstash":
        cache = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep pytest output clean
                return

            def do_POST(self):
                length = int(self.headers.get("content-length") or 0)
                body = self.rfile.read(length) if length else b"[]"
                try:
                    commands = json.loads(body or b"[]")
                except ValueError:
                    commands = []
                results = [cache.run(command) for command in commands]
                payload = json.dumps(results).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    @property
    def url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def keys(self) -> list[str]:
        return sorted(self.data)

    # ── command execution ─────────────────────────────────────────────────
    def run(self, command: list) -> dict:
        args = [str(a) for a in command]
        self.commands.append(args)
        if self.broken:
            return {"error": "simulated redis outage"}
        verb = args[0].upper()
        if verb == "GET":
            return {"result": self.data.get(args[1])}
        if verb == "SET":
            self.data[args[1]] = args[2]
            self.expiries[args[1]] = (
                int(args[4]) if len(args) > 4 and args[3].upper() == "EX" else None
            )
            return {"result": "OK"}
        if verb == "DEL":
            for key in args[1:]:
                self.data.pop(key, None)
            return {"result": 1}
        if verb == "PING":
            return {"result": "PONG"}
        if verb == "SCAN":
            pattern = args[3] if len(args) > 3 else "*"
            prefix = pattern.rstrip("*")
            # A single page is enough: the client stops once the cursor is "0".
            return {"result": ["0", [k for k in self.data if k.startswith(prefix)]]}
        return {"error": f"unknown command '{verb}'"}


@pytest.fixture
def fake_redis(monkeypatch):
    """A running fake Upstash REST server wired into the cache configuration."""
    server = FakeUpstash().start()
    monkeypatch.setattr(redis_cache, "_failures", 0)
    monkeypatch.setattr(redis_cache, "_open_until", 0.0)
    monkeypatch.setattr(redis_cache.settings, "KV_REST_API_URL", server.url)
    monkeypatch.setattr(redis_cache.settings, "KV_REST_API_TOKEN", "test-token")
    monkeypatch.setattr(redis_cache.settings, "UPSTASH_REDIS_REST_URL", "")
    monkeypatch.setattr(redis_cache.settings, "UPSTASH_REDIS_REST_TOKEN", "")
    monkeypatch.setattr(redis_cache.settings, "REDIS_URL", "")
    monkeypatch.setattr(redis_cache.settings, "REDIS_KEY_PREFIX", "detomsite:")
    ttl_cache.clear()
    yield server
    server.stop()
    ttl_cache.clear()


class StubRespClient:
    """Records RESP commands so the raw-protocol path can be asserted on."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.store: dict[str, str] = {}

    def get(self, key):
        self.calls.append(("get", key))
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.calls.append(("set", key, value, ex))
        self.store[key] = value

    def scan(self, cursor=0, match="*", count=10):
        self.calls.append(("scan", cursor, match, count))
        prefix = match.rstrip("*")
        return (0, [k for k in self.store if k.startswith(prefix)])

    def delete(self, *keys):
        self.calls.append(("delete", keys))
        return len(keys)


async def _drain_cache_writes() -> None:
    """Wait for fire-and-forget cache writes to land (test determinism)."""
    pending = [task for task in list(redis_cache._tasks) if not task.done()]
    if pending:
        await asyncio.gather(*pending)


def _request(method: str = "POST", path: str = "/api/v1/local/orders") -> StarletteRequest:
    """A minimal ASGI request for driving the invalidation middleware directly."""
    return StarletteRequest(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


# ─── configuration: the portal must run fine with no Redis at all ─────────


async def test_disabled_without_configuration():
    """No Redis configured → every call is a safe no-op (never raises)."""
    assert redis_cache.enabled() is False
    assert redis_cache.transport() == ""
    assert redis_cache.status()["enabled"] is False
    assert await redis_cache.get("batch") is None
    await redis_cache.set_pair("batch", {"x": 1}, 5)
    await redis_cache.clear()


# ─── REST transport (Upstash / Vercel KV) ─────────────────────────────────


async def test_rest_transport_roundtrip_with_ttl(fake_redis):
    assert redis_cache.transport() == "rest"
    payload = {"products": [{"id": 7, "name": "Chai ü"}], "stock_left": None}
    await redis_cache.set_pair("products:shop-1", payload, 30)
    assert await redis_cache.get("products:shop-1") == payload
    assert fake_redis.expiries["detomsite:products:shop-1"] == 30
    assert await redis_cache.get("products:shop-2") is None


async def test_unparseable_cached_value_is_treated_as_a_miss(fake_redis):
    """A corrupted/foreign value must never break the endpoint that reads it."""
    fake_redis.data["detomsite:orders:abc"] = "<not json>"
    assert await redis_cache.get("orders:abc") is None


async def test_clear_only_deletes_this_apps_keys(fake_redis):
    """Invalidation is prefix-scoped — a shared Redis is never wiped."""
    fake_redis.data["other-app:session:1"] = "keep-me"
    await redis_cache.set_pair("orders:abc", [1], 30)
    await redis_cache.set_pair("products:shop-1", [2], 30)
    assert len(fake_redis.keys()) == 3
    await redis_cache.clear()
    assert fake_redis.keys() == ["other-app:session:1"]


async def test_breaker_stops_calling_a_dead_redis(fake_redis, monkeypatch):
    """An outage must not add a timeout to every single request."""
    monkeypatch.setattr(redis_cache.settings, "REDIS_BREAKER_FAILURES", 2)
    monkeypatch.setattr(redis_cache.settings, "REDIS_BREAKER_COOLDOWN_SECONDS", 30.0)
    fake_redis.broken = True

    assert await redis_cache.get("orders:abc") is None  # failure 1
    assert await redis_cache.get("orders:abc") is None  # failure 2 → breaker opens
    assert redis_cache.status()["breaker_open"] is True

    attempts = len(fake_redis.commands)
    assert await redis_cache.get("orders:abc") is None     # skipped, no I/O
    await redis_cache.set_pair("orders:abc", {"n": 1}, 5)  # skipped too
    assert len(fake_redis.commands) == attempts

    # Once the cooldown expires the cache is probed again and recovers.
    monkeypatch.setattr(redis_cache, "_open_until", 0.0)
    fake_redis.broken = False
    await redis_cache.set_pair("orders:abc", {"n": 1}, 5)
    assert await redis_cache.get("orders:abc") == {"n": 1}
    assert redis_cache.status()["breaker_open"] is False


# ─── RESP transport (REDIS_URL + optional redis package) ──────────────────


async def test_resp_transport_uses_scan_not_flushdb(monkeypatch):
    stub = StubRespClient()
    monkeypatch.setattr(redis_cache, "_resp", stub)
    monkeypatch.setattr(redis_cache, "_resp_unavailable", False)
    monkeypatch.setattr(redis_cache, "_failures", 0)
    monkeypatch.setattr(redis_cache, "_open_until", 0.0)
    monkeypatch.setattr(redis_cache.settings, "KV_REST_API_URL", "")
    monkeypatch.setattr(redis_cache.settings, "KV_REST_API_TOKEN", "")
    monkeypatch.setattr(redis_cache.settings, "REDIS_URL", "redis://127.0.0.1:6379/0")

    assert redis_cache.transport() == "resp"
    await redis_cache.set_pair("orders:abc", {"n": 1}, 30)
    assert ("set", "detomsite:orders:abc", '{"n": 1}', 30) in stub.calls
    assert await redis_cache.get("orders:abc") == {"n": 1}

    await redis_cache.clear()
    assert ("scan", 0, "detomsite:*", 200) in stub.calls
    assert ("delete", ("detomsite:orders:abc",)) in stub.calls
    assert not any(call[0] == "flushall" for call in stub.calls)


# ─── layering: memory → Redis → Postgres → loader ─────────────────────────


async def test_loader_runs_once_then_redis_serves_every_instance(fake_redis):
    """The point of Redis: a *fresh* instance (empty memory) still skips the DB."""
    calls = []

    def loader(*_args, **_kwargs):
        calls.append(1)
        return [{"id": 1}]

    args = ("student-1",)
    assert await read_cache.cached_read(30, "orders", loader, *args) == [{"id": 1}]
    await _drain_cache_writes()
    assert len(calls) == 1

    # Same instance → memory hit, loader untouched.
    assert await read_cache.cached_read(30, "orders", loader, *args) == [{"id": 1}]

    # Simulate another serverless instance: memory empty, Redis warm.
    ttl_cache.clear()
    assert await read_cache.cached_read(30, "orders", loader, *args) == [{"id": 1}]
    assert len(calls) == 1
    # …and that instance now has it in memory as well.
    assert await read_cache.cached_read(30, "orders", loader, *args) == [{"id": 1}]
    assert len(calls) == 1


async def test_different_arguments_do_not_share_an_entry(fake_redis):
    """Per-user / per-filter results must never cross wires."""
    def loader(owner, status=None):
        return [{"owner": owner, "status": status}]

    mine = await read_cache.cached_read(30, "orders", loader, "student-1")
    theirs = await read_cache.cached_read(30, "orders", loader, "student-2")
    filtered = await read_cache.cached_read(30, "orders", loader, "student-1", status="pending")
    assert mine == [{"owner": "student-1", "status": None}]
    assert theirs == [{"owner": "student-2", "status": None}]
    assert filtered == [{"owner": "student-1", "status": "pending"}]


def test_cache_keys_carry_no_personal_data():
    """Cache keys are digests: a shared store holds no names/phones/e-mails."""
    user = {"id": 4, "name": "Aarav Sharma", "phone": "9876543210", "email": "a@x.com"}
    key = read_cache.cache_key("orders", (user,), {"status": "pending"})
    assert key.startswith("orders:")
    for secret in ("Aarav", "Sharma", "9876543210", "a@x.com", "phone"):
        assert secret not in key
    # Stable across calls (so every instance computes the same key)…
    assert key == read_cache.cache_key("orders", (user,), {"status": "pending"})
    # …but distinct when the arguments differ.
    assert key != read_cache.cache_key("orders", ({**user, "id": 5},), {"status": "pending"})


async def test_loader_errors_are_not_cached(fake_redis):
    """A failed query must never be stored as if it were data."""
    attempts = []

    def loader(*_args, **_kwargs):
        attempts.append(1)
        raise RuntimeError("db down")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await read_cache.cached_read(30, "orders", loader, "student-1")
    await _drain_cache_writes()
    assert len(attempts) == 2
    assert fake_redis.keys() == []


async def test_async_loader_is_awaited(fake_redis):
    """loaders that merge several sources may be async."""
    async def loader(value):
        await asyncio.sleep(0)
        return {"value": value}

    assert await read_cache.cached_read(30, "merged", loader, 9) == {"value": 9}


async def test_clear_invalidates_memory_and_redis(fake_redis):
    """A write on any instance must make the next read recompute."""
    calls = []

    def loader():
        calls.append(1)
        return {"n": len(calls)}

    assert await read_cache.cached_read(30, "products", loader) == {"n": 1}
    await _drain_cache_writes()
    assert fake_redis.keys()  # warm in the shared layer too

    await read_cache.clear()
    assert ttl_cache.get("products") is None
    assert fake_redis.keys() == []

    assert await read_cache.cached_read(30, "products", loader) == {"n": 2}


async def test_clear_bg_drops_memory_immediately(fake_redis):
    """Write paths drop this instance's copy synchronously, shared layers after."""
    await read_cache.cached_read(30, "products", lambda: {"n": 1})
    await _drain_cache_writes()
    read_cache.clear_bg()
    assert ttl_cache.get("products") is None
    await _drain_cache_writes()
    assert fake_redis.keys() == []


# ─── write invalidation middleware ────────────────────────────────────────


async def test_middleware_invalidates_after_successful_write(fake_redis):
    await read_cache.cached_read(30, "admin-orders", lambda: [{"id": 1}])
    await _drain_cache_writes()
    assert fake_redis.keys()

    async def call_next(_request):
        return Response(status_code=201)

    response = await cache_invalidation_middleware(_request("POST"), call_next)
    assert response.status_code == 201
    assert fake_redis.keys() == []
    assert ttl_cache.get("admin-orders") is None


async def test_middleware_keeps_cache_on_reads_and_failed_writes(fake_redis):
    """Only a *successful* mutation may drop the cache."""
    async def ok_read(_request):
        return Response(status_code=200)

    async def failed_write(_request):
        return Response(status_code=400)

    await read_cache.cached_read(30, "admin-orders", lambda: [{"id": 1}])
    await _drain_cache_writes()

    await cache_invalidation_middleware(_request("GET"), ok_read)
    assert fake_redis.keys()
    await cache_invalidation_middleware(_request("POST", "/api/v1/local/orders"), failed_write)
    assert fake_redis.keys()


async def test_invalidation_survives_a_redis_outage(fake_redis, monkeypatch):
    """A dead Redis must not turn a successful write into a 500."""
    monkeypatch.setattr(redis_cache.settings, "REDIS_BREAKER_FAILURES", 1)
    fake_redis.broken = True

    async def call_next(_request):
        return Response(status_code=201)

    response = await cache_invalidation_middleware(_request("POST"), call_next)
    assert response.status_code == 201


# ─── health reporting ─────────────────────────────────────────────────────


async def test_health_reports_cache_state_without_secrets(fake_redis):
    from app.main import health_check

    report = await health_check()
    cache = report["cache"]
    assert cache["redis"]["enabled"] is True
    assert cache["redis"]["transport"] == "rest"
    assert cache["redis"]["breaker_open"] is False
    # The report is public — it must not echo the configured credentials.
    serialised = json.dumps(report)
    assert "test-token" not in serialised
    assert fake_redis.url not in serialised
    assert "KV_REST_API" not in serialised


# ─── end-to-end: a real portal endpoint, served from Redis ────────────────


async def _student_token(client) -> str:
    import uuid

    username = f"rediscache_{uuid.uuid4().hex[:8]}"
    await client.post("/api/v1/local/auth/register", json={
        "username": username,
        "password": "password123",
        "name": "Redis Cache Student",
        "role": "student",
        "email": f"{username}@example.com",
        "phone": "+919000000001",
    })
    res = await client.post(
        "/api/v1/local/auth/login", json={"username": username, "password": "password123"}
    )
    assert res.status_code == 200
    return res.json()["access_token"]


async def test_orders_endpoint_skips_the_database_after_the_first_poll(
    client, fake_redis, monkeypatch
):
    """The real point of the Redis layer, measured on a real portal route.

    ``GET /api/v1/local/orders`` is what every portal polls. It must query the
    store once, then be answered from cache on this instance AND on a fresh
    instance (the serverless case), and a real write must make the next poll
    recompute.
    """
    from app.core.store import store as db

    token = await _student_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    queries = []
    real_list_orders = db.list_orders

    def counting_list_orders(*args, **kwargs):
        queries.append(1)
        return real_list_orders(*args, **kwargs)

    monkeypatch.setattr(db, "list_orders", counting_list_orders)

    first = await client.get("/api/v1/local/orders", headers=headers)
    assert first.status_code == 200
    await _drain_cache_writes()
    assert len(queries) == 1
    assert fake_redis.keys()  # the snapshot is now shared with every instance

    # Poll again on the same instance — served from memory, no query.
    assert (await client.get("/api/v1/local/orders", headers=headers)).status_code == 200
    assert len(queries) == 1

    # A different instance (cold memory) is served by Redis — still no query.
    ttl_cache.clear()
    same = await client.get("/api/v1/local/orders", headers=headers)
    assert same.status_code == 200
    assert same.json() == first.json()
    assert len(queries) == 1

    # A real write through the API invalidates every layer, so the next poll
    # recomputes instead of showing a stale list.
    posted = await client.post(
        "/api/v1/local/feedback",
        json={
            "category": "Bug",
            "subject": "Cache invalidation",
            "message": "a write must bust every read-cache layer",
        },
        headers=headers,
    )
    assert posted.status_code in (200, 201)
    assert fake_redis.keys() == []
    ttl_cache.clear()
    assert (await client.get("/api/v1/local/orders", headers=headers)).status_code == 200
    assert len(queries) == 2
