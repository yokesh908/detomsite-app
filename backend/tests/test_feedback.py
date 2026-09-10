"""
Site feedback / bug-report tests — the "Help us test DETOMSITE" flow:
students submit feedback, see their own reports, and the admin lists them
and moves them along the status pipeline.
"""
import uuid
import pytest


class TestFeedback:
    """Student feedback → admin Feedback page flow"""

    @staticmethod
    def _unique(prefix: str) -> str:
        # Unique per run so re-runs against a persistent DB never collide.
        return f"{prefix}{uuid.uuid4().hex[:8]}"

    async def _register_student(self, client, username=None):
        username = username or self._unique("feedbackstu")
        await client.post("/api/v1/local/auth/register", json={
            "username": username,
            "password": "test_password_123",
            "name": "Feedback Student",
            "role": "student",
        })
        login = await client.post("/api/v1/local/auth/login", json={
            "username": username,
            "password": "test_password_123",
        })
        assert login.status_code == 200
        return login.json()["access_token"], username

    async def test_submit_and_list_own_feedback(self, client):
        token, username = await self._register_student(client)
        headers = {"Authorization": f"Bearer {token}"}

        # Submit a bug report — tagged 'User' because it came from a real
        # portal-style submission (no source given → default).
        res = await client.post("/api/v1/local/feedback", headers=headers, json={
            "category": "Bug",
            "subject": "Checkout button unresponsive",
            "message": "The Pay button on the checkout page did nothing when I tapped it.",
            "page": "Checkout",
        })
        assert res.status_code == 200
        fb = res.json()
        assert fb["subject"] == "Checkout button unresponsive"
        assert fb["status"] == "Open"
        assert fb["source"] == "User"  # default source
        assert fb["username"] == username  # identity came from the JWT

        # Student can list their own reports
        mine = await client.get("/api/v1/local/feedback/mine", headers=headers)
        assert mine.status_code == 200
        assert any(f["id"] == fb["id"] for f in mine.json())

    async def test_feedback_without_token_falls_back_to_session(self, client):
        # Quick RoleGate-style session (no JWT) must still be able to contribute
        res = await client.post("/api/v1/local/feedback", json={
            "category": "Suggestion",
            "subject": "Add a dark mode",
            "message": "It would be great to have a dark theme for night-time browsing.",
            "page": "",
            "source": "ATS",  # test-suite submissions are tagged ATS
            "name": "Guest Tester",
            "email": "guest@campus.local",
        })
        assert res.status_code == 200
        assert res.json()["name"] == "Guest Tester"
        assert res.json()["email"] == "guest@campus.local"
        assert res.json()["source"] == "ATS"

    async def test_admin_lists_and_updates_feedback(self, client):
        await self._register_student(client, username=self._unique("feedbackstu2"))
        # submit via the guest path so we don't need a student token here
        await client.post("/api/v1/local/feedback", json={
            "category": "Improvement",
            "subject": "Faster loading",
            "message": "Shops page could load faster on mobile data.",
            "page": "Shops",
            "source": "ATS",
            "name": "Second Tester",
            "email": "second@campus.local",
        })

        # Register our own admin (so the test never depends on whatever
        # admin account/password happens to exist in the active database)
        admin_username = self._unique("feedback_admin")
        await client.post("/api/v1/local/auth/register", json={
            "username": admin_username,
            "password": "admin_pass_123",
            "name": "Feedback Admin",
            "role": "admin",
        })
        login = await client.post("/api/v1/admin/login", json={
            "username": admin_username,
            "password": "admin_pass_123",
        })
        assert login.status_code == 200
        admin_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        listing = await client.get("/api/v1/admin/feedback", headers=admin_headers)
        assert listing.status_code == 200
        items = listing.json()
        assert any(i["subject"] == "Faster loading" for i in items)

        # Admin can filter by source — ATS-only returns only test submissions
        ats_only = await client.get("/api/v1/admin/feedback?source=ATS", headers=admin_headers)
        assert ats_only.status_code == 200
        assert ats_only.json()
        assert all(i["source"] == "ATS" for i in ats_only.json())

        # A filter with no matches is an empty list, not an error
        users_only = await client.get("/api/v1/admin/feedback?source=User", headers=admin_headers)
        assert users_only.status_code == 200
        assert all(i["source"] == "User" for i in users_only.json())

        target = next(i for i in items if i["subject"] == "Faster loading")
        updated = await client.patch(
            f"/api/v1/admin/feedback/{target['id']}",
            headers=admin_headers,
            json={"status": "In Review"},
        )
        assert updated.status_code == 200
        assert updated.json()["status"] == "In Review"

        # Non-admin cannot access the admin list
        token, _ = await self._register_student(client)
        denied = await client.get(
            "/api/v1/admin/feedback",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert denied.status_code == 403
