"""
Test configuration and fixtures
"""
import os

# CRITICAL: always run tests against a throwaway LOCAL SQLite DB. The backend's
# .env sets USE_SUPABASE_DB=True, which would otherwise point pytest straight at
# PRODUCTION Supabase and leak test users/shops/orders into the live DB (this
# happened once; the rows had to be cleaned by hand). Env vars are set BEFORE
# `app.main` is imported so pydantic-settings picks them up and .env cannot
# override them. The shared Redis cache (Vercel KV) is disabled too, so tests
# never write into a real KV store.
os.environ["USE_SUPABASE_DB"] = "false"
os.environ["USE_TURSO_DB"] = "false"
os.environ["USE_LOCAL_DB"] = "true"
os.environ["LOCAL_DB_PATH"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pytest_local.db")
os.environ["KV_REST_API_URL"] = ""
os.environ["KV_REST_API_TOKEN"] = ""
os.environ["SUPABASE_DATABASE_URL"] = ""
os.environ["SMS_FORWARD_KEY"] = ""

import pytest
import httpx
from app.main import app
from app.core.store import init_store


@pytest.fixture(scope="session", autouse=True)
def _init_test_db():
    """Create the store schema before any test touches the database.

    A real server runs this in the app's lifespan; the httpx test client does
    not, so we do it here explicitly (idempotent).
    """
    init_store()


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
