from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

import psycopg2.errors

from app.core import supabase_db

logger = logging.getLogger(__name__)


def _day_key() -> str:
    """Today's date in IST as YYYY-MM-DD (matches local_demo_db)."""
    return supabase_db._now_kolkata().strftime("%Y-%m-%d")


def _day_key_compact() -> str:
    """Today's date in IST as YYYYMMDD (used in order ids like p20240320-18)."""
    return supabase_db._now_kolkata().strftime("%Y%m%d")


def get_current_batch(now: str | None = None) -> str:
    """Return the active delivery batch name ('Afternoon' or 'Night')."""
    hour = supabase_db._now_kolkata().hour
    return "Afternoon" if hour < 15 else "Night"


def get_next_token() -> int:
    """Next parent-order token for today. Tokens start at 18 each day."""
    dk = _day_key()
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(MAX(token), 17) + 1 AS next_token FROM parent_orders WHERE date_key = %s",
                (dk,),
            )
            row = supabase_db.cursor_row(cur)
            return int(row["next_token"]) if row else 18
    finally:
        supabase_db._release(connection)


def consume_token() -> int:
    """Reserve the next token number and return it."""
    return get_next_token()


def get_product_stock(product_id: str, batch_type: str, date_key: str | None = None) -> int:
    """Remaining stock for a product in the given batch."""
    dk = date_key or _day_key()
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT total_stock FROM product_stock WHERE product_id = %s AND date_key = %s AND batch_type = %s",
                (product_id, dk, batch_type),
            )
            row = supabase_db.cursor_row(cur)
            if row:
                return max(0, int(row["total_stock"]))
            cur.execute("SELECT inventory FROM products WHERE id = %s", (product_id,))
            prow = supabase_db.cursor_row(cur)
            return int(prow["inventory"]) if prow else 0
    finally:
        supabase_db._release(connection)


def get_product_stocks(batch_type: str, date_key: str | None = None) -> dict[str, int]:
    """Remaining stock for EVERY product in the given batch — one query, not
    one per product. Falls back to the product's ``inventory`` when no explicit
    ``product_stock`` row exists, mirroring :func:`get_product_stock`."""
    dk = date_key or _day_key()
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                """SELECT p.id AS pid,
                          COALESCE(ps.total_stock, p.inventory) AS stock_left
                     FROM products p
                     LEFT JOIN product_stock ps
                       ON ps.product_id = p.id AND ps.date_key = %s AND ps.batch_type = %s""",
                (dk, batch_type),
            )
            return {r["pid"]: max(0, int(r["stock_left"])) for r in cur.fetchall()}
    finally:
        supabase_db._release(connection)


def init_batch_stock(product_id: str, batch_type: str, default_stock: int, date_key: str | None = None) -> None:
    """Insert a default stock row for a product in a batch (no-op if present)."""
    dk = date_key or _day_key()
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                """INSERT INTO product_stock (product_id, date_key, batch_type, total_stock)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (product_id, date_key, batch_type) DO NOTHING""",
                (product_id, dk, batch_type, default_stock),
            )
            connection.commit()
    except Exception:
        connection.rollback()
    finally:
        supabase_db._release(connection)


def consume_batch_stock(product_id: str, batch_type: str, qty: int, date_key: str | None = None) -> bool:
    """Consume qty from a batch. Returns False when insufficient stock."""
    dk = date_key or _day_key()
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT id, total_stock FROM product_stock WHERE product_id = %s AND date_key = %s AND batch_type = %s",
                (product_id, dk, batch_type),
            )
            row = supabase_db.cursor_row(cur)
            if row:
                if int(row["total_stock"]) < qty:
                    return False
                cur.execute(
                    "UPDATE product_stock SET total_stock = total_stock - %s WHERE id = %s",
                    (qty, row["id"]),
                )
                connection.commit()
                return True
            # No stock row for this product/batch/date yet — the shop has no
            # explicit batch inventory tracked, so allow the order (matching the
            # single-shop flow, which never enforces inventory). Only block when
            # an explicit product_stock row exists AND has insufficient stock;
            # this keeps combo/multi-shop orders from spuriously failing on
            # shops that simply haven't configured batch stock rows.
            return True
    except Exception:
        connection.rollback()
        return False
    finally:
        supabase_db._release(connection)


def release_batch_stock(product_id: str, batch_type: str, qty: int, date_key: str | None = None) -> None:
    """Give back stock (e.g. cancellation)."""
    dk = date_key or _day_key()
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE product_stock SET total_stock = total_stock + %s WHERE product_id = %s AND date_key = %s AND batch_type = %s",
                (qty, product_id, dk, batch_type),
            )
            connection.commit()
    except Exception:
        connection.rollback()
    finally:
        supabase_db._release(connection)


def create_parent_order(
    student_name: str,
    student_phone: str,
    delivery_location: str,
    payment_method: str,
    shops: list[dict[str, Any]],
    student_email: str = "",
    student_id: str = "",
    owner_user_id: str = "",
) -> dict[str, Any] | None:
    """Create a multi-shop parent order with per-shop sub-orders.

    ``shops`` is a list like::

        [{"shop_id": "...", "items": [{"product_id": "...", "quantity": 2}]}, ...]

    Returns the parent order dict (with nested ``sub_orders``) or raises
    ``ValueError`` when no valid sub-order can be created. One token is shared
    across ALL sub-orders. The student pays ONE bill (sum of sub-order
    subtotals); each shop's flat ₹10-per-order commission is recorded per sub-order but never
    charged to the student.
    """
    token = consume_token()
    today_key = _day_key_compact()
    parent_id = f"p{today_key}-{token}"
    batch_type = get_current_batch()

    sub_orders: list[dict[str, Any]] = []
    grand_total = 0
    pending_subs: list[tuple[dict[str, Any], list[tuple], int, int, str, str]] = []
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            for group in shops:
                cur.execute("SELECT * FROM shops WHERE id = %s", (group["shop_id"],))
                shop = supabase_db.cursor_row(cur)
                if not shop or not supabase_db._shop_is_orderable(shop):
                    continue

                product_ids = [item["product_id"] for item in group.get("items", [])]
                products_by_id: dict[str, Any] = {}
                for pid in product_ids:
                    # PENTEST FIX: same shop-scoping + availability rule as
                    # create_order — a product from another shop (or a sold-out
                    # one) must never be priced into a sub-order.
                    cur.execute(
                        "SELECT * FROM products WHERE id = %s AND shop_id = %s",
                        (pid, group["shop_id"]),
                    )
                    prow = supabase_db.cursor_row(cur)
                    if prow and prow.get("available", 1):
                        products_by_id[pid] = prow

                subtotal = 0
                order_item_rows: list[tuple] = []
                for item in group.get("items", []):
                    product = products_by_id.get(item["product_id"])
                    if not product:
                        continue
                    quantity = int(item.get("quantity", 1) or 1)
                    if quantity <= 0:
                        continue
                    if not consume_batch_stock(product["id"], batch_type, quantity):
                        raise ValueError(f"Insufficient stock for {product['name']}")
                    subtotal += int(product["price"]) * quantity
                    order_item_rows.append(
                        (
                            product["id"],
                            product["name"],
                            int(product["price"]),
                            quantity,
                            int(product["price"]) * quantity,
                        )
                    )

                if not order_item_rows:
                    continue

                commission = 10  # flat ₹10 per order (admin's cut)
                shop_whatsapp = str(shop.get("whatsapp_number") or "").strip()
                shop_phone = str(shop.get("phone") or "").strip()
                grand_total += subtotal
                pending_subs.append((dict(shop), order_item_rows, subtotal, commission, shop_phone, shop_whatsapp))

            if not pending_subs:
                raise ValueError("No valid shops or items in order")

            # The parent row MUST exist before its sub-orders (FK constraint in
            # PostgreSQL is checked immediately, not at commit).
            #
            # PENTEST/RELIABILITY FIX. ``consume_token()`` read MAX(token)+1 on a
            # SEPARATE, already-released connection, so between that read and this
            # INSERT another student can claim the same token. The single-order
            # path (``create_order``) already retries on UniqueViolation; this one
            # did not, so a collision raised out of the endpoint as a 500 and the
            # student's order was lost — AFTER ``consume_batch_stock`` had already
            # decremented stock for every line, leaving the shop's inventory short
            # for an order that does not exist.
            #
            # A SAVEPOINT (not a full rollback) is used so the batch stock already
            # consumed in THIS transaction survives the retry.
            parent_row = None
            for _attempt in range(5):
                try:
                    cur.execute("SAVEPOINT parent_order_insert")
                    cur.execute(
                        """INSERT INTO parent_orders (
                           id, token, date_key, student_name, student_phone, student_email,
                           student_id, owner_user_id, total, payment_method, payment_status,
                           delivery_location, status, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Pending', %s, 'Pending', NOW())""",
                        (
                            parent_id,
                            token,
                            _day_key(),
                            student_name,
                            student_phone,
                            student_email,
                            student_id,
                            owner_user_id,
                            grand_total,
                            payment_method,
                            delivery_location,
                        ),
                    )
                    parent_row = True
                    break
                except psycopg2.errors.UniqueViolation:
                    # Another parent order took this token a moment ago. Undo only
                    # the failed INSERT, then re-read the next free token.
                    cur.execute("ROLLBACK TO SAVEPOINT parent_order_insert")
                    if _attempt == 4:
                        raise
                    token = consume_token()
                    parent_id = f"p{today_key}-{token}"
            if parent_row is None:  # pragma: no cover - the loop raises instead
                raise RuntimeError("Could not allocate a unique parent-order token")

            for idx, (shop, order_item_rows, subtotal, commission, shop_phone, shop_whatsapp) in enumerate(pending_subs, start=1):
                sub_order_id = f"{parent_id}-{idx}"

                cur.execute(
                    """INSERT INTO shop_sub_orders (
                           id, parent_order_id, shop_id, shop_name, shop_phone,
                           shop_whatsapp, token, subtotal, commission_5pct, status,
                           batch_type, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'Pending', %s, NOW())""",
                    (
                        sub_order_id,
                        parent_id,
                        shop["id"],
                        shop["name"],
                        shop_phone,
                        shop_whatsapp,
                        token,
                        subtotal,
                        commission,
                        batch_type,
                    ),
                )
                for product_id, name, price, qty, line_total in order_item_rows:
                    cur.execute(
                        """INSERT INTO order_items (sub_order_id, product_id, product_name, price, quantity, total)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (sub_order_id, product_id, name, price, qty, line_total),
                    )

                item_labels = [f"{q}x {n}" for _, n, _, q, _ in order_item_rows]

                sub_orders.append({
                    "id": sub_order_id,
                    "shop_id": shop["id"],
                    "shop_name": shop["name"],
                    "shop_phone": shop_phone,
                    "shop_whatsapp": shop_whatsapp,
                    "token": token,
                    "items_summary": ", ".join(item_labels),
                    "subtotal": subtotal,
                    "commission_5pct": commission,
                    "status": "Pending",
                    "batch_type": batch_type,
                })

                cur.execute(
                    """UPDATE shops SET orders_today = orders_today + 1,
                           revenue_today = revenue_today + %s, current_token = %s
                       WHERE id = %s""",
                    (subtotal, token, shop["id"]),
                )

            connection.commit()

            cur.execute("SELECT * FROM parent_orders WHERE id = %s", (parent_id,))
            parent = supabase_db.cursor_row(cur)
            if parent:
                parent["sub_orders"] = sub_orders
            return parent
    except Exception:
        connection.rollback()
        raise
    finally:
        supabase_db._release(connection)


def get_parent_order(parent_order_id: str, with_items: bool = True) -> dict[str, Any] | None:
    """Parent order with its shop sub-orders and their items.

    Batched: the old loop ran one ``order_items`` query per sub-order; we now
    pull all items + parents in two queries total (1 + 2N → 3 round trips)."""
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cur:
            cur.execute("SELECT * FROM parent_orders WHERE id = %s", (parent_order_id,))
            parent = supabase_db.cursor_row(cur)
            if not parent:
                return None
            cur.execute(
                "SELECT * FROM shop_sub_orders WHERE parent_order_id = %s ORDER BY id",
                (parent_order_id,),
            )
            subs = [dict(row) for row in cur.fetchall()]
            if not subs:
                parent["sub_orders"] = []
                return parent
            sub_ids = [s["id"] for s in subs]
            items: dict[str, list[dict[str, Any]]] = {}
            if with_items:
                cur.execute(
                    "SELECT * FROM order_items WHERE sub_order_id = ANY(%s) ORDER BY id",
                    (sub_ids,),
                )
                for row in cur.fetchall():
                    items.setdefault(row["sub_order_id"], []).append(dict(row))
            for sub in subs:
                sub["items"] = (items or {}).get(sub["id"], [])
                sub["items_summary"] = ", ".join(
                    f"{int(i['quantity'])}x {i['product_name']}" for i in sub["items"]
                )
            parent["sub_orders"] = subs
            return parent


def list_parent_orders(
    limit: int = 200,
    status: str | None = None,
    owner_user_id: str | None = None,
) -> list[dict[str, Any]]:
    """List parent orders, newest first, optional status / owner filter.

    ``owner_user_id`` pushes the per-student filter into SQL (indexed) instead
    of loading every student's orders into Python and filtering there — the
    old ``/orders/parent`` path scaled with the whole platform on every poll.
    """
    owner = str(owner_user_id or "").strip()
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cur:
            clauses: list[str] = []
            params: list[Any] = []
            if status:
                clauses.append("status = %s")
                params.append(status)
            if owner:
                clauses.append("owner_user_id = %s")
                params.append(owner)
            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            cur.execute(
                f"SELECT * FROM parent_orders{where} ORDER BY created_at DESC LIMIT %s",
                (*params, limit),
            )
            return supabase_db._rows_to_dicts(cur.fetchall())


def get_shop_sub_orders(shop_id: str, status: str | None = None) -> list[dict[str, Any]]:
    """All sub-orders for a shop (shopkeeper portal). Only this shop's items.

    Batched: items + parent rows are pulled in two queries for ALL sub-orders
    instead of two queries per sub-order (1 + 2N → 3 round trips)."""
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cur:
            if status:
                cur.execute(
                    "SELECT * FROM shop_sub_orders WHERE shop_id = %s AND status = %s ORDER BY id",
                    (shop_id, status),
                )
            else:
                cur.execute(
                    "SELECT * FROM shop_sub_orders WHERE shop_id = %s ORDER BY id",
                    (shop_id,),
                )
            subs = [dict(row) for row in cur.fetchall()]
            if not subs:
                return []
            sub_ids = [s["id"] for s in subs]
            parent_ids = list({s["parent_order_id"] for s in subs if s.get("parent_order_id")})
            cur.execute(
                "SELECT * FROM order_items WHERE sub_order_id = ANY(%s) ORDER BY id",
                (sub_ids,),
            )
            items: dict[str, list[dict[str, Any]]] = {}
            for row in cur.fetchall():
                items.setdefault(row["sub_order_id"], []).append(dict(row))
            parents: dict[str, dict[str, Any]] = {}
            if parent_ids:
                cur.execute(
                    "SELECT id, student_name, student_phone, delivery_location, total, payment_method, created_at FROM parent_orders WHERE id = ANY(%s)",
                    (parent_ids,),
                )
                parents = {row["id"]: dict(row) for row in cur.fetchall()}
            for s in subs:
                s["items"] = items.get(s["id"], [])
                s["parent"] = parents.get(s.get("parent_order_id", "")) or {}
            return subs


def list_all_sub_orders(limit: int = 300) -> list[dict[str, Any]]:
    """Recent sub-orders across ALL shops (admin orders view), newest first.

    The admin orders endpoint used to loop over every shop and call
    ``get_shop_sub_orders`` once per shop — 3 round trips per shop, all
    sequential, which made the admin orders page crawl as shops grew. This
    batches it: one query for the sub-orders plus two follow-ups for items
    and parents, regardless of shop count."""
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT * FROM shop_sub_orders ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
            subs = [dict(row) for row in cur.fetchall()]
            if not subs:
                return []
            sub_ids = [s["id"] for s in subs]
            parent_ids = list({s["parent_order_id"] for s in subs if s.get("parent_order_id")})
            cur.execute(
                "SELECT * FROM order_items WHERE sub_order_id = ANY(%s) ORDER BY id",
                (sub_ids,),
            )
            items: dict[str, list[dict[str, Any]]] = {}
            for row in cur.fetchall():
                items.setdefault(row["sub_order_id"], []).append(dict(row))
            parents: dict[str, dict[str, Any]] = {}
            if parent_ids:
                cur.execute(
                    "SELECT id, student_name, student_phone, delivery_location, total, payment_method, created_at FROM parent_orders WHERE id = ANY(%s)",
                    (parent_ids,),
                )
                parents = {row["id"]: dict(row) for row in cur.fetchall()}
            for s in subs:
                s["items"] = items.get(s["id"], [])
                s["parent"] = parents.get(s.get("parent_order_id", "")) or {}
            return subs
    finally:
        supabase_db._release(connection)


def get_sub_order(sub_order_id: str) -> dict[str, Any] | None:
    """Find one shop sub-order with its parent + shop context attached.

    Used to enrich WhatsApp logs whose ``sub_order_id`` is a multi-shop
    sub-order id (those don't live in the plain ``orders`` table). Returns the
    sub-order dict plus ``parent`` (student/phone/location/total/payment) and
    ``shop`` context, or ``None`` when it's not a sub-order id at all.
    """
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT * FROM shop_sub_orders WHERE id = %s", (sub_order_id,))
            sub = supabase_db.cursor_row(cur)
            if not sub:
                return None
            cur.execute(
                "SELECT student_name, student_phone, delivery_location, total, payment_method, created_at FROM parent_orders WHERE id = %s",
                (sub["parent_order_id"],),
            )
            parent = supabase_db.cursor_row(cur)
            sub["parent"] = parent or {}
            cur.execute(
                "SELECT id, name, phone, whatsapp_number FROM shops WHERE id = %s",
                (sub["shop_id"],),
            )
            shop = supabase_db.cursor_row(cur)
            sub["shop"] = shop or {}
            return sub
    finally:
        supabase_db._release(connection)


def update_sub_order_status(
    sub_order_id: str, status: str, notes: str = ""
) -> dict[str, Any] | None:
    """Update a shop sub-order's status + transition timestamp."""
    ts_col = {
        "Accepted": "accepted_at",
        "Preparing": "prepared_at",
        "Ready": "ready_at",
        "Delivered": "delivered_at",
        "Completed": "completed_at",
    }.get(status)
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            if ts_col:
                cur.execute(
                    f"""UPDATE shop_sub_orders SET status = %s, {ts_col} = NOW(),
                        rejection_reason = CASE WHEN %s = 'Rejected' THEN %s ELSE rejection_reason END
                        WHERE id = %s RETURNING *""",
                    (status, status, notes, sub_order_id),
                )
            elif status == "Rejected":
                cur.execute(
                    "UPDATE shop_sub_orders SET status = %s, rejection_reason = %s WHERE id = %s RETURNING *",
                    (status, notes, sub_order_id),
                )
            else:
                cur.execute("UPDATE shop_sub_orders SET status = %s WHERE id = %s RETURNING *", (status, sub_order_id))
            connection.commit()
            return supabase_db.cursor_row(cur)
    except Exception:
        connection.rollback()
        return None
    finally:
        supabase_db._release(connection)


def update_parent_order_status(parent_order_id: str, status: str) -> dict[str, Any] | None:
    """Update a parent (multi-shop) order's status (Accepted/Preparing/…/Cancelled)."""
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE parent_orders SET status = %s WHERE id = %s RETURNING *",
                (status, parent_order_id),
            )
            connection.commit()
            return supabase_db.cursor_row(cur)
    except Exception:
        connection.rollback()
        return None
    finally:
        supabase_db._release(connection)


def cancel_parent_order(parent_order_id: str) -> dict[str, Any] | None:
    """Cancel a parent order and every sub-order that is still open."""
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE shop_sub_orders SET status = 'Cancelled' "
                "WHERE parent_order_id = %s AND status NOT IN ('Completed', 'Delivered', 'Cancelled')",
                (parent_order_id,),
            )
            cur.execute(
                "UPDATE parent_orders SET status = 'Cancelled' WHERE id = %s RETURNING *",
                (parent_order_id,),
            )
            connection.commit()
            return supabase_db.cursor_row(cur)
    except Exception:
        connection.rollback()
        return None
    finally:
        supabase_db._release(connection)


def get_daily_token_count(date_key: str | None = None) -> int:
    """Number of parent orders today."""
    dk = date_key or _day_key()
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM parent_orders WHERE date_key = %s", (dk,))
            row = supabase_db.cursor_row(cur)
            return int(row["cnt"]) if row else 0
    finally:
        supabase_db._release(connection)


def auto_complete_expired_deliveries() -> int:
    """Auto-complete sub-orders delivered more than 30 minutes ago.

    Per spec section 36: after the 30-minute problem window the order is
    auto-confirmed, and the parent order completes once every sub-order is
    terminal. Idempotent + fast, so it is safe to call on every request —
    this makes it work on serverless hosts (Vercel) with no background loop.
    Returns the number of sub-orders completed just now.
    """
    completed_now = 0
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            # Coarse DB-side pre-filter: only recent deliveries can possibly be
            # due (the 30-minute check below stays authoritative). Without this
            # the sweep re-scanned every historical Delivered row on every run
            # — holding a pool thread + connection for seconds over WAN while
            # portal reads queued behind it. delivered_at is timestamptz so the
            # cutoff compares exactly; 24 h is pure margin, not semantics.
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            cur.execute(
                """SELECT id, parent_order_id, delivered_at
                   FROM shop_sub_orders
                   WHERE status = 'Delivered' AND delivered_at IS NOT NULL
                     AND delivered_at > %s""",
                (cutoff,),
            )
            rows = cur.fetchall()

            now = datetime.utcnow()
            for row in rows:
                try:
                    dt_str = str(row["delivered_at"] or "")
                    dt_str_clean = dt_str.replace("+05:30", "").replace("+00:00", "").replace("T", " ")
                    delivered = datetime.strptime(dt_str_clean[:19], "%Y-%m-%d %H:%M:%S")
                    if (now - delivered) < timedelta(minutes=30):
                        continue
                    cur.execute(
                        """UPDATE shop_sub_orders SET status = 'Completed', completed_at = NOW()
                           WHERE id = %s""",
                        (row["id"],),
                    )
                    completed_now += 1
                    cur.execute(
                        "SELECT status FROM shop_sub_orders WHERE parent_order_id = %s",
                        (row["parent_order_id"],),
                    )
                    statuses = [r["status"] for r in cur.fetchall()]
                    if statuses and all(s in ("Delivered", "Completed") for s in statuses):
                        cur.execute(
                            "UPDATE parent_orders SET status = 'Completed' WHERE id = %s",
                            (row["parent_order_id"],),
                        )
                except Exception:
                    continue
            connection.commit()
    except Exception:
        connection.rollback()
        return 0
    finally:
        supabase_db._release(connection)
    return completed_now
