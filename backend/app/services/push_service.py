"""
Web Push service — "new order" notifications for the installed vendor app.

Flow:
  1. The vendor app (installed PWA) asks the browser for a push subscription
     and registers it via ``POST /api/v1/vendor/push/subscribe``.
  2. When a student places an order, ``local.py`` calls
     ``notify_shop_new_order_async`` (fire-and-forget).
  3. This module looks up the shop's subscriptions and delivers a web push
     with the order details. The browser's service worker (mobile/sw.js)
     turns it into a system notification on the vendor's phone.

VAPID keys:
  - Prefer ``VAPID_PUBLIC_KEY`` / ``VAPID_PRIVATE_KEY`` / ``VAPID_SUBJECT``
    from the environment (set these in production, e.g. Render env vars).
  - If they are missing, a local ``backend/vapid_keys.json`` is auto-generated
    (git-ignored) so the feature works out of the box in development.
  - If neither exists (e.g. pywebpush not installed), push is simply disabled
    — in-app notifications still work and nothing crashes.
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.store import store as db

logger = logging.getLogger(__name__)

# backend/vapid_keys.json — auto-generated local dev keys (git-ignored).
_VAPID_FILE = Path(__file__).resolve().parents[2] / "vapid_keys.json"


def get_vapid_keys() -> dict[str, str] | None:
    """Return ``{public_key, private_key, subject}`` or ``None`` if push is
    not configured (and cannot be auto-configured).

    Production (``DEBUG=False``) requires the env vars — a key file generated
    on a server's ephemeral filesystem would be lost on every redeploy and
    silently invalidate every registered subscription. In development the
    git-ignored ``backend/vapid_keys.json`` is auto-generated for zero-config."""
    public_key = (settings.VAPID_PUBLIC_KEY or "").strip()
    private_key = (settings.VAPID_PRIVATE_KEY or "").strip()
    if public_key and private_key:
        return {
            "public_key": public_key,
            "private_key": private_key,
            "subject": (settings.VAPID_SUBJECT or "mailto:admin@detomsite.local").strip(),
        }

    # Development only from here on — never auto-generate on a prod server.
    if not settings.DEBUG:
        logger.error(
            "Web push disabled: set VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY "
            "env vars (generate with python backend/scripts/gen_vapid.py)."
        )
        return None

    # Dev convenience: reuse the auto-generated local key file if present.
    try:
        if _VAPID_FILE.exists():
            data = json.loads(_VAPID_FILE.read_text(encoding="utf-8"))
            if data.get("public_key") and data.get("private_key"):
                return {
                    "public_key": data["public_key"],
                    "private_key": data["private_key"],
                    "subject": (data.get("subject") or "mailto:admin@detomsite.local").strip(),
                }
    except Exception as e:
        logger.warning(f"Could not read {_VAPID_FILE}: {e}")

    # Generate a fresh key pair with the already-installed cryptography lib.
    try:
        from cryptography.hazmat.primitives.asymmetric import ec

        private_key_obj = ec.generate_private_key(ec.SECP256R1())
        private_value = private_key_obj.private_numbers().private_value.to_bytes(32, "big")
        public_numbers = private_key_obj.public_key().public_numbers()
        # Uncompressed SEC1 point: 0x04 || x || y (VAPID public key format).
        point = b"\x04" + public_numbers.x.to_bytes(32, "big") + public_numbers.y.to_bytes(32, "big")
        _b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
        new_keys = {
            "public_key": _b64(point),
            "private_key": _b64(private_value),
            "subject": (settings.VAPID_SUBJECT or "mailto:admin@detomsite.local").strip(),
        }
        _VAPID_FILE.write_text(json.dumps(new_keys, indent=2), encoding="utf-8")
        logger.info(
            "Auto-generated local VAPID keys at %s — for production set "
            "VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY env vars instead.",
            _VAPID_FILE,
        )
        return new_keys
    except Exception as e:
        logger.warning(f"Web push disabled — could not load/generate VAPID keys: {e}")
        return None


def send_order_push(order: dict[str, Any]) -> int:
    """Deliver a 'new order' web push to every subscription of the order's
    shop. Returns how many pushes were sent. Never raises — failures are
    logged and dead subscriptions are cleaned up (410/404 from the push
    service means the browser uninstalled/revoked)."""
    keys = get_vapid_keys()
    if not keys:
        return 0

    shop_id = order.get("shop_id", "")
    try:
        subscriptions = db.list_push_subscriptions(shop_id)
    except Exception as e:
        logger.warning(f"Could not list push subscriptions for shop {shop_id}: {e}")
        return 0
    if not subscriptions:
        return 0

    payment_method = str(order.get("payment_method", "") or "").upper()
    if payment_method == "COD":
        method_label = "Cash on Delivery — collect ₹%s" % order.get("total", 0)
    elif payment_method == "UPI":
        method_label = "UPI payment — confirm in your UPI app"
    else:
        method_label = "Payment done"

    student_phone = (order.get("student_phone") or "").strip()
    phone_line = f"\n📞 {student_phone}" if student_phone else ""
    delivery_loc = (order.get("delivery_location") or "").strip()
    loc_line = f"\n📍 {delivery_loc}" if delivery_loc else ""

    payload = json.dumps({
        "title": f"🛎️ New Order #{order.get('token', '')}",
        "body": f"{order.get('items', '')} · ₹{order.get('total', 0)} · {method_label}{phone_line}{loc_line}",
        "tag": f"order-{order.get('id', '')}",
        "url": "/mobile",
        "student_phone": student_phone,
        "student_name": order.get("student_name", ""),
        "delivery_location": delivery_loc,
    })

    return _deliver(shop_id, subscriptions, payload, keys)


def send_test_push(shop_id: str) -> dict[str, Any]:
    """Send a test push to one shop's subscribed devices and return a
    human-readable result (used by the vendor app's test button)."""
    keys = get_vapid_keys()
    if not keys:
        return {"ok": False, "detail": "Push is not configured on the server yet (VAPID keys missing)."}
    try:
        subscriptions = db.list_push_subscriptions(shop_id)
    except Exception as e:
        logger.warning(f"Could not list push subscriptions for shop {shop_id}: {e}")
        return {"ok": False, "detail": "Could not read subscriptions from the database."}
    if not subscriptions:
        return {
            "ok": False,
            "detail": "No device is subscribed for this shop yet — tap 'Enable Order Notifications' first, then try again.",
        }

    payload = json.dumps({
        "title": "🔔 Test notification",
        "body": "Your vendor app notifications are working!",
        "tag": "test-push",
        "url": "/mobile",
    })
    sent, errors = _deliver_detailed(shop_id, subscriptions, payload, keys)
    if sent:
        return {"ok": True, "sent": sent, "detail": f"Sent to {sent} device(s). Check your phone!"}
    return {"ok": False, "detail": "Push failed: " + ("; ".join(errors[:2]) if errors else "unknown error")}


def _deliver(shop_id: str, subscriptions: list[dict], payload: str, keys: dict) -> int:
    """Deliver ``payload`` to every subscription. Returns how many succeeded."""
    sent, _ = _deliver_detailed(shop_id, subscriptions, payload, keys)
    return sent


def _deliver_detailed(shop_id: str, subscriptions: list[dict], payload: str, keys: dict) -> tuple[int, list[str]]:
    """Deliver ``payload`` to every subscription, returning (sent_count, errors).
    Dead subscriptions (404/410) are removed from the store so we stop
    failing on them. Never raises."""
    try:
        from pywebpush import WebPushException, webpush
    except ImportError as e:
        logger.warning(f"pywebpush not installed — web push skipped: {e}")
        return 0, [str(e)]

    sent = 0
    errors: list[str] = []
    for subscription in subscriptions:
        endpoint = str(subscription.get("endpoint", "") or "")
        if not endpoint.startswith("https://"):
            continue
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription["endpoint"],
                    "keys": {
                        "p256dh": subscription["p256dh"],
                        "auth": subscription["auth"],
                    },
                },
                data=payload,
                vapid_private_key=keys["private_key"],
                vapid_claims={"sub": keys["subject"]},
                timeout=6,
            )
            sent += 1
        except WebPushException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):
                # Subscription is dead — drop it so we stop failing on it.
                try:
                    db.remove_push_subscription(shop_id, subscription["endpoint"])
                except Exception as cleanup_error:
                    logger.warning(f"Could not clean up dead subscription: {cleanup_error}")
            else:
                errors.append(f"{status or ''} {str(e)}".strip())
                logger.warning(f"Web push rejected for {subscription['endpoint']}: {e}")
        except Exception as e:
            errors.append(str(e))
            logger.warning(f"Web push failed for {subscription['endpoint']}: {e}")
    return sent, errors


async def notify_shop_new_order_async(order: dict[str, Any]) -> None:
    """Fire the order push off the event loop (blocking HTTP calls run in a
    worker thread). Never raises — order placement must not be affected."""
    import asyncio

    try:
        await asyncio.to_thread(send_order_push, order)
    except Exception:
        logger.exception("Unexpected error while sending order push notification")
