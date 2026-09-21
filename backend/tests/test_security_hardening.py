"""
Security regressions found while pentesting the payment / ordering surface.

Every test here pins a hole that was reachable by a plain authenticated student
(or, in the agent-key cases, by an anonymous caller):

* a Razorpay order started life as ``Pending Acceptance`` — i.e. an unpaid order,
  so ``payment_method="Razorpay"`` alone bought a free order (the vendor is SMSed
  the moment the order row is created);
* ``/payments/create-razorpay-order`` was unauthenticated AND trusted the
  request's ``amount``, so a ₹1 gateway order could be opened against a ₹500 bill;
* ``/payments/verify-razorpay`` was unauthenticated, unbounded in amount, and
  replayable;
* ``POST /local/payments`` accepted a client-supplied ``amount``;
* ``quantity`` was silently dropped from the order payload, so every line billed
  as a single unit regardless of what the cart sent;
* the bank-SMS / WhatsApp agent endpoints skipped their key check entirely when
  ``SMS_FORWARD_KEY`` was unset — and both can mark an order paid.
"""
import uuid
from unittest.mock import AsyncMock

from app.core.store import store as db
from test_order_cancel import _approved_shop_with_product, _register_and_login

_RUN = uuid.uuid4().hex[:6]


def _u(base: str) -> str:
    return f"{base}_{_RUN}"


async def _student_with_order(client, monkeypatch, *, quantity=1, method="UPI", price=100):
    """Register a student, give them an approved shop + product, place an order.

    Order notifications are stubbed out so no SMS/push provider is touched.
    """
    from app.api.v1 import local

    monkeypatch.setattr(local, "_notify_order_via_sms", AsyncMock())
    monkeypatch.setattr(local.push_service, "notify_shop_new_order_async", AsyncMock())

    token = await _register_and_login(client, _u("sec"), "password123", "Sec Student", "student")
    headers = {"Authorization": f"Bearer {token}"}
    shop, product = _approved_shop_with_product(f"{_u('sec_vendor')}@example.com", "Sec Vendor")
    res = await client.post("/api/v1/local/orders", headers=headers, json={
        "shop_id": shop["id"],
        "items": [{"product_id": product["id"], "quantity": quantity}],
        "student_name": "Sec Student",
        "student_phone": "+919000000123",
        "delivery_location": "Test location",
        "delivery_slot": "Evening",
        "payment_method": method,
    })
    assert res.status_code == 200, res.text
    order = res.json()
    assert order["total"] == price * quantity
    return headers, order, shop, product


class TestQuantityIsBilled:
    async def test_quantity_survives_the_request_schema(self, client, monkeypatch):
        """Pydantic used to drop the unknown ``quantity`` field entirely."""
        _headers, order, _shop, _product = await _student_with_order(client, monkeypatch, quantity=3)
        assert order["total"] == 300

    async def test_absurd_quantity_is_rejected(self, client, monkeypatch):
        from app.api.v1 import local

        monkeypatch.setattr(local, "_notify_order_via_sms", AsyncMock())
        token = await _register_and_login(client, _u("bigqty"), "password123", "Big Qty", "student")
        shop, product = _approved_shop_with_product(f"{_u('bigqty_v')}@example.com", "Big Qty Vendor")
        res = await client.post("/api/v1/local/orders", headers={"Authorization": f"Bearer {token}"}, json={
            "shop_id": shop["id"],
            "items": [{"product_id": product["id"], "quantity": 100000}],
            "delivery_location": "Test location", "delivery_slot": "Evening", "payment_method": "UPI",
        })
        assert res.status_code == 422

    async def test_multi_shop_quantity_is_bounded(self, client, monkeypatch):
        from app.api.v1 import local

        monkeypatch.setattr(local, "_notify_shop_via_whatsapp", AsyncMock())
        monkeypatch.setattr(local.push_service, "notify_shop_new_order_async", AsyncMock())
        token = await _register_and_login(client, _u("mq"), "password123", "Multi Qty", "student")
        shop, product = _approved_shop_with_product(f"{_u('mq_v')}@example.com", "Multi Qty Vendor")
        res = await client.post("/api/v1/local/orders/multi", headers={"Authorization": f"Bearer {token}"}, json={
            "shops": [{"shop_id": shop["id"], "items": [{"product_id": product["id"], "quantity": 0}]}],
            "student_name": "Multi Qty", "student_phone": "+919000000124",
            "delivery_location": "Test location", "payment_method": "UTR",
        })
        assert res.status_code == 400


class TestRazorpayBypass:
    async def test_razorpay_order_is_not_fulfillable_before_payment(self, client, monkeypatch):
        """THE critical bug: unpaid Razorpay orders must start unpaid."""
        _headers, order, _shop, _product = await _student_with_order(
            client, monkeypatch, method="Razorpay",
        )
        assert order["status"] == "Pending Payment"
        assert order["payment_method"].upper() == "RAZORPAY"

    async def test_cod_order_still_reaches_the_shop(self, client, monkeypatch):
        _headers, order, _shop, _product = await _student_with_order(client, monkeypatch, method="COD")
        assert order["status"] in ("Pending Acceptance", "Accepted")

    async def test_unknown_payment_method_is_rejected(self, client, monkeypatch):
        from app.api.v1 import local

        monkeypatch.setattr(local, "_notify_order_via_sms", AsyncMock())
        token = await _register_and_login(client, _u("badmethod"), "password123", "Bad Method", "student")
        shop, product = _approved_shop_with_product(f"{_u('badm_v')}@example.com", "Bad Method Vendor")
        res = await client.post("/api/v1/local/orders", headers={"Authorization": f"Bearer {token}"}, json={
            "shop_id": shop["id"], "items": [{"product_id": product["id"], "quantity": 1}],
            "delivery_location": "Test location", "delivery_slot": "Evening",
            "payment_method": "FREE_FOR_ME",
        })
        assert res.status_code == 422

    async def test_create_razorpay_order_requires_auth(self, client, monkeypatch):
        _headers, order, _shop, _product = await _student_with_order(client, monkeypatch)
        res = await client.post("/api/v1/local/payments/create-razorpay-order", json={
            "amount": 100, "currency": "INR", "order_id": order["id"],
        })
        assert res.status_code == 401

    async def test_create_razorpay_order_rejects_a_short_amount(self, client, monkeypatch):
        """A ₹1 gateway order for a ₹100 bill must be refused."""
        from app.core.config import settings

        headers, order, _shop, _product = await _student_with_order(client, monkeypatch)
        db.update_payment_settings({"razorpay_enabled": True})
        monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_key")
        monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "rzp_test_secret")

        res = await client.post(
            "/api/v1/local/payments/create-razorpay-order",
            headers=headers,
            json={"amount": 100, "currency": "INR", "order_id": order["id"]},  # 100 paise = ₹1
        )
        assert res.status_code == 400
        assert "100" in res.json()["detail"]

    async def test_verify_razorpay_requires_auth(self, client, monkeypatch):
        _headers, order, _shop, _product = await _student_with_order(client, monkeypatch)
        res = await client.post("/api/v1/local/payments/verify-razorpay", json={
            "razorpay_order_id": "order_x", "razorpay_payment_id": "pay_x",
            "razorpay_signature": "sig", "order_id": order["id"],
        })
        assert res.status_code == 401

    async def test_verify_razorpay_denies_a_foreign_order(self, client, monkeypatch):
        _headers, order, _shop, _product = await _student_with_order(client, monkeypatch)
        intruder = await _register_and_login(client, _u("intruder"), "password123", "Intruder", "student")
        res = await client.post(
            "/api/v1/local/payments/verify-razorpay",
            headers={"Authorization": f"Bearer {intruder}"},
            json={
                "razorpay_order_id": "order_x", "razorpay_payment_id": "pay_x",
                "razorpay_signature": "sig", "order_id": order["id"],
            },
        )
        assert res.status_code == 403

    async def test_verify_razorpay_refuses_an_already_settled_order(self, client, monkeypatch):
        """A COD order (Pending Acceptance) is never 'awaiting payment'."""
        headers, order, _shop, _product = await _student_with_order(client, monkeypatch, method="COD")
        res = await client.post("/api/v1/local/payments/verify-razorpay", headers=headers, json={
            "razorpay_order_id": "order_x", "razorpay_payment_id": "pay_x",
            "razorpay_signature": "sig", "order_id": order["id"],
        })
        assert res.status_code == 400
        assert "awaiting" in res.json()["detail"].lower()


class TestPaymentAmountIntegrity:
    async def test_payment_amount_comes_from_the_stored_order(self, client, monkeypatch):
        """A client-declared ₹1 must not become the recorded amount."""
        headers, order, _shop, _product = await _student_with_order(client, monkeypatch, quantity=2)
        res = await client.post("/api/v1/local/payments", headers=headers, json={
            "order_id": order["id"], "amount": 1, "method": "UPI", "utr_number": "UTR0001",
        })
        assert res.status_code == 200, res.text
        assert res.json()["amount"] == 200  # 2 x ₹100, not ₹1
        stored = [p for p in db.list_payments() if p["order_id"] == order["id"] and p["utr_number"] == "UTR0001"]
        assert stored and stored[0]["amount"] == 200

    async def test_unsupported_payment_method_is_rejected(self, client, monkeypatch):
        headers, order, _shop, _product = await _student_with_order(client, monkeypatch)
        res = await client.post("/api/v1/local/payments", headers=headers, json={
            "order_id": order["id"], "amount": 100, "method": "Magic Beans",
        })
        assert res.status_code == 422


class TestAgentEndpointsFailClosed:
    """The agent-key endpoints must not become public when the key is unset."""

    async def test_sms_match_requires_key_when_configured(self, client, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "SMS_FORWARD_KEY", "secret-agent-key")
        res = await client.post("/api/v1/local/sms/match", json={
            "phone": "+919000000999", "utr": "ABC12345678", "amount": 100,
        }, headers={"X-Agent-Key": "wrong"})
        assert res.status_code == 401

    async def test_sms_match_fails_closed_without_a_configured_key(self, client, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "SMS_FORWARD_KEY", "")
        monkeypatch.setattr(settings, "DEBUG", False)
        res = await client.post("/api/v1/local/sms/match", json={
            "phone": "+919000000999", "utr": "ABC12345678", "amount": 100,
        })
        assert res.status_code == 503

    async def test_sms_incoming_fails_closed_without_a_configured_key(self, client, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "SMS_FORWARD_KEY", "")
        monkeypatch.setattr(settings, "DEBUG", False)
        res = await client.post("/api/v1/local/sms/incoming", json={
            "phone": "+919000000999", "text": "YES TOKEN123",
        })
        assert res.status_code == 503

    async def test_whatsapp_pending_fails_closed_without_a_configured_key(self, client, monkeypatch):
        """This feed exposes customer phone numbers + order messages."""
        from app.core.config import settings
        monkeypatch.setattr(settings, "SMS_FORWARD_KEY", "")
        monkeypatch.setattr(settings, "DEBUG", False)
        res = await client.get("/api/v1/local/whatsapp/pending")
        assert res.status_code == 503

    async def test_agent_endpoints_stay_usable_for_the_agent(self, client, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "SMS_FORWARD_KEY", "secret-agent-key")
        key_header = {"X-Agent-Key": "secret-agent-key"}
        # Keyword behaviour skips (no order matches), so the exact body does not
        # matter — what matters is that the agent is NOT rejected.
        assert (await client.get("/api/v1/local/whatsapp/pending", headers=key_header)).status_code == 200
        res = await client.post("/api/v1/local/sms/match", headers=key_header, json={
            "phone": "+919000000999", "utr": "NOPE12345678", "amount": 100,
        })
        # Accepted by the agent gate (no matching order exists → no order was
        # confirmed); a 401/503 would mean the key check wrongly rejected it.
        assert res.status_code not in (401, 503), res.text


class TestUploadLimits:
    async def test_oversized_screenshot_is_rejected(self, client, monkeypatch):
        from app.api.v1.local import MAX_UPLOAD_BYTES

        headers, order, _shop, _product = await _student_with_order(client, monkeypatch)
        blob = b"\x89PNG\r\n\x1a\n" + b"0" * (MAX_UPLOAD_BYTES + 1024)
        res = await client.post(
            "/api/v1/local/payments/upload",
            headers=headers,
            data={"order_id": order["id"], "utr_number": "UTR9"},
            files={"file": ("proof.png", blob, "image/png")},
        )
        assert res.status_code == 413
