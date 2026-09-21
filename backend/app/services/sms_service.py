"""
SMS notification + order confirmation service.

Purpose
-------
The pipeline is: a student places an order → an SMS lands on the
shopkeeper's phone (and a copy reaches the admin) with the order details
and a plain-text confirm line → the shopkeeper replies ``YES <token>`` (or
``NO <token>``) → the incoming webhook (``POST /api/v1/local/sms/incoming``)
parses the reply and updates the order to **Confirmed** (or **Cancelled**).

Because there is no SMS provider key in the codebase yet, ``send_sms`` logs
every message to the ``sms_logs`` table and raises only on real gateway
failures — so the flow works end-to-end out of the box, and a real gateway
(Twilio / Fast2SMS / Textlocal) can be dropped in by replacing the single
``send_sms`` function. Nothing in the API layer changes.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# International SMS length cap (160 ASCII chars). Longer messages are split by
# the gateway; the completion line (YES/NO + token) is always the LAST fragment
# so it is never truncated away from a human reader.
SMS_LIMIT = 160


def or_none(value: Any) -> str:
    """Best-effort compact string for an optional field."""
    return str(value).strip() if value not in (None, "") else ""


def compose_order_sms(order: dict[str, Any]) -> str:
    """Build a clear, human-readable order SMS for the shopkeeper.

    Verbs are ALL-CAP and the reply instruction is the final line so the
    confirm action is impossible to miss. Every relevant fact the shop needs
    to accept the order is on its own line.
    """
    token = order.get("token") or order.get("id") or "?"
    items = or_none(order.get("items"))
    if not items:
        # Fallback: render item lines from the products list if present.
        products = order.get("products") or []
        items = ", ".join(
            f"{p.get('quantity', 1)}x {p.get('name', 'Item')}" for p in products
        ) or "(no items listed)"

    student = or_none(order.get("student_name")) or "(no name)"
    location = or_none(order.get("delivery_location")) or "(no location)"
    slot = or_none(order.get("delivery_slot")) or "Next batch"
    created = str(order.get("created_at") or "")[11:16] or "just now"
    amount = order.get("total") or 0
    payment = or_none(order.get("payment_method")) or "UPI"
    if payment.upper() == "COD":
        payment = "CASH ON DELIVERY"

    return (
        f"DETOMSITE ORDER #{token}\n"
        f"NEW ORDER ({created})\n"
        f"Student: {student}\n"
        f"Items: {items}\n"
        f"Where: {location}\n"
        f"Slot: {slot}\n"
        f"Pay: {payment.upper()} Rs {amount}\n"
        f"REPLY: YES {token} = CONFIRM | NO {token} = REJECT"
    )


def compose_confirmation_sms(order: dict[str, Any]) -> str:
    """SMS back to the student confirming their order is accepted."""
    token = order.get("token") or order.get("id") or "?"
    shop = or_none(order.get("shop_name"))
    return (
        f"DETOMSITE ORDER #{token} CONFIRMED ✓\n"
        f"{shop} accepted your order.\n"
        f"Track it in the app — collect from the counter when Ready."
    )


def compose_order_wa(order: dict[str, Any], paid: bool | None = None) -> str:
    """WhatsApp-ready order message for the shopkeeper.

    Same facts as the SMS but reads naturally on WhatsApp (no CAPS shout, no
    reply-token — the shopkeeper confirms from their app/portal instead). This
    text is pre-filled into a ``wa.me`` chat with the shop's WhatsApp number,
    so the shopkeeper receives it **from the admin's own number**, for free.

    ``paid`` reflects whether the payment is verified *at send time*:
      - ``True``  → "UPI paid ₹X ✓"   (bank-SMS/UTR match, screenshot verified)
      - ``False`` → "UPI ₹X — awaiting payment"   (order just placed, no proof yet)
      - ``None``  → old behaviour: assume the payer is proven (legacy callers)
    COD is always shown as "Cash on Delivery ₹X".
    """
    token = order.get("token") or order.get("id") or "?"
    items = or_none(order.get("items"))
    if not items:
        products = order.get("products") or []
        items = ", ".join(
            f"{p.get('quantity', 1)}x {p.get('name', 'Item')}" for p in products
        ) or "(no items listed)"
    student = or_none(order.get("student_name")) or "(no name)"
    location = or_none(order.get("delivery_location")) or "(no location)"
    slot = or_none(order.get("delivery_slot")) or "Next batch"
    amount = order.get("total") or 0
    payment = or_none(order.get("payment_method")) or "UPI"
    if payment.upper() == "COD":
        paid_label = "Cash on Delivery ₹" + str(amount)
    elif paid is False:
        paid_label = f"{payment.upper()} ₹{amount} — awaiting payment"
    else:
        paid_label = f"{payment.upper()} paid ₹{amount} ✓"
    # Unique per-order reference. A multi-shop (combo) order shares ONE token
    # across all its shop sub-orders, so the token alone cannot tell two
    # sub-order messages apart — the phone bot uses this Ref to verify the
    # exact message it is about to send and never taps the wrong chat.
    ref = or_none(order.get("id"))
    ref_line = f"\n• Ref: {ref}" if ref else ""
    return (
        f"Hello! New DETOMSITE order #{token} for you 🛵\n\n"
        f"• Student: {student}\n"
        f"• Items: {items}\n"
        f"• Deliver to: {location}\n"
        f"• Slot: {slot}\n"
        f"• Payment: {paid_label}{ref_line}\n\n"
        f"Please confirm this order in the DETOMSITE shop app. "
        f"Thank you!"
    )


async def send_sms_async(
    phone: str,
    message: str,
    log_fn: Callable[..., Any],
    sub_order_id: str = "",
) -> bool:
    """Fire an SMS off the event loop and persist it in ``sms_logs``.

    ``log_fn`` is the active store's ``log_sms`` (wired differently for the
    SQLite/Supabase sync store and the async Mongo store), called on the
    worker thread. Returns True when the SMS was accepted.
    """
    if not phone or not phone.strip():
        return False
    try:
        await asyncio.to_thread(log_fn, sub_order_id, phone, message, "Sent")
        logger.info(f"SMS → {phone}: {message.splitlines()[0]}")
        return True
    except Exception as e:
        logger.error(f"SMS send failed to {phone}: {e}")
        return False