"""
Authentication tests — use the /local/auth endpoints, which are registered in
every deployment mode (SQLite / Turso / Supabase). The Mongo-only /auth router
is not mounted in CI, so testing it here would 404.
"""
import pytest


class TestAuth:
    """Authentication endpoint tests"""

    async def test_register(self, client, test_user_data):
        """Test user registration"""
        response = await client.post("/api/v1/local/auth/register", json=test_user_data)
        assert response.status_code in [201, 409]  # 201 created, 409 username exists

    async def test_login(self, client, test_user_data):
        """Test user login (register first so the user exists in CI)"""
        await client.post("/api/v1/local/auth/register", json=test_user_data)
        login_data = {
            "username": test_user_data["username"],
            "password": test_user_data["password"],
        }
        response = await client.post("/api/v1/local/auth/login", json=login_data)
        assert response.status_code == 200
        body = response.json()
        assert body.get("access_token")
        assert body.get("user", {}).get("role") == "student"

    async def test_health_check(self, client):
        """Test health check endpoint"""
        response = await client.get("/health")
        assert response.status_code == 200
        assert "status" in response.json()
