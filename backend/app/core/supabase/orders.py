from __future__ import annotations

from datetime import timedelta, timezone
import logging
from typing import Any

import psycopg2.errors

from app.core import supabase_db

logger = logging.getLogger(__name__)


def list_orders(limit: int | None = None) -> list[dict[str, Any]]:
    """All orders, newest first. ``limit`` bounds the payload — callers that
    only need the latest rows (admin dashboard, orders page) pass it so the
    response never ships the shop's entire history on every poll."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            # Newest first — created_at desc puts today's orders on top even
            # though tokens restart every day (tokens alone mix days together).
            sql = "SELECT * FROM orders ORDER BY created_at DESC, token DESC"
            params: tuple = ()
            if limit:
                sql += " LIMIT %s"
                params = (limit,)
            cursor.execute(sql, params)
            return supabase_db._rows_to_dicts(cursor.fetchall())


def list_orders_by_shop(shop_id: str) -> list[dict[str, Any]]:
    """Orders for one shop only — the vendor dashboard/history hot path. Uses
    the ``idx_orders_shop_id`` index instead of shipping every order to Python."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM orders WHERE shop_id = %s ORDER BY token DESC",
                (shop_id,),
            )
            return supabase_db._rows_to_dicts(cursor.fetchall())


def list_orders_by_user_id(
    user_id: str,
    student_name: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Orders belonging to a specific student, newest first.
    Queries by owner_user_id (indexed), with fallback to student_name for legacy rows."""
    uid = str(user_id or "").strip()
    s_name = str(student_name or "").strip()
    if not uid and not s_name:
        return []

    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            if uid and s_name:
                sql = (
                    "SELECT * FROM orders WHERE owner_user_id = %s "
                    "OR (owner_user_id = '' AND LOWER(student_name) = LOWER(%s)) "
                    "ORDER BY created_at DESC, token DESC"
                )
                params: list[Any] = [uid, s_name]
            elif uid:
                sql = (
                    "SELECT * FROM orders WHERE owner_user_id = %s "
                    "ORDER BY created_at DESC, token DESC"
                )
                params = [uid]
            else:
                sql = (
                    "SELECT * FROM orders WHERE LOWER(student_name) = LOWER(%s) "
                    "ORDER BY created_at DESC, token DESC"
                )
                params = [s_name]

            if limit:
                sql += " LIMIT %s"
                params.append(limit)

            cursor.execute(sql, tuple(params))
            return supabase_db._rows_to_dicts(cursor.fetchall())


def find_order_by_client_ref(client_ref: str, owner_user_id: str = "") -> dict[str, Any] | None:
    """Find a student's own order by the checkout idempotency key.

    ALWAYS scoped to the owning account when one is supplied: the ref is chosen
    by the client, so student B could otherwise send student A's ref and receive
    A's order (and its id) back from their own checkout.
    """
    ref = (client_ref or "").strip()
    if not ref:
        return None
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            if owner_user_id:
                cursor.execute(
                    "SELECT * FROM orders WHERE client_ref = %s AND owner_user_id = %s"
                    " ORDER BY created_at DESC LIMIT 1",
                    (ref, str(owner_user_id)),
                )
            else:
                cursor.execute(
                    "SELECT * FROM orders WHERE client_ref = %s"
                    " ORDER BY created_at DESC LIMIT 1",
                    (ref,),
                )
                return supabase_db.cursor_row(cursor)
            return supabase_db.cursor_row(cursor)


def list_recent_orders_by_shop(shop_id: str, limit: int = 250) -> list[dict[str, Any]]:
    """Latest orders for one shop (newest first) — the live feed shown in the
    vendor app. Bounded so the 30s auto-refresh never ships the shop's entire
    order history (that payload grew with every order and made the vendor app
    feel slow). Stats are still computed from the full list via
    ``list_orders_by_shop``."""
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM orders WHERE shop_id = %s ORDER BY created_at DESC LIMIT %s",
                (shop_id, limit),
            )
            return supabase_db._rows_to_dicts(cursor.fetchall())


def get_order(order_id: str) -> dict[str, Any] | None:
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
            row = cursor.fetchone()
            return dict(row) if row else None


def update_order_status(order_id: str, status: str) -> dict[str, Any] | None:
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE orders SET status = %s WHERE id = %s", (status, order_id))
            cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
            row = cursor.fetchone()
            if row:
                status_messages = {
                    "Accepted": "The shop accepted your order.",
                    "Confirmed": "Your order has been confirmed.",
                    "Preparing": "Your food is being prepared.",
                    "Ready": "Your order is ready.",
                    "Completed": "Order completed successfully.",
                    "Cancelled": "Order cancelled.",
                    "Failed": "Payment failed.",
                    "Refunded": "Order refunded.",
                }
                supabase_db.create_notification(
                    title="Order completed" if status == "Completed" else "Order status updated",
                    message=f"Token {row['token']}: {status_messages.get(status, f'Order is now {status}.')}",
                    order_id=order_id,
                    status=status,
                    target_role="student",
                )
            return dict(row) if row else None


def create_order(values: dict[str, Any]) -> dict[str, Any] | None:
    """Create an order. Self-healing: if the database is missing a newer
    column (e.g. ``payment_method``), the migration is applied automatically
    and the insert is retried once — so COD/UPI orders never fail on an
    out-of-date Supabase schema."""
    try:
        return _create_order_impl(values)
    except psycopg2.errors.UndefinedColumn:
        logger.warning("Missing column in orders table — applying auto-migrations and retrying")
        supabase_db._apply_migrations()
        return _create_order_impl(values)


def _create_order_impl(values: dict[str, Any]) -> dict[str, Any] | None:
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM shops WHERE id = %s", (values["shop_id"],))
            shop = cursor.fetchone()
            if not shop:
                return None
            if not supabase_db._shop_is_orderable(dict(shop)):
                return None

            product_ids = [item["product_id"] for item in values["items"]]
            products_by_id = {}
            for product_id in product_ids:
                # PENTEST FIX: scope to this shop and require the item to still be
                # orderable. Looking up by id alone let a student post shop A with
                # shop B's product_id (bill, kitchen and per-shop payment scoping
                # then disagreed), and let sold-out items be ordered at all.
                cursor.execute(
                    "SELECT * FROM products WHERE id = %s AND shop_id = %s",
                    (product_id, values["shop_id"]),
                )
                row = cursor.fetchone()
                if row and dict(row).get("available", 1):
                    products_by_id[product_id] = dict(row)

            subtotal = 0
            item_labels = []
            for item in values["items"]:
                product = products_by_id.get(item["product_id"])
                if not product:
                    continue
                # Quantity system removed — each cart line is one unit, so older
                # callers that send only {"product_id"} still work (default 1).
                quantity = int(item.get("quantity", 1) or 1)
                subtotal += int(product["price"]) * quantity
                # Quantity system removed — a single item reads "Masala Dosa",
                # not "1x Masala Dosa". Multi-quantity callers keep the prefix.
                item_labels.append(product["name"] if quantity <= 1 else f"{quantity}x {product['name']}")

            if not item_labels:
                return None

            # ─── Fees: the customer pays only the subtotal. The admin's ₹10 per order is
            # taken from the vendor's single-day earnings, never added to the
            # student's bill. ───
            service_fee = 0
            tax = 0
            delivery_fee = 0
            total = subtotal

            # Payment method drives the initial order status:
            #   COD     → awaiting shop acceptance
            #   UPI     → awaiting the customer's UPI payment (vendor confirms)
            #   Razorpay → paid instantly, awaiting acceptance
            payment_method = str(values.get("payment_method", "") or "").strip().upper()
            if payment_method == "COD":
                initial_status = "Pending Acceptance"
            elif payment_method == "UPI":
                initial_status = "Pending Payment"
            elif payment_method == "RAZORPAY":
                # SECURITY: a Razorpay order is only PAID once
                # ``/payments/verify-razorpay`` has verified the gateway
                # signature AND the captured amount. Starting it at
                # "Pending Acceptance" let any authenticated student POST
                # payment_method="Razorpay" and receive a fulfilled order they
                # never paid for (the vendor is SMSed the moment the order is
                # created). It must start unpaid — verification promotes it.
                initial_status = "Pending Payment"
            else:
                # Legacy callers without a payment method keep old behavior
                initial_status = "Pending Payment" if values.get("pending_payment") else "Pending Acceptance"
                payment_method = "UPI" if initial_status == "Pending Payment" else "COD"

            # ─── Order IDs: o<IST date>-<daily token> ───
            # The token restarts daily in India time (Asia/Kolkata), so the
            # "today" boundary must be IST too — using the server's CURRENT_DATE
            # (usually UTC) lets orders placed between 12:00–5:30 AM IST share a
            # token bucket with the previous day and collide on the same ID.
            today_key = supabase_db._now_kolkata().strftime("%Y%m%d")
            ist_day_start = supabase_db._now_kolkata().replace(hour=0, minute=0, second=0, microsecond=0)
            ist_day_end = ist_day_start + timedelta(days=1)

            # MAX(token)+1 read-then-insert is NOT atomic — two students placing
            # orders in the same instant can both read the same MAX and build
            # the same order id, so the second INSERT fails with the
            # "orders_pkey" unique violation. Recompute the token and retry on
            # a collision (the failed INSERT aborts the transaction, so roll
            # back before re-reading).
            row = None
            for _attempt in range(5):
                cursor.execute(
                    "SELECT COALESCE(MAX(token), 17) + 1 AS next FROM orders WHERE created_at >= %s AND created_at < %s",
                    (ist_day_start.astimezone(timezone.utc), ist_day_end.astimezone(timezone.utc)),
                )
                next_token = cursor.fetchone()["next"]
                order_id = f"o{today_key}-{next_token}"
                try:
                    cursor.execute(
                        """
                        INSERT INTO orders (
                            id, token, owner_user_id, student_name, student_phone, shop_id, shop_name,
                            items, subtotal, service_fee, tax, delivery_fee, total,
                            delivery_location, delivery_slot, status, payment_method, client_ref,
                            created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                        """,
                        (
                            order_id,
                            next_token,
                            values.get("owner_user_id", ""),
                            values.get("student_name", "Student"),
                            values.get("student_phone", ""),
                            values["shop_id"],
                            shop["name"],
                            ", ".join(item_labels),
                            subtotal,
                            service_fee,
                            tax,
                            delivery_fee,
                            total,
                            values["delivery_location"],
                            values["delivery_slot"],
                            initial_status,
                            payment_method,
                            values.get("client_ref") or None,
                        ),
                    )
                except psycopg2.errors.UniqueViolation:
                    # Another order claimed this token/id a moment ago — roll
                    # back the aborted transaction and try the next token.
                    connection.rollback()
                    if _attempt == 4:
                        raise
                    continue
                cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
                row = cursor.fetchone()
                break
            if row:
                cursor.execute(
                    """
                    UPDATE shops
                    SET orders_today = orders_today + 1,
                        revenue_today = revenue_today + %s,
                        current_token = %s
                    WHERE id = %s
                    """,
                    (total, next_token, values["shop_id"]),
                )
                supabase_db.create_notification(
                    title="Order placed",
                    message=f"Token {row['token']} is pending shop acceptance.",
                    order_id=order_id,
                    status=row["status"],
                    target_role="student",
                    connection=connection,
                )
                cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
                row = cursor.fetchone()
            return dict(row) if row else None
