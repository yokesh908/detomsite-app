"""Per-shop WhatsApp notifications on multi-shop (combo) orders.

Regression guard for the "all messages went to the LAST shop, three times" bug:
a combo order shares ONE token across its shop sub-orders, so every WhatsApp
message must be individually addressable. These tests pin the backend side:

  1. A COD multi-shop order logs exactly ONE WhatsApp message per shop,
     addressed to THAT shop's number and containing ONLY that shop's items.
  2. Every message carries a unique ``Ref: <sub-order-id>`` line so the on-phone
     bot can verify the exact message on screen and never tap Send in the wrong
     chat (the old token-only verification matched every sub-order).
"""
from unittest.mock import AsyncMock

from app.api.v1 import local
from app.core.store import store as db
from test_order_cancel import _approved_shop_with_product, _register_and_login


def _shop_with_whatsapp(email: str, name: str, whatsapp: str, product_name: str):
    """Approved, open shop with its own WhatsApp number and one product."""
    shop, _ = _approved_shop_with_product(email, name)
    updated = db.update_shop(shop["id"], {"whatsapp_number": whatsapp})
    assert updated and updated["whatsapp_number"] == whatsapp
    product = db.create_product({
        "shop_id": shop["id"],
        "name": product_name,
        "description": "",
        "price": 100,
        "category": "Food",
        "inventory": 10,
        "prep_time": 10,
        "available": True,
    })
    return shop, product


async def test_cod_multi_shop_order_notifies_each_shop_individually(client, monkeypatch):
    monkeypatch.setattr(local.push_service, "notify_shop_new_order_async", AsyncMock())
    token = await _register_and_login(client, "wamulti", "password123", "WA Student", "student")
    shop_a, prod_a = _shop_with_whatsapp("waa@example.com", "Shop A", "9600000001", "Biryani A")
    shop_b, prod_b = _shop_with_whatsapp("wab@example.com", "Shop B", "9600000002", "Dosa B")

    res = await client.post("/api/v1/local/orders/multi", headers={"Authorization": f"Bearer {token}"}, json={
        "shops": [
            {"shop_id": shop_a["id"], "items": [{"product_id": prod_a["id"], "quantity": 1}]},
            {"shop_id": shop_b["id"], "items": [{"product_id": prod_b["id"], "quantity": 2}]},
        ],
        "student_name": "WA Student", "student_phone": "+919876543210",
        "delivery_location": "VIT-AP Test location", "payment_method": "COD",
    })
    assert res.status_code == 200, res.text
    subs = res.json()["sub_orders"]
    assert len(subs) == 2

    logs = db.list_whatsapp_logs(100)
    by_sub = {log["sub_order_id"]: log for log in logs}
    # One message per sub-order — never one number receiving everything.
    assert set(by_sub) == {subs[0]["id"], subs[1]["id"]}
    for sub in subs:
        log = by_sub[sub["id"]]
        assert log["phone"] == sub["shop_whatsapp"]
        own_item = "Biryani A" if sub["shop_id"] == shop_a["id"] else "Dosa B"
        other_item = "Dosa B" if sub["shop_id"] == shop_a["id"] else "Biryani A"
        # The message contains ONLY this shop's items — never another shop's.
        assert own_item in log["message"]
        assert other_item not in log["message"]
        # Unique Ref line so the phone bot can tell the messages apart.
        assert f"Ref: {sub['id']}" in log["message"]


def test_compose_order_wa_ref_is_unique_per_sub_order():
    order_a = {"id": "p20260921-18-1", "token": 18, "items": "1x Biryani", "total": 100,
               "payment_method": "COD", "student_name": "S", "delivery_location": "VIT-AP L"}
    order_b = {"id": "p20260921-18-2", "token": 18, "items": "1x Dosa", "total": 100,
               "payment_method": "COD", "student_name": "S", "delivery_location": "VIT-AP L"}
    msg_a, msg_b = local.sms_service.compose_order_wa(order_a), local.sms_service.compose_order_wa(order_b)
    assert "Ref: p20260921-18-1" in msg_a
    assert "Ref: p20260921-18-2" in msg_b
    assert msg_a != msg_b  # same token, still distinguishable
