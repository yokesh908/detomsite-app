"""
Test configuration and fixtures
"""
import os

# CRITICAL: tests NEVER touch Supabase. They run against a throwaway local
# SQLite DB (app/core/local_demo_db.py, test-only) so no test user/shop/order
# can leak into the live Supabase project (this happened once; the rows had to
# be cleaned by hand). The store facade is swapped to the test module via
# store._use_test_store() in the session fixture below. The shared Redis cache
# (Vercel KV) is disabled too, so tests never write into a real KV store.
os.environ["LOCAL_DB_PATH"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pytest_local.db")
os.environ["KV_REST_API_URL"] = ""
os.environ["KV_REST_API_TOKEN"] = ""
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
    from app.core.config import settings

    settings.LOCAL_DB_PATH = str(tmp_path / "test.db")
    patch = pytest.MonkeyPatch()
    patch.setattr(shared_cache, "enabled", lambda: False)
    patch.setattr(shared_cache, "_pg_enabled", lambda: False)

    def forbid_live_database():
        raise AssertionError("Tests must not connect to Supabase")

    patch.setattr(supabase_db, "_connect", forbid_live_database)
    store_module._use_test_store(_test_db)
    _test_db.init_local_demo_db()
    if hasattr(_test_db, "ensure_admin_user"):
        _test_db.ensure_admin_user()
    yield
    store_module._use_test_store(None)
    patch.undo()


@pytest.fixture
async def client():
    """Create test client (httpx>=0.28 uses ASGITransport instead of app=)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
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
