"""
Order acceptance & cancellation tests.

The day is split into two delivery windows — Morning (until 12:30 PM) and
Afternoon (until 6:00 PM). Orders placed inside a window are auto-accepted,
and the student can cancel them until that window closes. Orders placed after
6:00 PM stay pending and cannot be cancelled by the student.
"""
from datetime import datetime, time
from uuid import uuid4

import pytest

from app.core.store import store as db

# The test DB persists across runs, so every username is made unique per run
# to avoid stale users from earlier runs leaking into the assertions.
_RUN = uuid4().hex[:6]


def _u(base: str) -> str:
    return f"{base}_{_RUN}"


async def _register_and_login(client, username, password, name, role, phone="+919876543210"):
    """Register a user and return their access token."""
    await client.post("/api/v1/local/auth/register", json={
        "username": username,
        "password": password,
        "name": name,
        "role": role,
        "email": f"{username}@example.com",
        "phone": phone,
    })
    res = await client.post("/api/v1/local/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200
    return res.json()["access_token"]


def _freeze_time(monkeypatch, hour, minute=0):
    """Fix the current IST time for BOTH the slot helpers (auto-accept) and the
    cancel endpoint's now reference, so tests are deterministic at any hour."""
    import app.api.v1.local as local_mod
    import app.core.order_slots as slots_mod

    fixed = datetime(2026, 8, 16, hour, minute, tzinfo=slots_mod.KOLKATA_TZ)
    monkeypatch.setattr(slots_mod, "now_kolkata", lambda: fixed)
    monkeypatch.setattr(local_mod, "now_kolkata", lambda: fixed)
    return fixed


def _approved_shop_with_product(shopkeeper_email: str, shopkeeper_name: str):
    """Create an approved, open shop with one product, straight through the store."""
    shop = db.create_shop({
        "name": f"{shopkeeper_name}'s Shop",
        "category": "Food",
        "description": "Demo shop",
        "shopkeeper_email": shopkeeper_email,
        "shopkeeper_name": shopkeeper_name,
        "phone": "9876543210",
    })
    db.update_shop(shop["id"], {"approval_status": "Approved", "present": True, "status": "Open"})
    product = db.create_product({
        "shop_id": shop["id"],
        "name": "Pizza",
        "description": "",
        "price": 100,
        "category": "Food",
        "inventory": 10,
        "prep_time": 10,
        "available": True,
    })
    return shop, product


async def _place_order(client, shop_id, product_id, student_name, method="COD", token=None):
    """POST /local/orders — requires the student's auth token, so callers must
    pass the token from ``_register_and_login``."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    res = await client.post("/api/v1/local/orders", json={
        "shop_id": shop_id,
        "items": [{"product_id": product_id, "quantity": 2}],
        "student_name": student_name,
        "student_phone": "+919876543210",
        "delivery_location": "VIT-AP Hostel A Block 101",
        "delivery_slot": "Evening",
        "payment_method": method,
    }, headers=headers)
    assert res.status_code == 200
    return res.json()


@pytest.mark.anyio
async def test_order_auto_accepted_within_window(client, monkeypatch):
    _freeze_time(monkeypatch, 10, 0)  # 10:00 AM — inside the morning window
    await _register_and_login(client, _u("autos1"), "password123", "Auto Student", "student")
    shop, product = _approved_shop_with_product(_u("autos1vendor") + "@example.com", "Auto Vendor")

    _tok = await _register_and_login(client, _u("autos1_tok"), "password123", "Auto", "student")
    order = await _place_order(client, shop["id"], product["id"], "Auto Student", method="COD", token=_tok)
    assert order["status"] == "Accepted"


@pytest.mark.anyio
async def test_order_not_auto_accepted_outside_window(client, monkeypatch):
    _freeze_time(monkeypatch, 20, 0)  # 8:00 PM — outside both delivery windows
    await _register_and_login(client, _u("autos2"), "password123", "Auto Student 2", "student")
    shop, product = _approved_shop_with_product(_u("autos2vendor") + "@example.com", "Auto Vendor 2")

    _tok2 = await _register_and_login(client, _u("autos2_tok"), "password123", "Auto 2", "student")
    order = await _place_order(client, shop["id"], product["id"], "Auto Student 2", method="COD", token=_tok2)
    assert order["status"] == "Pending Acceptance"


@pytest.mark.anyio
async def test_student_cancels_order_within_window(client, monkeypatch):
    import app.api.v1.local as local_mod

    _freeze_time(monkeypatch, 10, 0)  # placed at 10:00 AM → auto-accepted
    student_token = await _register_and_login(client, _u("cancels1"), "password123", "Cancel Student", "student")
    shop, product = _approved_shop_with_product(_u("cancels1vendor") + "@example.com", "Cancel Vendor")

    order = await _place_order(client, shop["id"], product["id"], "Cancel Student", method="COD", token=student_token)
    assert order["status"] == "Accepted"

    # 11:00 AM — still inside the window (cut-off 12:30) → cancellation works.
    _freeze_time(monkeypatch, 11, 0)
    monkeypatch.setattr(local_mod, "slot_cutoff_for", lambda _dt: time(12, 30))
    res = await client.post(
        f"/api/v1/local/orders/{order['id']}/cancel",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert res.status_code == 200
    assert res.json()["order"]["status"] == "Cancelled"

    # A second cancel is rejected — the order is no longer cancellable.
    res2 = await client.post(
        f"/api/v1/local/orders/{order['id']}/cancel",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert res2.status_code == 400


@pytest.mark.anyio
async def test_cannot_cancel_after_window_closes(client, monkeypatch):
    import app.api.v1.local as local_mod

    _freeze_time(monkeypatch, 10, 0)
    student_token = await _register_and_login(client, _u("cancels2"), "password123", "Cancel Student 2", "student")
    shop, product = _approved_shop_with_product(_u("cancels2vendor") + "@example.com", "Cancel Vendor 2")
    order = await _place_order(client, shop["id"], product["id"], "Cancel Student 2", method="COD", token=student_token)

    # 1:00 PM — the morning window (cut-off 12:30) has closed.
    _freeze_time(monkeypatch, 13, 0)
    monkeypatch.setattr(local_mod, "slot_cutoff_for", lambda _dt: time(12, 30))
    res = await client.post(
        f"/api/v1/local/orders/{order['id']}/cancel",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert res.status_code == 400
    assert "closed" in res.json()["detail"].lower()


@pytest.mark.anyio
async def test_cannot_cancel_order_placed_outside_windows(client, monkeypatch):
    import app.api.v1.local as local_mod

    _freeze_time(monkeypatch, 10, 0)
    student_token = await _register_and_login(client, _u("cancels3"), "password123", "Cancel Student 3", "student")
    shop, product = _approved_shop_with_product(_u("cancels3vendor") + "@example.com", "Cancel Vendor 3")
    order = await _place_order(client, shop["id"], product["id"], "Cancel Student 3", method="COD", token=student_token)

    # The order's placement time maps to no delivery window at all.
    monkeypatch.setattr(local_mod, "slot_cutoff_for", lambda _dt: None)
    res = await client.post(
        f"/api/v1/local/orders/{order['id']}/cancel",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert res.status_code == 400
    assert "outside the delivery windows" in res.json()["detail"].lower()


@pytest.mark.anyio
async def test_cannot_cancel_completed_order(client, monkeypatch):
    _freeze_time(monkeypatch, 10, 0)
    student_token = await _register_and_login(client, _u("cancels4"), "password123", "Cancel Student 4", "student")
    shop, product = _approved_shop_with_product(_u("cancels4vendor") + "@example.com", "Cancel Vendor 4")
    order = await _place_order(client, shop["id"], product["id"], "Cancel Student 4", method="COD", token=student_token)
    db.update_order_status(order["id"], "Completed")

    res = await client.post(
        f"/api/v1/local/orders/{order['id']}/cancel",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert res.status_code == 400


@pytest.mark.anyio
async def test_cannot_cancel_someone_elses_order(client, monkeypatch):
    import app.api.v1.local as local_mod

    _freeze_time(monkeypatch, 10, 0)
    monkeypatch.setattr(local_mod, "slot_cutoff_for", lambda _dt: time(12, 30))
    student_token = await _register_and_login(client, _u("cancels5"), "password123", "Cancel Student 5", "student")
    await _register_and_login(client, _u("cancels6"), "password123", "Other Student", "student", phone="+919000000001")
    shop, product = _approved_shop_with_product(_u("cancels5vendor") + "@example.com", "Cancel Vendor 5")
    order = await _place_order(client, shop["id"], product["id"], "Cancel Student 5", method="COD", token=student_token)

    # The wrong student can't cancel it — the order belongs to someone else.
    other_token = (await client.post("/api/v1/local/auth/login", json={"username": _u("cancels6"), "password": "password123"})).json()["access_token"]
    res = await client.post(
        f"/api/v1/local/orders/{order['id']}/cancel",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert res.status_code == 403

    # The owner CAN still cancel it (same window as before).
    res2 = await client.post(
        f"/api/v1/local/orders/{order['id']}/cancel",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert res2.status_code == 200
