"""
Phone-bot endpoints: the WhatsApp auto-send agent polls ``/whatsapp/pending``
with the SMS forward key, gets only messages that are READY to deliver (COD and
paid-verified UPI), and confirms delivery via ``/whatsapp/{id}/mark-sent``.
"""
import pytest

from app.core.store import store


@pytest.fixture(autouse=True)
def _clean_wa_logs():
    yield
    with store._connect() as connection:
        connection.execute("DELETE FROM whatsapp_logs")


async def test_pending_filters_drafts_and_sent(client):
    # Draft → still awaiting payment: the bot must NOT send it yet.
    store.log_whatsapp(
        sub_order_id="o1", phone="9876543210",
        message="Hello! New DETOMSITE order #1\n• Payment: UPI ₹200 — awaiting payment",
        url="https://wa.me/919876543210", status="Pending",
    )
    # COD → ready now (nothing to verify).
    store.log_whatsapp(
        sub_order_id="o2", phone="9876543210",
        message="Hello! New DETOMSITE order #2\n• Payment: Cash on Delivery ₹150",
        url="https://wa.me/919876543210", status="Pending",
    )
    # Paid-verified UPI → ready now.
    store.log_whatsapp(
        sub_order_id="o3", phone="9876543210",
        message="Hello! New DETOMSITE order #3\n• Payment: UPI paid ₹80 ✓",
        url="https://wa.me/919876543210", status="Pending",
    )
    # Already delivered → never returned.
    store.log_whatsapp(
        sub_order_id="o4", phone="9876543210",
        message="Hello! New DETOMSITE order #4\n• Payment: UPI paid ₹90 ✓",
        url="https://wa.me/919876543210", status="Sent",
    )

    resp = await client.get("/api/v1/local/whatsapp/pending")
    assert resp.status_code == 200
    body = resp.json()
    assert sorted(x["sub_order_id"] for x in body) == ["o2", "o3"]
    assert all("awaiting payment" not in x["message"] for x in body)


async def test_mark_sent_roundtrip(client, monkeypatch):
    # Mutate the settings object the router holds (a sibling test reloads
    # app.core.config, replacing `settings`, so the endpoint instance is the
    # authoritative one here).
    from app.api.v1 import local as local_mod

    monkeypatch.setattr(local_mod.settings, "SMS_FORWARD_KEY", "topsecret")
    row = store.log_whatsapp(
        sub_order_id="o-marker", phone="9876543210",
        message="paid", url="https://wa.me/919876543210", status="Pending",
    )
    wa_id = row["id"]

    bad = await client.post(
        f"/api/v1/local/whatsapp/{wa_id}/mark-sent", headers={"X-Agent-Key": "nope"}
    )
    assert bad.status_code == 401

    good = await client.post(
        f"/api/v1/local/whatsapp/{wa_id}/mark-sent", headers={"X-Agent-Key": "topsecret"}
    )
    assert good.status_code == 200
    assert good.json()["status"] == "Sent"

    # A second mark is idempotent (still exists → 200). A missing row → 404.
    again = await client.post(
        f"/api/v1/local/whatsapp/{wa_id}/mark-sent", headers={"X-Agent-Key": "topsecret"}
    )
    assert again.status_code == 200
    missing = await client.post(
        "/api/v1/local/whatsapp/w-does-not-exist/mark-sent", headers={"X-Agent-Key": "topsecret"}
    )
    assert missing.status_code == 404


async def test_pending_requires_key(client, monkeypatch):
    from app.api.v1 import local as local_mod

    monkeypatch.setattr(local_mod.settings, "SMS_FORWARD_KEY", "sekret")
    resp = await client.get("/api/v1/local/whatsapp/pending")
    assert resp.status_code == 401
    resp = await client.get(
        "/api/v1/local/whatsapp/pending", headers={"X-Agent-Key": "sekret"}
    )
    assert resp.status_code == 200