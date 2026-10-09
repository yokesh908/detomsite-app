from __future__ import annotations

from typing import Any

from app.core import supabase_db, ttl_cache


def get_admin_dashboard_stats(today: str) -> dict[str, Any]:
    """Admin dashboard numbers computed in SQL.
    Optimized: single-pass FILTER aggregation on shops and orders, sargable timestamp range,
    and 10-second TTL cache for frequent polls."""
    cache_k = f"admin:dashboard_stats:{today}"
    cached = ttl_cache.get(cache_k)
    if cached is not None:
        return cached

    start_ts = f"{today} 00:00:00+05:30"
    end_ts = f"{today} 23:59:59.999999+05:30"

    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  s.total_shops,
                  s.approved_shops,
                  s.pending_approvals,
                  o.total_orders,
                  o.active_orders,
                  o.total_revenue,
                  o.today_orders,
                  o.today_revenue,
                  (SELECT COUNT(*) FROM products) AS total_products,
                  (SELECT COUNT(*) FROM payments WHERE status = 'Pending Verification') AS pending_payments
                FROM
                  (SELECT
                     COUNT(*) AS total_shops,
                     COUNT(*) FILTER (WHERE approval_status = 'Approved') AS approved_shops,
                     COUNT(*) FILTER (WHERE approval_status = 'Pending Approval') AS pending_approvals
                   FROM shops) s,
                  (SELECT
                     COUNT(*) AS total_orders,
                     COUNT(*) FILTER (WHERE status NOT IN ('Completed', 'Cancelled')) AS active_orders,
                     COALESCE(SUM(total), 0) AS total_revenue,
                     COUNT(*) FILTER (WHERE created_at >= %s::timestamptz AND created_at <= %s::timestamptz) AS today_orders,
                     COALESCE(SUM(total) FILTER (WHERE created_at >= %s::timestamptz AND created_at <= %s::timestamptz), 0) AS today_revenue
                   FROM orders) o
                """,
                (start_ts, end_ts, start_ts, end_ts),
            )
            row = cursor.fetchone()
            result = dict(row) if row else {}
            if result:
                ttl_cache.set(cache_k, result, ttl=10.0)
            return result


def get_orders_grouped_by_date() -> list[dict[str, Any]]:
    """Get orders grouped by date for revenue tracking."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT created_at::date::text AS created_at, COUNT(*) AS count, SUM(total) AS revenue, "
                "SUM(subtotal) AS subtotal, COUNT(*) * 10 AS service_fee, "
                "SUM(tax) AS tax, SUM(delivery_fee) AS delivery_fee, "
                "STRING_AGG(id, ',') AS ids FROM orders GROUP BY created_at::date ORDER BY created_at::date DESC"
            )
            return supabase_db._rows_to_dicts(cursor.fetchall())


def get_orders_by_date(date_key: str) -> list[dict[str, Any]]:
    """Get orders for a specific date (YYYY-MM-DD) for daily log filtering."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM orders WHERE created_at::date = %s::date ORDER BY token DESC",
                (date_key,),
            )
            return supabase_db._rows_to_dicts(cursor.fetchall())


def get_payments_by_date(date_key: str) -> list[dict[str, Any]]:
    """Get payments for a specific date (YYYY-MM-DD) for daily log filtering."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM payments WHERE created_at::date = %s::date ORDER BY created_at DESC",
                (date_key,),
            )
            return supabase_db._rows_to_dicts(cursor.fetchall())


def get_daily_stats() -> dict[str, Any]:
    """Get today's statistics."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS count, COALESCE(SUM(total), 0) AS revenue, "
                "COUNT(*) * 10 AS service_fee FROM orders WHERE created_at::date = CURRENT_DATE"
            )
            today_orders = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) AS count FROM users")
            total_users = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) AS count FROM shops WHERE approval_status = 'Approved'")
            total_shops = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) AS count FROM orders")
            total_orders = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) * 10 AS total FROM orders")
            total_service_fee = cursor.fetchone()
            return {
                "today_orders": dict(today_orders) if today_orders else {"count": 0, "revenue": 0, "service_fee": 0},
                "total_users": dict(total_users)["count"] if total_users else 0,
                "approved_shops": dict(total_shops)["count"] if total_shops else 0,
                "total_orders": dict(total_orders)["count"] if total_orders else 0,
                "total_service_fee": dict(total_service_fee)["total"] if total_service_fee else 0,
            }


def get_vendor_daily_logs(shop_id: str) -> list[dict[str, Any]]:
    """Per-day earnings + order counts for one shop (admin vendor logs)."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT created_at::date::text AS created_at, COUNT(*) AS count,
                       SUM(total) AS revenue, COUNT(*) * 10 AS admin_fee
                FROM orders WHERE shop_id = %s
                GROUP BY created_at::date ORDER BY created_at::date DESC
                """,
                (shop_id,),
            )
            return supabase_db._rows_to_dicts(cursor.fetchall())


def get_vendor_orders(shop_id: str) -> list[dict[str, Any]]:
    """All orders for one shop (admin vendor logs)."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM orders WHERE shop_id = %s ORDER BY created_at DESC",
                (shop_id,),
            )
            return supabase_db._rows_to_dicts(cursor.fetchall())


def get_summary() -> dict[str, Any]:
    """Aggregate summary computed with COUNT/SUM SQL so the DB ships a single
    tiny row instead of every shop/product/order row across the wire.

    The old version loaded ``shops``, ``orders`` and ``products`` in full, then
    counted in Python — ~800 ms of cold latency on a live Supabase project.
    This version runs three COUNT/SUM queries and returns immediately."""
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE status = 'Open') AS open_n "
                "FROM shops"
            )
            row = supabase_db.cursor_row(cur)
            shop_count = row["n"] if row else 0
            open_shop_count = row["open_n"] if row else 0

            cur.execute(
                "SELECT COUNT(*) AS active, COALESCE(SUM(total), 0) AS revenue "
                "FROM orders WHERE status != 'Completed'"
            )
            row = supabase_db.cursor_row(cur)
            active_orders = row["active"] if row else 0
            revenue = row["revenue"] if row else 0

            # The alias is NOT cosmetic: psycopg2 reports an unaliased COUNT(*)
            # under the column name "count", so reading row["COUNT(*)"] raised
            # KeyError and the endpoint answered 500 (an admin-only route, and
            # the pentest sweep asserts it answers an admin). The SQLite demo
            # store used by the tests keeps the literal "COUNT(*)" name and reads
            # it positionally, so only the production Supabase path could fail.
            cur.execute("SELECT COUNT(*) AS n FROM products")
            row = supabase_db.cursor_row(cur)
            product_count = row["n"] if row else 0

        return {
            "shops": shop_count,
            "orderable_shops": open_shop_count,
            "products": product_count,
            "active_orders": active_orders,
            "revenue": revenue,
            "token_starts_at": 18,
        }
    finally:
        supabase_db._release(connection)
