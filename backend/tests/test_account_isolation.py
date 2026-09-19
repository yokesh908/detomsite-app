"""Account isolation regressions; all data is in the throwaway test store."""
from unittest.mock import AsyncMock

from app.api.v1 import local
from app.core.store import store as db
from test_order_cancel import _approved_shop_with_product, _register_and_login


async def test_order_is_bound_to_account_not_contact_details(client, monkeypatch):
    monkeypatch.setattr(local, "_notify_order_via_sms", AsyncMock())
    monkeypatch.setattr(local.push_service, "notify_shop_new_order_async", AsyncMock())
    token = await _register_and_login(client, "owner", "password123", "Same Name", "student")
    shop, product = _approved_shop_with_product("vendor@example.com", "Vendor")
    # No messaging providers are configured in this isolated test.
    response = await client.post("/api/v1/local/orders", headers={"Authorization": f"Bearer {token}"}, json={
        "shop_id": shop["id"], "items": [{"product_id": product["id"], "quantity": 1}],
        "student_name": "Different contact", "student_phone": "+919000000002",
        "delivery_location": "Test location", "delivery_slot": "Evening", "payment_method": "UPI",
    })
    assert response.status_code == 200
    order = response.json()
    owner = db.get_user_by_username("owner")
    assert str(order.get("owner_user_id")) == str(owner["id"])
    assert local._same_student(owner, order)
    assert not local._same_student({"id": 99999, "name": order["student_name"], "phone": order["student_phone"]}, order)


def test_legacy_order_is_not_claimed_by_name_phone_or_client_student_id():
    assert not local._same_student(
        {"id": 1, "name": "Same Name", "phone": "+919876543210"},
        {"student_id": "1", "student_name": "Same Name", "student_phone": "+919876543210"},
    )


async def test_notifications_are_filtered_by_owned_order(client):
    token = await _register_and_login(client, "reader", "password123", "Reader", "student")
    db.create_notification("Private", "Another student's order", order_id="unknown-order", target_role="student")
    db.create_notification("Admin only", "Private admin event", target_role="admin")
    response = await client.get("/api/v1/local/notifications", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == []


async def test_multi_shop_order_persists_owner_and_denies_other_account(client, monkeypatch):
    monkeypatch.setattr(local.push_service, "notify_shop_new_order_async", AsyncMock())
    monkeypatch.setattr(local, "_notify_shop_via_whatsapp", AsyncMock())
    owner_token = await _register_and_login(client, "multi_owner", "password123", "Same Name", "student")
    other_token = await _register_and_login(client, "multi_other", "password123", "Same Name", "student")
    owner = db.get_user_by_username("multi_owner")
    other = db.get_user_by_username("multi_other")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    other_headers = {"Authorization": f"Bearer {other_token}"}
    shop, product = _approved_shop_with_product("multi_vendor@example.com", "Multi Vendor")
    response = await client.post("/api/v1/local/orders/multi", headers=owner_headers, json={
        "shops": [{"shop_id": shop["id"], "items": [{"product_id": product["id"], "quantity": 1}]}],
        "student_name": "Same Name", "student_phone": "+919876543210",
        "student_id": str(other["id"]), "owner_user_id": str(other["id"]),
        "delivery_location": "Test location", "payment_method": "UTR",
    })
    assert response.status_code == 200, response.text
    order_id = response.json()["id"]
    # Read back the actual persisted row, not just the creation response.
    persisted = db.get_parent_order(order_id)
    assert persisted["owner_user_id"] == str(owner["id"])
    assert persisted["student_id"] == str(owner["id"])
    detail = f"/api/v1/local/orders/parent/{order_id}"
    assert (await client.get(detail, headers=owner_headers)).status_code == 200
    assert (await client.get(detail, headers=other_headers)).status_code == 403
    assert (await client.get("/api/v1/local/orders/parent", headers=other_headers)).json() == []
    assert (await client.patch(f"/api/v1/local/orders/{order_id}/cancel", headers=other_headers)).status_code == 403
    payment = await client.post("/api/v1/local/payments", headers=other_headers, json={
        "order_id": order_id, "amount": persisted["total"], "method": "Manual UTR",
    })
    assert payment.status_code == 403
    notification = db.create_notification("Owned order", "Private update", order_id=order_id, target_role="student")
    own_notices = await client.get("/api/v1/local/notifications", headers=owner_headers)
    assert notification["id"] in [row["id"] for row in own_notices.json()]
    for suffix in ("", "?role=admin"):
        notices = await client.get(f"/api/v1/local/notifications{suffix}", headers=other_headers)
        assert notices.status_code == 200
        assert notices.json() == []


async def test_two_tokens_keep_order_identity_separate(client, monkeypatch):
    monkeypatch.setattr(local, "_notify_order_via_sms", AsyncMock())
    monkeypatch.setattr(local, "_notify_shop_via_whatsapp", AsyncMock())
    monkeypatch.setattr(local.push_service, "notify_shop_new_order_async", AsyncMock())
    shop, product = _approved_shop_with_product("switch_vendor@example.com", "Switch Vendor")
    accounts = []
    for username, name, phone in (
        ("switch_a", "Student Alpha", "+919000000011"),
        ("switch_b", "Student Beta", "+919000000012"),
    ):
        token = await _register_and_login(client, username, "password123", name, "student", phone)
        headers = {"Authorization": f"Bearer {token}"}
        profile = await client.get("/api/v1/local/auth/me", headers=headers)
        assert profile.status_code == 200
        user = profile.json()
        assert (user["username"], user["name"], user["phone"]) == (username, name, phone)
        response = await client.post("/api/v1/local/orders/multi", headers=headers, json={
            "shops": [{"shop_id": shop["id"], "items": [{"product_id": product["id"], "quantity": 1}]}],
            "student_name": name, "student_phone": phone,
            "delivery_location": "Test location", "payment_method": "UTR",
        })
        assert response.status_code == 200, response.text
        order = response.json()
        assert (order["owner_user_id"], order["student_name"], order["student_phone"]) == (str(user["id"]), name, phone)
        accounts.append((headers, order["id"]))
    for headers, order_id in accounts:
        response = await client.get("/api/v1/local/orders/parent", headers=headers)
        assert response.status_code == 200
        assert [row["id"] for row in response.json()] == [order_id]

