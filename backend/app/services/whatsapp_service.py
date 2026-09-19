"""Automatic WhatsApp delivery for shopkeeper notifications.

How it works
------------
Every DETOMSITE order notification is stored in ``whatsapp_logs`` with a
``wa.me`` deep-link. Two ways it actually reaches the shopkeeper:

- **Manual (default, zero-cost):** the notification stays ``Pending`` and the
  admin taps its ``wa.me`` link in Admin → WhatsApp centre. WhatsApp opens with
  the order pre-filled and the admin sends it from their own number.

- **Automatic (needs a provider):** the moment a notification is generated —
  e.g. right AFTER the UPI payment is verified — one of the providers below
  delivers the message to the shopkeeper on its own, and the row flips to
  ``Sent``. If the send fails the row stays ``Pending`` so the admin can still
  tap the link (nothing is lost).

Providers (pick one by setting env vars):
- ``WA_PROVIDER=wassenger``  + ``WA_API_TOKEN`` (+ optional ``WA_API_URL``,
  default ``https://api.wassenger.com/v1/messages``). One token; sends free-form
  text from your connected WhatsApp device.
- ``WA_PROVIDER=meta``       + ``WA_META_TOKEN`` + ``WA_META_PHONE_ID``.
  WhatsApp Business Cloud API. Free-form text only works inside an open 24-hour
  customer session; a long-lived token comes from the Meta developer portal.
- ``WA_PROVIDER=webhook``    + ``WA_API_URL``. Posts JSON ``{phone, message}``
  with a Bearer token if ``WA_API_TOKEN`` is set (handy for any custom bridge).

Everything is best-effort and never raises: a failure behaves like the manual
fallback, never like an error.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from app.core.config import settings

logger = logging.getLogger(__name__)

# Default endpoints for the token-only providers.
WASSENGER_URL = "https://api.wassenger.com/v1/messages"
META_GRAPH_URL = "https://graph.facebook.com/v21.0"


def provider_configured() -> bool:
    provider = (settings.WA_PROVIDER or "").strip().lower()
    if provider == "wassenger":
        return bool((settings.WA_API_TOKEN or "").strip())
    if provider == "meta":
        return bool((settings.WA_META_TOKEN or "").strip() and (settings.WA_META_PHONE_ID or "").strip())
    if provider == "webhook":
        return bool((settings.WA_API_URL or "").strip())
    return False


def _digits(number: str) -> str:
    return "".join(ch for ch in number if ch.isdigit())


def _india_default(number: str) -> str:
    digits = _digits(number)
    if len(digits) == 10:
        digits = "91" + digits
    return digits


def _post_json(url: str, payload: dict[str, Any], token: str = "") -> bool:
    """POST JSON to a gateway. Returns True on a 2xx, never raises."""
    import urllib.request

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:  # noqa: S310
            return 200 <= resp.status < 300
    except Exception as e:
        logger.warning(f"WhatsApp gateway error ({url}): {e}")
        return False


def send_whatsapp(
    phone: str,
    message: str,
    log_fn: Callable[..., Any],
    sub_order_id: str = "",
) -> bool:
    """Send one WhatsApp message via the configured provider.

    ``log_fn`` is the active store's ``log_whatsapp``; the message is persisted
    first (status ``Sent``) so the Admin → WhatsApp centre shows history even
    when the message is delivered automatically. Returns True when the gateway
    accepted it (or no provider is configured → the caller keeps the Pending
    wa.me-link flow).
    """
    provider = (settings.WA_PROVIDER or "").strip().lower()
    if not provider_configured():
        return False

    number = _india_default(phone)
    if not number:
        return False

    ok = False
    if provider == "wassenger":
        ok = _post_json(
            (settings.WA_API_URL or WASSENGER_URL).rstrip("/") + "/messages",
            {"phone": number, "message": message},
            settings.WA_API_TOKEN or "",
        )
    elif provider == "meta":
        ok = _post_json(
            f"{META_GRAPH_URL}/{settings.WA_META_PHONE_ID}/messages",
            {
                "messaging_product": "whatsapp",
                "to": number,
                "type": "text",
                "text": {"body": message},
            },
            settings.WA_META_TOKEN or "",
        )
    elif provider == "webhook":
        ok = _post_json(
            settings.WA_API_URL,
            {"phone": number, "message": message},
            settings.WA_API_TOKEN or "",
        )

    if ok and log_fn is not None:
        try:
            log_fn(sub_order_id, number, message, status="Sent")
        except Exception as e:
            logger.warning(f"WhatsApp log error after send: {e}")
    return ok