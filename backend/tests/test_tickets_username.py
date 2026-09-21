"""
Role-aware support tickets (student dashboard fix) + forgot-username endpoint.

The student dashboard used to show "Could not load your data" because
GET /local/tickets was admin-only (403 for students). These tests pin the
role-aware behaviour and the new POST /users/forgot-username flow.
"""
import uuid


def _unique(prefix: str) -> str:
    # Unique per run so re-runs against a persistent DB never collide.
    return f"{prefix}{uuid.uuid4().hex[:8]}"


async def _register_student(client, name: str, email: str):
    username = _unique("tkstu")
    await client.post("/api/v1/local/auth/register", json={
        "username": username,
        "password": "test_password_123",
        "name": name,
        "role": "student",
        "email": email,
    })
    login = await client.post("/api/v1/local/auth/login", json={
        "username": username,
        "password": "test_password_123",
    })
    assert login.status_code == 200
    return login.json()["access_token"]


class TestRoleAwareTickets:
    async def test_student_gets_own_tickets_not_403(self, client):
        name = _unique("Ticket Student")
        email = f"{_unique('tkstu')}@campus.edu"
        token = await _register_student(client, name, email)
        headers = {"Authorization": f"Bearer {token}"}

        created = await client.post("/api/v1/local/tickets", headers=headers, json={
            "name": name, "email": email, "phone_number": "9876543210",
            "category": "Order Issue", "title": "Missing item",
            "description": "My order arrived without the drinks.",
        })
        assert created.status_code == 200

        # The old admin-only guard returned 403 here and broke the dashboard.
        res = await client.get("/api/v1/local/tickets", headers=headers)
        assert res.status_code == 200
        tickets = res.json()
        assert any(t["title"] == "Missing item" for t in tickets)
        # Only their own tickets — never another student's.
        assert all(t.get("email") == email or t.get("name") == name for t in tickets)

    async def test_another_student_does_not_see_foreign_tickets(self, client):
        name_a, email_a = _unique("Stu A"), f"{_unique('a')}@campus.edu"
        name_b, email_b = _unique("Stu B"), f"{_unique('b')}@campus.edu"
        token_a = await _register_student(client, name_a, email_a)
        token_b = await _register_student(client, name_b, email_b)

        await client.post("/api/v1/local/tickets", headers={"Authorization": f"Bearer {token_a}"}, json={
            "name": name_a, "email": email_a, "phone_number": "9876543210",
            "category": "Order Issue", "title": "A's private ticket",
            "description": "Only student A should see this.",
        })
        res = await client.get("/api/v1/local/tickets", headers={"Authorization": f"Bearer {token_b}"})
        assert res.status_code == 200
        assert not any(t["title"] == "A's private ticket" for t in res.json())


class TestForgotUsername:
    async def test_forgot_username_never_leaks_accounts(self, client):
        # Unknown email → same generic response as a known one.
        ok = await client.post("/api/v1/users/forgot-username", json={"email": f"{_unique('nobody')}@campus.edu"})
        unknown = ok.json()["message"]
        assert ok.status_code == 200

        username = _unique("remstu")
        await client.post("/api/v1/local/auth/register", json={
            "username": username,
            "password": "test_password_123",
            "name": "Reminder Student",
            "role": "student",
            "email": f"{username}@campus.edu",
        })
        known = await client.post("/api/v1/users/forgot-username", json={"email": f"{username}@campus.edu"})
        assert known.status_code == 200
        assert known.json()["message"] == unknown  # identical → no enumeration

    async def test_forgot_username_requires_email(self, client):
        res = await client.post("/api/v1/users/forgot-username", json={})
        assert res.status_code == 422  # pydantic validation
