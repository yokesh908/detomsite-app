"""
Test configuration and fixtures
"""
import os
import uuid

# CRITICAL: tests NEVER touch Supabase. They run against a throwaway local
# SQLite DB (app/core/local_demo_db.py, test-only) so no test user/shop/order
# can leak into the live Supabase project (this happened once; the rows had to
# be cleaned by hand). The store facade is swapped to the test module via
# store._use_test_store() in the session fixture below. Both shared caches
# (Redis/Vercel KV and the Supabase app_cache table) are disabled too, so tests
# never read or write a real cache store.
os.environ["LOCAL_DB_PATH"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pytest_local.db")
os.environ["KV_REST_API_URL"] = ""
os.environ["KV_REST_API_TOKEN"] = ""
os.environ["UPSTASH_REDIS_REST_URL"] = ""
os.environ["UPSTASH_REDIS_REST_TOKEN"] = ""
os.environ["REDIS_URL"] = ""
# Never boot the in-process redis-server during tests (app/core/embedded_redis.py):
# a real test would fork a server, slow the suite down and leave a child process
# behind. The opt-in integration test flips this itself.
os.environ["DETOMSITE_EMBEDDED_REDIS"] = "0"
# Use explicit dummy settings before importing the app. Never load live DB
# credentials from backend/.env; the session fixture supplies the test store.
os.environ["DEBUG"] = "True"
os.environ["JWT_SECRET"] = "pytest-only-secret-not-for-deployment"
os.environ["SUPABASE_DATABASE_URL"] = "postgresql://dummy:dummy@127.0.0.1:1/test?connect_timeout=1"
os.environ["SUPABASE_DB_HOST"] = "127.0.0.1"
os.environ["SUPABASE_DB_PASSWORD"] = "dummy"
os.environ["DEFAULT_SUPER_ADMIN_EMAIL"] = "admin@example.com"
os.environ["DEFAULT_SUPER_ADMIN_PASSWORD"] = "pytest-admin-password"
os.environ["SMS_FORWARD_KEY"] = ""

import pytest
import httpx
from app.main import app
from app.core import store as store_module


@pytest.fixture(autouse=True)
def _init_test_db(tmp_path):
    """Point the store facade at throwaway SQLite and create its schema.

    A real server runs init_store() in the app lifespan against Supabase; the
    httpx test client does not, so we swap + init here explicitly (idempotent).
    """
    from app.core import local_demo_db as _test_db, shared_cache, supabase_db
    from app.core import rate_limit
    from app.core.config import settings
    from app import main as main_module

    settings.LOCAL_DB_PATH = str(tmp_path / "test.db")
    patch = pytest.MonkeyPatch()
    patch.setattr(shared_cache, "enabled", lambda: False)
    patch.setattr(shared_cache, "_pg_enabled", lambda: False)

    # Every test starts with empty throttling buckets. Both the middleware (60
    # auth calls/min per IP+path) and the per-endpoint limiter
    # (app/core/rate_limit) key on the client IP, and the whole suite hammers
    # those endpoints from ONE test-client IP — without this reset a later test
    # would randomly see 429 instead of the response it asserts on, so the suite
    # must only ever fail for real regressions.
    main_module._rate_limit_store.clear()
    rate_limit._hits.clear()

    def forbid_live_database():
        raise AssertionError("Tests must not connect to Supabase")

    patch.setattr(supabase_db, "_connect", forbid_live_database)
    store_module._use_test_store(_test_db)
    _test_db.init_local_demo_db()
    if hasattr(_test_db, "ensure_admin_user"):
        _test_db.ensure_admin_user()
    yield
    store_module._use_test_store(None)
    main_module._rate_limit_store.clear()
    rate_limit._hits.clear()
    patch.undo()


@pytest.fixture
async def client():
    """Create test client (httpx>=0.28 uses ASGITransport instead of app=).

    Each client carries its own synthetic ``x-forwarded-for`` (the header Vercel
    sets in production), so every test gets a private rate-limit bucket. The
    auth endpoints cap sign-ups at 40/hour per IP and the middleware at 60/min;
    with one shared test-client IP the suite exhausted that budget and later
    tests saw an unrelated 429 (a real flake: the run failed at
    ``test_tickets_username`` because an earlier test file had spent the quota).
    A per-test IP makes throttling deterministic and still exercises the limit
    *within* a test, where one client must share the bucket.
    """
    fake_ip = f"10.{uuid.uuid4().int % 250 + 1}.{(uuid.uuid4().int % 250) + 1}.{(uuid.uuid4().int % 250) + 1}"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"x-forwarded-for": fake_ip}
    ) as ac:
        yield ac


@pytest.fixture
async def test_user_data():
    """Test user data — matches the /local/auth/register schema"""
    return {
        "username": "testuser",
        "password": "test_password_123",
        "name": "Test User",
        "role": "student",
    }
