from __future__ import annotations

import logging
from typing import Any

import psycopg2.errors

from app.core import supabase_db

logger = logging.getLogger(__name__)

_PROOF_SUBMITTED = "PAYMENT_PROOF_SUBMITTED"
_PROOF_APPROVED = "PAYMENT_APPROVED"
_PROOF_REJECTED = "PAYMENT_REJECTED"


def create_payment(
    order_id: str,
    amount: int,
    method: str,
    utr_number: str | None = None,
    screenshot_name: str | None = None,
    allow_unknown_order: bool = False,
) -> dict[str, Any] | None:
    """Record a payment. ``order_id`` is normally a row in ``orders`` — multi-
    shop parents are recorded via ``record_parent_payment`` instead (the
    ``payments.order_id`` FK only accepts ``orders`` rows, so parent orders can
    never live here)."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            if not allow_unknown_order:
                cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
                if not cursor.fetchone():
                    return None
            # COUNT(*)+1 read-then-insert is not atomic under concurrency — if
            # another payment claimed the same id a moment ago, retry with a
            # freshly computed one instead of failing with a duplicate key.
            status = "Pending" if method in ("Manual UTR", "UPI") else "Success"
            row = None
            for _attempt in range(5):
                cursor.execute("SELECT COUNT(*) + 1 AS next FROM payments")
                payment_id = f"pay{cursor.fetchone()['next']}"
                try:
                    cursor.execute(
                        """
                        INSERT INTO payments (id, order_id, amount, method, status, utr_number, screenshot_name)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (payment_id, order_id, amount, method, status, utr_number, screenshot_name),
                    )
                except psycopg2.errors.UniqueViolation:
                    connection.rollback()
                    if _attempt == 4:
                        raise
                    continue
                cursor.execute("SELECT * FROM payments WHERE id = %s", (payment_id,))
                row = cursor.fetchone()
                break
            return dict(row) if row else None


def list_payments() -> list[dict[str, Any]]:
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM payments ORDER BY created_at DESC")
            return supabase_db._rows_to_dicts(cursor.fetchall())


def get_payment_by_id(payment_id: str) -> dict[str, Any] | None:
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM payments WHERE id = %s", (payment_id,))
            row = cursor.fetchone()
            return dict(row) if row else None


def _parent_payment_shape(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "order_id": row["id"],
        "amount": row["total"],
        "method": row["payment_method"],
        "status": "Success" if str(row.get("payment_status") or "").upper() == "PAID" else row.get("payment_status", "Pending"),
        "proof_status": row.get("payment_proof_status") or "PENDING_PAYMENT",
        "utr_number": row.get("utr_number"),
        "screenshot_name": row.get("screenshot_name"),
        "payment_screenshot_url": row.get("payment_screenshot_url") or "",
        "payment_screenshot_public_id": row.get("payment_screenshot_public_id") or "",
        "payment_submitted_at": str(row.get("payment_submitted_at") or ""),
        "payment_verified_at": str(row.get("payment_verified_at") or ""),
        "payment_verified_by": row.get("payment_verified_by") or "",
        "payment_rejection_reason": row.get("payment_rejection_reason") or "",
        "created_at": str(row.get("created_at") or ""),
        "is_parent": True,
    }


def record_parent_payment(
    parent_order_id: str,
    amount: int,
    method: str,
    utr_number: str | None = None,
    screenshot_name: str | None = None,
) -> dict[str, Any] | None:
    """Create/refresh the payment proof (UTR + screenshot) for a parent order."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM parent_orders WHERE id = %s", (parent_order_id,))
            parent = supabase_db.cursor_row(cursor)
            if not parent:
                return None
            cursor.execute(
                """UPDATE parent_orders
                   SET payment_method = COALESCE(%s, payment_method),
                       utr_number = COALESCE(%s, utr_number),
                       screenshot_name = COALESCE(%s, screenshot_name)
                   WHERE id = %s""",
                (method, utr_number, screenshot_name, parent_order_id),
            )
            cursor.execute("SELECT * FROM parent_orders WHERE id = %s", (parent_order_id,))
            parent = supabase_db.cursor_row(cursor)
            return _parent_payment_shape(parent) if parent else None


def get_parent_payment(parent_order_id: str) -> dict[str, Any] | None:
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM parent_orders WHERE id = %s", (parent_order_id,))
            row = supabase_db.cursor_row(cursor)
            return _parent_payment_shape(row) if row else None


def list_parent_payments() -> list[dict[str, Any]]:
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM parent_orders ORDER BY created_at DESC")
            return [_parent_payment_shape(dict(r)) for r in cursor.fetchall()]


def verify_parent_payment(parent_order_id: str, status: str) -> dict[str, Any] | None:
    """Verify/reject a parent group's UPI/UTR proof. On success the whole group
    moves to Pending Acceptance and every pending sub-order is Accepted."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            if str(status).lower() in ("success", "verified", "received"):
                cursor.execute("SELECT token, status FROM parent_orders WHERE id = %s", (parent_order_id,))
                prow = supabase_db.cursor_row(cursor)
                if not prow:
                    return None
                cursor.execute("UPDATE parent_orders SET payment_status = 'Paid' WHERE id = %s", (parent_order_id,))
                if prow["status"] == "Pending":
                    cursor.execute("UPDATE parent_orders SET status = 'Pending Acceptance' WHERE id = %s", (parent_order_id,))
                cursor.execute(
                    "UPDATE shop_sub_orders SET status = 'Accepted' WHERE parent_order_id = %s AND status = 'Pending'",
                    (parent_order_id,),
                )
                supabase_db.create_notification(
                    title="Payment confirmed",
                    message=f"Payment for token {prow['token']} confirmed — the shops will accept your order soon.",
                    order_id=None,  # notifications.order_id FK only accepts `orders` ids
                    status="Pending Acceptance",
                    target_role="student",
                    connection=connection,
                )
            else:
                cursor.execute("SELECT id FROM parent_orders WHERE id = %s", (parent_order_id,))
                if not supabase_db.cursor_row(cursor):
                    return None
                cursor.execute("UPDATE parent_orders SET payment_status = 'Failed' WHERE id = %s", (parent_order_id,))
            cursor.execute("SELECT * FROM parent_orders WHERE id = %s", (parent_order_id,))
            row = supabase_db.cursor_row(cursor)
            return _parent_payment_shape(row) if row else None


def update_payment_status(payment_id: str, status: str) -> dict[str, Any] | None:
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE payments SET status = %s WHERE id = %s", (status, payment_id))
            cursor.execute("SELECT * FROM payments WHERE id = %s", (payment_id,))
            row = cursor.fetchone()
            if row and status in ("Success", "Failed"):
                is_parent = bool(row.get("parent_order_id"))
                if is_parent:
                    # Multi-shop: ONE bill → entire group moves together.
                    parent_id = row["parent_order_id"]
                    if status == "Success":
                        cursor.execute(
                            "UPDATE parent_orders SET payment_status = 'Paid' WHERE id = %s",
                            (parent_id,),
                        )
                        cursor.execute("SELECT token, status FROM parent_orders WHERE id = %s", (parent_id,))
                        p_row = cursor.fetchone()
                        if p_row and p_row["status"] == "Pending":
                            cursor.execute(
                                "UPDATE parent_orders SET status = 'Pending Acceptance' WHERE id = %s",
                                (parent_id,),
                            )
                        cursor.execute(
                            "UPDATE shop_sub_orders SET status = 'Accepted' WHERE parent_order_id = %s AND status = 'Pending'",
                            (parent_id,),
                        )
                        supabase_db.create_notification(
                            title="Payment confirmed",
                            message=f"Payment for token {p_row['token'] if p_row else parent_id} confirmed — the shops will accept your order soon.",
                            order_id=None,  # notifications.order_id FK only accepts `orders` ids
                            status="Pending Acceptance",
                            target_role="student",
                            connection=connection,
                        )
                    else:
                        cursor.execute(
                            "UPDATE parent_orders SET payment_status = 'Failed' WHERE id = %s",
                            (parent_id,),
                        )
                else:
                    order_id = row["order_id"]
                    cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
                    order_row = cursor.fetchone()
                    if order_row:
                        if status == "Success":
                            cursor.execute("UPDATE orders SET status = %s WHERE id = %s", ("Pending Acceptance", order_row["id"]))
                            supabase_db.create_notification(
                                title="Payment confirmed",
                                message=f"Payment for token {order_row['token']} confirmed — the shop will accept your order soon.",
                                order_id=order_row["id"],
                                status="Pending Acceptance",
                                target_role="student",
                                connection=connection,
                            )
                        else:
                            cursor.execute("UPDATE orders SET status = %s WHERE id = %s", ("Failed", order_row["id"]))
            return dict(row) if row else None


def save_single_payment_proof(
    order_id: str,
    amount: int,
    utr_number: str,
    screenshot_url: str,
    screenshot_public_id: str,
) -> dict[str, Any] | None:
    """Attach (or refresh) a UTR + screenshot proof on a single-shop order.

    Reuses the order's open payment row when one exists, otherwise inserts a
    fresh one. Legacy ``status`` is kept in sync ('Pending Verification').
    Returns None when the order does not exist.
    """
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
            if not cursor.fetchone():
                return None
            cursor.execute(
                "SELECT * FROM payments WHERE order_id = %s ORDER BY created_at DESC, id DESC LIMIT 1",
                (order_id,),
            )
            row = cursor.fetchone()
            if row:
                cursor.execute(
                    """UPDATE payments
                       SET amount = %s, method = 'Manual UTR', utr_number = %s,
                           proof_status = 'PAYMENT_PROOF_SUBMITTED', status = 'Pending Verification',
                           payment_screenshot_url = %s, payment_screenshot_public_id = %s,
                           payment_submitted_at = now(),
                           payment_verified_at = NULL, payment_verified_by = '',
                           payment_rejection_reason = ''
                       WHERE id = %s""",
                    (amount, utr_number, screenshot_url, screenshot_public_id, row["id"]),
                )
                payment_id = row["id"]
            else:
                cursor.execute("SELECT COUNT(*) + 1 AS next FROM payments")
                payment_id = f"pay{cursor.fetchone()['next']}"
                try:
                    cursor.execute(
                        """INSERT INTO payments (id, order_id, amount, method, status,
                                                utr_number, proof_status, payment_screenshot_url,
                                                payment_screenshot_public_id, payment_submitted_at)
                           VALUES (%s, %s, %s, 'Manual UTR', 'Pending Verification',
                                   %s, 'PAYMENT_PROOF_SUBMITTED', %s, %s, now())""",
                        (payment_id, order_id, amount, utr_number, screenshot_url, screenshot_public_id),
                    )
                except psycopg2.errors.UniqueViolation:
                    connection.rollback()
                    return None
            cursor.execute("SELECT * FROM payments WHERE id = %s", (payment_id,))
            saved = cursor.fetchone()
            return dict(saved) if saved else None


def save_parent_payment_proof(
    parent_order_id: str,
    amount: int,
    utr_number: str,
    screenshot_url: str,
    screenshot_public_id: str,
) -> dict[str, Any] | None:
    """Attach (or refresh) a UTR + screenshot proof on a multi-shop parent bill."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM parent_orders WHERE id = %s", (parent_order_id,))
            parent = supabase_db.cursor_row(cursor)
            if not parent:
                return None
            cursor.execute(
                """UPDATE parent_orders
                   SET payment_method = 'Manual UTR',
                       payment_status = 'Pending',
                       payment_proof_status = 'PAYMENT_PROOF_SUBMITTED',
                       utr_number = %s,
                       payment_screenshot_url = %s,
                       payment_screenshot_public_id = %s,
                       payment_submitted_at = now(),
                       payment_verified_at = NULL,
                       payment_verified_by = '',
                       payment_rejection_reason = ''
                   WHERE id = %s""",
                (utr_number, screenshot_url, screenshot_public_id, parent_order_id),
            )
            cursor.execute("SELECT * FROM parent_orders WHERE id = %s", (parent_order_id,))
            updated = supabase_db.cursor_row(cursor)
            return _parent_payment_shape(updated) if updated else None


def verify_single_payment_proof(
    payment_id: str, approved: bool, admin_name: str, reason: str = ""
) -> dict[str, Any] | None:
    """Admin approve/reject of a single-order proof. Approval moves the order
    to Pending Acceptance (normal pipeline resumes) + notifies the student;
    rejection leaves the order awaiting payment so the student can resubmit."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM payments WHERE id = %s", (payment_id,))
            row = cursor.fetchone()
            if not row:
                return None
            proof = _PROOF_APPROVED if approved else _PROOF_REJECTED
            legacy = "Success" if approved else "Rejected"
            cursor.execute(
                    """UPDATE payments
                       SET proof_status = %s, status = %s, payment_verified_at = now(),
                           payment_verified_by = %s, payment_rejection_reason = %s
                       WHERE id = %s""",
                (proof, legacy, admin_name[:100], (reason or "")[:500], payment_id),
            )
            order_id = row["order_id"]
            cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
            order_row = cursor.fetchone()
            if order_row and approved:
                if str(order_row["status"]) in ("Pending", "Pending Payment", "Pending Acceptance"):
                    cursor.execute("UPDATE orders SET status = %s WHERE id = %s", ("Pending Acceptance", order_row["id"]))
                supabase_db.create_notification(
                    title="Payment verified",
                    message=f"Payment for token {order_row['token']} is verified — the shop will accept your order soon.",
                    order_id=order_row["id"],
                    status="Pending Acceptance",
                    target_role="student",
                    connection=connection,
                )
            elif order_row and not approved:
                supabase_db.create_notification(
                    title="Payment rejected",
                    message=(
                        f"Payment proof for token {order_row['token']} was rejected"
                        + (f": {reason[:200]}" if (reason or "").strip() else "")
                        + ". Please submit a fresh UTR + screenshot."
                    ),
                    order_id=order_row["id"],
                    status=str(order_row["status"]),
                    target_role="student",
                    connection=connection,
                )
            cursor.execute("SELECT * FROM payments WHERE id = %s", (payment_id,))
            saved = cursor.fetchone()
            return dict(saved) if saved else None


def verify_parent_payment_proof(
    parent_order_id: str, approved: bool, admin_name: str, reason: str = ""
) -> dict[str, Any] | None:
    """Admin approve/reject of a multi-shop parent proof (mirrors
    verify_parent_payment, plus proof columns + student notification)."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM parent_orders WHERE id = %s", (parent_order_id,))
            parent = supabase_db.cursor_row(cursor)
            if not parent:
                return None
            proof = _PROOF_APPROVED if approved else _PROOF_REJECTED
            legacy = "Paid" if approved else "Failed"
            cursor.execute(
                """UPDATE parent_orders
                   SET payment_proof_status = %s, payment_status = %s,
                       payment_verified_at = now(), payment_verified_by = %s,
                       payment_rejection_reason = %s
                   WHERE id = %s""",
                (proof, legacy, admin_name[:100], (reason or "")[:500], parent_order_id),
            )
            if approved:
                if parent["status"] == "Pending":
                    cursor.execute("UPDATE parent_orders SET status = 'Pending Acceptance' WHERE id = %s", (parent_order_id,))
                cursor.execute(
                    "UPDATE shop_sub_orders SET status = 'Accepted' WHERE parent_order_id = %s AND status = 'Pending'",
                    (parent_order_id,),
                )
                supabase_db.create_notification(
                    title="Payment verified",
                    message=f"Payment for token {parent['token']} is verified — the shops will accept your order soon.",
                    order_id=None,
                    status="Pending Acceptance",
                    target_role="student",
                    connection=connection,
                )
            else:
                supabase_db.create_notification(
                    title="Payment rejected",
                    message=(
                        f"Payment proof for token {parent['token']} was rejected"
                        + (f": {reason[:200]}" if (reason or "").strip() else "")
                        + ". Please submit a fresh UTR + screenshot."
                    ),
                    order_id=None,
                    status=str(parent.get("status") or "Pending"),
                    target_role="student",
                    connection=connection,
                )
            cursor.execute("SELECT * FROM parent_orders WHERE id = %s", (parent_order_id,))
            updated = supabase_db.cursor_row(cursor)
            return _parent_payment_shape(updated) if updated else None


def get_payment_by_order_id(order_id: str) -> dict[str, Any] | None:
    """Get the most recent payment record for an order. For multi-shop parents
    the payment is anchored on a sub-order id but keeps ``parent_order_id`` —
    so lookups by the parent id match too."""
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM payments WHERE order_id = %s ORDER BY created_at DESC, id DESC LIMIT 1",
                (order_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None


def get_payments_map_by_order_ids(order_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Batch fetch latest payment records for a list of order IDs in ONE query.
    Eliminates N+1 query loops across order list and dashboard routes."""
    if not order_ids:
        return {}
    clean_ids = list({str(oid).strip() for oid in order_ids if oid})
    if not clean_ids:
        return {}
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT ON (order_id) id, order_id, parent_order_id, method, status, utr_number, amount, created_at
                FROM payments
                WHERE order_id = ANY(%s) OR parent_order_id = ANY(%s)
                ORDER BY order_id, created_at DESC, id DESC
                """,
                (clean_ids, clean_ids),
            )
            rows = cursor.fetchall()
            result: dict[str, dict[str, Any]] = {}
            for r in rows:
                d = dict(r)
                if d.get("order_id"):
                    result[d["order_id"]] = d
                if d.get("parent_order_id"):
                    result[d["parent_order_id"]] = d
            return result


def set_payment_utr(order_id: str, utr_number: str) -> dict[str, Any] | None:
    """Stamp the student-provided UTR on the latest payment for an order."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM payments WHERE order_id = %s ORDER BY created_at DESC, id DESC LIMIT 1",
                (order_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            cursor.execute(
                "UPDATE payments SET utr_number = %s WHERE id = %s",
                (utr_number, row["id"]),
            )
            cursor.execute("SELECT * FROM payments WHERE id = %s", (row["id"],))
            updated = cursor.fetchone()
            return dict(updated) if updated else None


def get_payment_by_utr(utr_number: str) -> dict[str, Any] | None:
    """Find the most recent payment record carrying this UTR (student-entered)."""
    if not utr_number:
        return None
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM payments WHERE utr_number = %s ORDER BY created_at DESC, id DESC LIMIT 1",
                (utr_number,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None


def list_payments_by_utr(utr_number: str) -> list[dict[str, Any]]:
    """Indexed UTR lookup for /sms/match Tier-1 duplicate detection.

    Uses the partial unique index on payments(utr_number) instead of the
    full-table ``list_payments()`` scan, so concurrent bank credits cost one
    indexed read no matter how large the table grows.
    """
    if not utr_number:
        return []
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM payments WHERE utr_number = %s ORDER BY created_at DESC, id DESC",
                (utr_number,),
            )
            return supabase_db._rows_to_dicts(cursor.fetchall())


def settle_payment_if_open(payment_id: str) -> dict[str, Any] | None:
    """Atomically flip a payment to Success only if it is still open.

    Single-statement conditional UPDATE (Postgres executes it atomically and
    holds the row lock to COMMIT — see Postgres UPDATE + RETURNING docs): two
    concurrent credits racing on the same payment serialize here, the loser
    gets zero rows back (None) instead of double-settling. Returns the settled
    row, or None when it was already Success/Cancelled/Failed/Rejected.
    """
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """UPDATE payments SET status = 'Success'
                   WHERE id = %s AND status NOT IN ('Success','Cancelled','Failed','Rejected')
                   RETURNING *""",
                (payment_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None


def get_payment_settings() -> dict[str, Any]:
    defaults = {
        "manual_enabled": False,
        "upi_id": "",
        "receiver_name": "",
        "instructions": "",
        "razorpay_enabled": False,
    }
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT key, value FROM app_settings")
            values = {row["key"]: row["value"] for row in cursor.fetchall()}
    return {
        "manual_enabled": values.get("manual_enabled", "false") == "true",
        "upi_id": values.get("upi_id", defaults["upi_id"]),
        "receiver_name": values.get("receiver_name", defaults["receiver_name"]),
        "instructions": values.get("instructions", defaults["instructions"]),
        "razorpay_enabled": values.get("razorpay_enabled", "false") == "true",
    }


def update_payment_settings(values: dict[str, Any]) -> dict[str, Any]:
    allowed = {"manual_enabled", "upi_id", "receiver_name", "instructions", "razorpay_enabled"}
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            for key, value in values.items():
                if key not in allowed or value is None:
                    continue
                stored_value = str(value).lower() if isinstance(value, bool) else str(value)
                cursor.execute(
                    "INSERT INTO app_settings (key, value) VALUES (%s, %s) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
                    (key, stored_value),
                )
    return get_payment_settings()


def get_student_notice() -> dict[str, Any]:
    """The info block students see on their home page, edited from the Admin
    Centre. Stored in the shared ``app_settings`` key/value table so no new
    table (or migration) is needed:

    * ``student_notice_enabled`` — "true" / "false"
    * ``student_notice_text``    — the message the student reads

    An empty message can never render, so ``enabled`` is reported as False
    whenever the text is blank — the admin can't leave a blank green block on
    the student app by accident.
    """
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT key, value FROM app_settings "
                "WHERE key IN ('student_notice_text', 'student_notice_enabled')"
            )
            values = {row["key"]: row["value"] for row in cursor.fetchall()}
    text = str(values.get("student_notice_text", "") or "").strip()
    return {
        "enabled": values.get("student_notice_enabled", "false") == "true" and bool(text),
        "text": text,
    }


def update_student_notice(values: dict[str, Any]) -> dict[str, Any]:
    """Save the student info notice (admin only — see the local API routes)."""
    columns = {"enabled": "student_notice_enabled", "text": "student_notice_text"}
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            for field, key in columns.items():
                if field not in values or values[field] is None:
                    continue
                value = values[field]
                stored_value = ("true" if value else "false") if isinstance(value, bool) else str(value)
                cursor.execute(
                    "INSERT INTO app_settings (key, value) VALUES (%s, %s) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
                    (key, stored_value),
                )
    return get_student_notice()


def bank_sms_seen(utr: str) -> bool:
    """True when a bank credit SMS containing this UTR was already logged inbound.

    This is the security anchor for the double-confirm flow: an order only
    auto-confirms via a student-entered UTR if the bank's SMS (proving the
    money actually arrived) was received too.
    """
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM sms_logs WHERE direction = 'in' AND status = 'UTR Received' "
                "AND UPPER(message) LIKE %s LIMIT 1",
                (f"%{utr}%",),
            )
            return cur.fetchone() is not None
    finally:
        supabase_db._release(connection)
