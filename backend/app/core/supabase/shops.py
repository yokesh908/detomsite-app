from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

import psycopg2.errors

from app.core import supabase_db, ttl_cache

logger = logging.getLogger(__name__)


def list_shops(
    public_only: bool = False,
    search: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict[str, Any]]:
    """List shops, newest-rated first.

    ``public_only`` is applied in SQL (``WHERE approval_status = 'Approved'``)
    so the ``idx_shops_approval_status`` index is used instead of fetching the
    whole table and filtering in Python. ``limit``/``offset`` bound the payload
    as the catalogue grows; ``None`` preserves the legacy return-everything
    behaviour for existing callers.
    """
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            query = "SELECT * FROM shops"
            params: list[Any] = []
            conditions: list[str] = []
            if public_only:
                conditions.append("approval_status = 'Approved'")
            if search and search.strip():
                s = f"%{search.strip().lower()}%"
                conditions.append("(LOWER(name) LIKE %s OR LOWER(category) LIKE %s OR LOWER(description) LIKE %s)")
                params.extend([s, s, s])
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY rating DESC"
            if limit is not None:
                query += " LIMIT %s"
                params.append(max(1, min(int(limit), 500)))
                if offset:
                    query += " OFFSET %s"
                    params.append(max(0, int(offset)))
            elif offset:
                # OFFSET without LIMIT still needs a LIMIT clause in Postgres.
                query += " OFFSET %s"
                params.append(max(0, int(offset)))
            cursor.execute(query, params)
            return supabase_db._rows_to_dicts(cursor.fetchall())


def get_shop(shop_id: str) -> dict[str, Any] | None:
    cache_k = f"shop:id:{shop_id}"
    cached = ttl_cache.get(cache_k)
    if cached is not None:
        return cached

    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM shops WHERE id = %s", (shop_id,))
            row = cursor.fetchone()
            result = dict(row) if row else None
            if result is not None:
                ttl_cache.set(cache_k, result, ttl=30.0)
            return result


def get_shop_by_phone(phone: str) -> dict[str, Any] | None:
    """Find a shop by its phone number (the bank-linked number whose SMS the
    agent forwards). Matches on digits only so '+919876543210' == '9876543210'."""
    import re as _re
    digits = _re.sub(r'\D', '', phone or '')
    if not digits:
        return None
    if len(digits) == 10:
        digits = '91' + digits
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM shops WHERE approval_status = 'Approved'")
            for row in cursor.fetchall():
                shop = dict(row)
                shop_digits = _re.sub(r'\D', '', shop.get('phone') or '')
                if len(shop_digits) == 10:
                    shop_digits = '91' + shop_digits
                if shop_digits == digits:
                    return shop
    return None


def get_shop_by_shopkeeper_email(email: str) -> dict[str, Any] | None:
    """Get a vendor's shop by shopkeeper email (used by every vendor endpoint —
    avoids scanning the whole shops table on each request)."""
    cache_k = f"shop:email:{email.lower()}"
    cached = ttl_cache.get(cache_k)
    if cached is not None:
        return cached

    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM shops WHERE LOWER(shopkeeper_email) = %s ORDER BY created_at LIMIT 1",
                (email.lower(),),
            )
            row = cursor.fetchone()
            result = dict(row) if row else None
            if result is not None:
                ttl_cache.set(cache_k, result, ttl=30.0)
            return result


def create_shop(values: dict[str, Any]) -> dict[str, Any]:
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) + 1 AS next FROM shops")
            next_id = cursor.fetchone()["next"]
            shop_id = f"s{next_id}"
            cursor.execute(
                """
                INSERT INTO shops (
                    id, name, category, description, rating, opening_time,
                    closing_time, present, status, approval_status, shopkeeper_email,
                    shopkeeper_name, phone, upi_id, orders_today, revenue_today, current_token,
                    upi_enabled, cod_enabled, whatsapp_number
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    shop_id,
                    values["name"],
                    values["category"],
                    values.get("description", ""),
                    0,
                    values.get("opening_time", "09:00 AM"),
                    values.get("closing_time", "09:00 PM"),
                    False,
                    "Closed",
                    "Pending Approval",
                    values.get("shopkeeper_email", ""),
                    values["shopkeeper_name"],
                    values["phone"],
                    values.get("upi_id", ""),
                    0,
                    0,
                    18,
                    values.get("upi_enabled", True),
                    values.get("cod_enabled", True),
                    values.get("whatsapp_number", ""),
                ),
            )
            cursor.execute("SELECT * FROM shops WHERE id = %s", (shop_id,))
            row = cursor.fetchone()
            return dict(row)


def update_shop(shop_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
    """Update a shop. Self-healing: if a newer column (e.g. ``is_removed`` or
    ``admin_dues_balance``) is missing from the database, it is added
    automatically and the update is retried once."""
    try:
        return _update_shop_impl(shop_id, values)
    except psycopg2.errors.UndefinedColumn:
        logger.warning("Missing column in shops table — applying auto-migrations and retrying")
        supabase_db._apply_migrations()
        return _update_shop_impl(shop_id, values)


def _update_shop_impl(shop_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
    allowed_fields = {
        "name",
        "category",
        "description",
        "opening_time",
        "closing_time",
        "present",
        "status",
        "approval_status",
        "shopkeeper_email",
        "shopkeeper_name",
        "phone",
        "upi_id",
        "upi_enabled",
        "cod_enabled",
        "is_removed",
        "admin_dues_balance",
        "admin_dues_last_paid_at",
        "whatsapp_number",
        "ordering_position",
        "is_featured",
        "shop_image",
    }
    updates = {key: value for key, value in values.items() if key in allowed_fields and value is not None}
    if not updates:
        return get_shop(shop_id)

    if "present" in updates:
        updates["present"] = bool(updates["present"])
        # Keep the separate ``status`` field in sync (vendor UI has a single
        # Start/Stop toggle, but orderability requires status == 'Open').
        if "status" not in updates:
            updates["status"] = "Open" if updates["present"] else "Closed"

    if "approval_status" in updates and updates["approval_status"] in {"Suspended", "Removed"}:
        updates["present"] = False
        updates["status"] = "Closed"

    assignments = ", ".join(f"{field} = %s" for field in updates)
    params = [*updates.values(), shop_id]
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"UPDATE shops SET {assignments} WHERE id = %s", params)
            cursor.execute("SELECT * FROM shops WHERE id = %s", (shop_id,))
            row = cursor.fetchone()
            return dict(row) if row else None


def list_products(
    shop_id: str | None = None,
    search: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict[str, Any]]:
    """List products. ``limit``/``offset`` bound the payload (``None`` keeps the
    legacy return-everything behaviour); the ``shop_id`` path is served by
    ``idx_products_shop_id``."""
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            query = "SELECT * FROM products"
            params: list[Any] = []
            conditions = []
            if shop_id:
                conditions.append("shop_id = %s")
                params.append(shop_id)
            if search and search.strip():
                s = f"%{search.strip().lower()}%"
                conditions.append("(LOWER(name) LIKE %s OR LOWER(description) LIKE %s OR LOWER(category) LIKE %s OR LOWER(combo_items) LIKE %s)")
                params.extend([s, s, s, s])
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY category, name"
            if limit is not None:
                query += " LIMIT %s"
                params.append(max(1, min(int(limit), 500)))
                if offset:
                    query += " OFFSET %s"
                    params.append(max(0, int(offset)))
            elif offset:
                query += " OFFSET %s"
                params.append(max(0, int(offset)))
            cursor.execute(query, params)
            return supabase_db._rows_to_dicts(cursor.fetchall())


def menu_summary(keywords: list[str] | None = None) -> dict[str, Any]:
    """Per-shop menu flags for the storefront browse page, in ONE query.

    The /shops page needs, per shop, only: dish count, whether a combo exists
    (a first-class schema field), and — for keyword-driven tags like
    'Biryani & Rice' — how many dish names match client-supplied keywords.
    Fetching the whole products table for that (tens of MB at production
    scale) is what made /shops slow — this returns ~1 small row per shop
    instead. Keywords come from the caller, so no tag vocabulary is hardcoded
    here; they are length/count-bounded and passed as query params.
    """
    kws = [k.strip().lower() for k in (keywords or []) if k and k.strip()][:5]
    kws = [k[:30] for k in kws]
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            if kws:
                conds = " OR ".join(["LOWER(name) LIKE %s"] * len(kws))
                params: list[Any] = [f"%{k}%" for k in kws]
                cursor.execute(
                    f"""
                    SELECT shop_id,
                           COUNT(*) AS dishes,
                           BOOL_OR(is_combo) AS has_combo,
                           SUM(CASE WHEN {conds} THEN 1 ELSE 0 END) AS matched
                    FROM products
                    GROUP BY shop_id
                    """,
                    params,
                )
            else:
                cursor.execute(
                    """
                    SELECT shop_id,
                           COUNT(*) AS dishes,
                           BOOL_OR(is_combo) AS has_combo
                    FROM products
                    GROUP BY shop_id
                    """
                )
            shops = {}
            for row in cursor.fetchall():
                entry: dict[str, Any] = {"dishes": row["dishes"],
                                         "has_combo": bool(row["has_combo"])}
                if kws:
                    entry["matched"] = int(row["matched"] or 0)
                shops[row["shop_id"]] = entry
            total = sum(s["dishes"] for s in shops.values())
            return {"shops": shops, "total_dishes": total}


def create_product(values: dict[str, Any]) -> dict[str, Any]:
    """Create a product. Self-healing: if the database is missing a newer
    column (e.g. ``pending_price``), the migration is applied automatically
    and the insert is retried once — so vendors never hit a generic failure
    on an out-of-date Supabase schema."""
    try:
        return _create_product_impl(values)
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        logger.warning("Missing table/column in products — applying auto-migrations and retrying")
        supabase_db._apply_migrations()
        return _create_product_impl(values)


def _create_product_impl(values: dict[str, Any]) -> dict[str, Any]:
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            _product_sql = """
                INSERT INTO products (
                    id, shop_id, name, description, price, pending_price,
                    category, inventory, prep_time, available, is_combo, combo_items
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """

            def _product_params(rid):
                return (
                    rid,
                    values["shop_id"],
                    values["name"],
                    values.get("description", ""),
                    values["price"],
                    values.get("pending_price"),
                    "Combo" if values.get("is_combo") else values["category"],
                    values.get("inventory", 0),
                    values.get("prep_time", 10),
                    bool(values.get("available", True)),
                    bool(values.get("is_combo", False)),
                    str(values.get("combo_items", "") or ""),
                )

            product_id = values.get("id")
            if product_id:
                # Caller-supplied id: honour it verbatim (imports / fixtures).
                cursor.execute(_product_sql, _product_params(product_id))
            else:
                # MAX (not COUNT) so deletes can never reuse an id, AND a retry on
                # a concurrent collision (see _insert_with_suffixed_id).
                product_id = supabase_db._insert_with_suffixed_id(
                    cursor, "products", "p", _product_sql, _product_params,
                )
            cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
            row = cursor.fetchone()
            return dict(row)


def update_product(product_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
    allowed_fields = {
        "name",
        "description",
        "price",
        "pending_price",
        "category",
        "inventory",
        "prep_time",
        "available",
        "is_combo",
        "combo_items",
    }
    updates = {key: value for key, value in values.items() if key in allowed_fields and (value is not None or key == "pending_price")}
    if not updates:
        return get_product(product_id)

    if "available" in updates:
        updates["available"] = bool(updates["available"])
    if "is_combo" in updates:
        updates["is_combo"] = bool(updates["is_combo"])
        if updates["is_combo"] and "category" not in updates:
            updates["category"] = "Combo"

    assignments = ", ".join(f"{field} = %s" for field in updates)
    params = [*updates.values(), product_id]
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"UPDATE products SET {assignments} WHERE id = %s", params)
            cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
            row = cursor.fetchone()
            return dict(row) if row else None


def get_product(product_id: str) -> dict[str, Any] | None:
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
            row = cursor.fetchone()
            return dict(row) if row else None


def delete_product(product_id: str) -> bool:
    """Permanently remove a product row. Returns True when a row was deleted."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM products WHERE id = %s", (product_id,))
            return cursor.rowcount > 0


def suspend_shop(shop_id: str) -> dict[str, Any] | None:
    return update_shop(shop_id, {"approval_status": "Suspended", "present": False, "status": "Closed"})


def remove_shop(shop_id: str) -> dict[str, Any] | None:
    return update_shop(shop_id, {"approval_status": "Removed", "present": False, "status": "Closed", "is_removed": True})


def pay_admin_dues(shop_id: str, amount: int | None = None) -> dict[str, Any] | None:
    """Mark part or all of the shop's admin dues as paid."""
    shop = get_shop(shop_id)
    if not shop:
        return None
    current_balance = int(shop.get("admin_dues_balance", 0) or 0)
    pay_amount = amount if amount is not None else current_balance
    new_balance = max(0, current_balance - pay_amount)
    return update_shop(
        shop_id,
        {
            "admin_dues_balance": new_balance,
            "admin_dues_last_paid_at": datetime.now().isoformat(),
        },
    )


def record_share_payment(shop_id: str, amount: int) -> dict[str, Any] | None:
    """Record a vendor's share payment to the admin.

    When the vendor taps Pay, the UPI app opens to the admin's UPI ID. We log a
    Pending record here; the admin marks it Received once the money actually
    lands in their bank account. Returns an existing pending payment for today
    if one already exists (so tapping Pay twice doesn't double-log)."""
    try:
        return _record_share_payment_impl(shop_id, amount)
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        logger.warning("Missing share_payments table/columns — applying auto-migrations and retrying")
        supabase_db._apply_migrations()
        return _record_share_payment_impl(shop_id, amount)


def _record_share_payment_impl(shop_id: str, amount: int) -> dict[str, Any] | None:
    shop = get_shop(shop_id)
    if not shop:
        return None
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM share_payments
                WHERE shop_id = %s AND status = 'Pending'
                  AND (created_at AT TIME ZONE 'Asia/Kolkata')::date = CURRENT_DATE
                ORDER BY created_at DESC LIMIT 1
                """,
                (shop_id,),
            )
            existing = cursor.fetchone()
            if existing:
                return dict(existing)
            cursor.execute("SELECT COUNT(*) + 1 AS next FROM share_payments")
            payment_id = f"sp{cursor.fetchone()['next']}"
            cursor.execute(
                """
                INSERT INTO share_payments (id, shop_id, shop_name, amount, status)
                VALUES (%s, %s, %s, %s, 'Pending')
                """,
                (payment_id, shop_id, shop.get("name", ""), int(amount)),
            )
            cursor.execute(
                "UPDATE shops SET admin_dues_last_paid_at = now() WHERE id = %s",
                (shop_id,),
            )
            cursor.execute("SELECT * FROM share_payments WHERE id = %s", (payment_id,))
            row = cursor.fetchone()
            return dict(row) if row else None


def list_share_payments() -> list[dict[str, Any]]:
    """All vendor→admin share payments, newest first."""
    try:
        return _list_share_payments_impl()
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        supabase_db._apply_migrations()
        return _list_share_payments_impl()


def list_share_payments_by_shop(shop_id: str) -> list[dict[str, Any]]:
    """Share payments for one shop only (vendor dashboard hot path)."""
    try:
        with supabase_db._DBContext(supabase_db._connect()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM share_payments WHERE shop_id = %s ORDER BY created_at DESC",
                    (shop_id,),
                )
                return supabase_db._rows_to_dicts(cursor.fetchall())
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        supabase_db._apply_migrations()
        with supabase_db._DBContext(supabase_db._connect()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM share_payments WHERE shop_id = %s ORDER BY created_at DESC",
                    (shop_id,),
                )
                return supabase_db._rows_to_dicts(cursor.fetchall())


def _list_share_payments_impl() -> list[dict[str, Any]]:
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM share_payments ORDER BY created_at DESC")
            return supabase_db._rows_to_dicts(cursor.fetchall())


def update_share_payment_status(payment_id: str, status: str) -> dict[str, Any] | None:
    """Mark a share payment Received (Completed) or Rejected. Sets paid_at on completion."""
    try:
        return _update_share_payment_status_impl(payment_id, status)
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        supabase_db._apply_migrations()
        return _update_share_payment_status_impl(payment_id, status)


def _update_share_payment_status_impl(payment_id: str, status: str) -> dict[str, Any] | None:
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            if status == "Completed":
                cursor.execute(
                    "UPDATE share_payments SET status = %s, paid_at = now() WHERE id = %s",
                    (status, payment_id),
                )
            else:
                cursor.execute(
                    "UPDATE share_payments SET status = %s WHERE id = %s",
                    (status, payment_id),
                )
            cursor.execute("SELECT * FROM share_payments WHERE id = %s", (payment_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
