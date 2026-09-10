"""
Test configuration and fixtures
"""
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
