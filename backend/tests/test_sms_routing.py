"""Payment proof routing must never guess a customer from an amount."""
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from app.api.v1 import local


@pytest.fixture
def matching(monkeypatch):
    shop = {"id": "shop-a", "phone": "9876543210", "whatsapp_number": "9876543210"}
    orders = [
        {"id": "older", "shop_id": "shop-a", "status": "Pending Payment", "total": 80,
         "payment_method": "UPI", "created_at": "2026-09-17T10:00:00"},
        {"id": "newer", "shop_id": "shop-a", "status": "Pending Payment", "total": 80,
         "payment_method": "UPI", "created_at": "2026-09-17T10:01:00"},
    ]
    payments = [{"id": "p1", "order_id": "older", "utr_number": "123456789012", "amount": 80, "status": "Pending"}]
    writes = []

    async def fake_db(fn, *args, **kwargs):
        name = fn.__name__
        if name == "get_shop_by_phone": return shop
        if name == "list_orders_by_shop": return orders
        if name == "list_payments": return payments
        if name == "get_payment_by_order_id":
            return next((p for p in payments if p["order_id"] == args[0]), None)
        if name in ("create_payment", "set_payment_utr", "update_payment_status", "update_order_status"):
            writes.append((name, args, kwargs))
        return {"id": "result"}

    monkeypatch.setattr(local, "_db", fake_db)
    monkeypatch.setattr(local, "_push_admin", lambda *a, **k: None)
    monkeypatch.setattr(local, "_notify_shop_via_whatsapp", AsyncMock())
    monkeypatch.setattr(local.settings, "SMS_FORWARD_KEY", "test-key")
    return orders, payments, writes


async def test_saved_utr_selects_older_order_not_newest_amount(matching):
    result = await local.sms_match(local.LocalSmsMatch(phone="9876543210", utr="123456789012", amount=80), "test-key")
    assert result["order_id"] == "older"
    assert local._notify_shop_via_whatsapp.await_args.args[0]["id"] == "older"


@pytest.mark.parametrize("case", ["missing", "duplicate", "other_shop", "wrong_amount", "already_paid", "cod"])
async def test_uncertain_proof_never_changes_order_or_sends(matching, case):
    orders, payments, writes = matching
    if case == "missing": payments.clear()
    if case == "duplicate": payments.append(dict(payments[0], id="p2", order_id="newer"))
    if case == "other_shop": payments[0]["order_id"] = "another-shop-order"
    if case == "wrong_amount": payments[0]["amount"] = 90
    if case == "already_paid": payments[0]["status"] = "Success"
    if case == "cod": orders[0]["payment_method"] = "COD"
    with pytest.raises(HTTPException):
        await local.sms_match(local.LocalSmsMatch(phone="9876543210", utr="123456789012", amount=80), "test-key")
    assert not writes
    local._notify_shop_via_whatsapp.assert_not_awaited()


@pytest.mark.parametrize("text", [
    "A/c credited Rs 80. Avl bal Rs 5000. Account 123456789012",
    "Debited Rs 80 UTR:123456789012",
    "OTP 123456 for UPI txn Ref:123456789012",
])
def test_non_credit_or_unlabelled_reference_is_not_proof(text):
    assert local._extract_utr(text) == ""


def test_balance_is_not_payment_amount():
    assert local._extract_amount("Avl bal Rs 5000. Credited Rs 80 UTR:123456789012") == 80
    assert local._extract_amount("Credit received. Available balance Rs 5000") is None
