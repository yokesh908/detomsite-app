"""
Supabase (Postgres) data store for DETOMSITE.

Mirrors the function signatures of ``local_demo_db`` so the API layer can switch
between SQLite (dev) and Supabase Postgres (production) via the ``store`` facade
without any other code changes.

Connect using either ``SUPABASE_DATABASE_URL`` (a full Postgres connection
string) or the individual ``SUPABASE_DB_*`` settings.

Run the schema from ``backend/supabase/schema.sql`` in the Supabase SQL editor before
using this store.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any


# Asia/Kolkata fixed offset (works even without the tzdata package)
_KOLKATA_TZ = timezone(timedelta(hours=5, minutes=30))


def _now_kolkata() -> datetime:
    return datetime.now(_KOLKATA_TZ)

import psycopg2
import psycopg2.extras
from psycopg2 import pool as _pg_pool

from app.core.config import settings

logger = logging.getLogger(__name__)


def _connection_string() -> str:
    if settings.SUPABASE_DATABASE_URL:
        return settings.SUPABASE_DATABASE_URL
    return (
        f"postgresql://{settings.SUPABASE_DB_USER}:{settings.SUPABASE_DB_PASSWORD}"
        f"@{settings.SUPABASE_DB_HOST}:{settings.SUPABASE_DB_PORT}/{settings.SUPABASE_DB_NAME}"
    )


# ─── Connection pool ────────────────────────────────────────────────────
# Opening a brand-new Postgres connection for every request is slow (each one
# needs a TCP + TLS handshake across regions). We keep a small pool of warm
# connections and reuse them, which makes the site feel much snappier.
_pool: Any = None


def _get_pool() -> Any:
    """Lazily create the shared connection pool (thread-safe)."""
    global _pool
    if _pool is None:
        _pool = _pg_pool.ThreadedConnectionPool(
            1, 15, _connection_string(),
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
    return _pool


def _connect() -> Any:
    """Get a pooled Postgres connection with dict-row support."""
    conn = _get_pool().getconn()
    if getattr(conn, "closed", 0) != 0:
        # Stale pooled connection — return its slot (rebuilds the pool) and
        # ask for a fresh one, so the slot is never leaked.
        _release(conn, discard=True)
        conn = _get_pool().getconn()
    return conn


def _release(conn: Any, discard: bool = False) -> None:
    """Return a connection to the pool. If it broke (or ``discard=True``),
    rebuild the pool so the next connections are healthy."""
    global _pool
    if discard:
        try:
            conn.close()
        except Exception:
            pass
        _rebuild_pool()
        return
    try:
        if getattr(conn, "closed", 1) == 0:
            _get_pool().putconn(conn)
            return
    except Exception:
        pass
    # Connection is dead — rebuild the pool so new connections are healthy.
    _rebuild_pool()


def _rebuild_pool() -> None:
    """Close and drop the current pool (if any). New connections will be
    created lazily by the next ``_get_pool()`` call."""
    global _pool
    old_pool = _pool
    _pool = None  # clear first so concurrent callers build a fresh pool
    try:
        if old_pool is not None:
            old_pool.closeall()
    except Exception:
        pass


class _DBContext:
    """Context manager: commits on success, rolls back on error, returns the
    connection to the pool on exit."""

    def __init__(self, connection: Any):
        self._connection = connection

    def __enter__(self) -> Any:
        return self._connection

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is None:
            self._connection.commit()
            _release(self._connection)
            return False
        try:
            self._connection.rollback()
            _release(self._connection)
        except Exception:
            # Rollback failed → the connection itself is broken. Discard it so
            # the pool rebuilds with healthy connections.
            _release(self._connection, discard=True)
        return False


def _rows_to_dicts(rows: list) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def cursor_row(cursor) -> dict[str, Any] | None:
    """Return the next row from a cursor as a dict, or None."""
    row = cursor.fetchone()
    return dict(row) if row else None


def cursor_row_as_dict(cursor) -> dict[str, Any] | None:
    """Alias for cursor_row — return next row as dict or None."""
    return cursor_row(cursor)





def _shop_is_orderable(shop: dict[str, Any]) -> bool:
    # The vendor's Start/Stop toggle (present + status) is the single source of
    # truth for whether a shop accepts orders. opening/closing hours are shown
    # to students as information only and do NOT block ordering — otherwise a
    # vendor who presses "Start" outside the default hours would stay closed.
    return (
        shop["approval_status"] == "Approved"
        and bool(shop["present"])
        and shop["status"] == "Open"
    )


# ─── Auto-migrations ─────────────────────────────────────────────────────
# New columns added to the schema after the database was first created.
# Re-applied on every startup AND re-applied automatically if a query ever
# fails with a missing-column error (self-healing) — so the app never breaks
# on a database that hasn't had the latest schema.sql run against it.
_MIGRATIONS = [
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method text NOT NULL DEFAULT 'UPI'",
    "ALTER TABLE shops ADD COLUMN IF NOT EXISTS is_removed boolean NOT NULL DEFAULT false",
    "ALTER TABLE shops ADD COLUMN IF NOT EXISTS admin_dues_balance integer NOT NULL DEFAULT 0",
    "ALTER TABLE shops ADD COLUMN IF NOT EXISTS admin_dues_last_paid_at timestamptz",
    "ALTER TABLE shops ADD COLUMN IF NOT EXISTS upi_enabled boolean NOT NULL DEFAULT true",
    "ALTER TABLE shops ADD COLUMN IF NOT EXISTS cod_enabled boolean NOT NULL DEFAULT true",
    # Older product tables may be missing the pending_price column — without this
    # the vendor's "Add Product" fails in production (500) while local SQLite
    # works (local auto-creates the schema on startup).
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS pending_price integer",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS prep_time integer NOT NULL DEFAULT 10",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS available boolean NOT NULL DEFAULT true",
    # Track the 5% shares vendors pay to the admin (UPI → recorded as Pending,
    # admin marks Received once the money lands in their bank account).
    """
    CREATE TABLE IF NOT EXISTS share_payments (
        id text PRIMARY KEY,
        shop_id text NOT NULL,
        shop_name text NOT NULL DEFAULT '',
        amount integer NOT NULL DEFAULT 0,
        status text NOT NULL DEFAULT 'Pending',
        created_at timestamptz NOT NULL DEFAULT now(),
        paid_at timestamptz
    )
    """,
    # Browser push subscriptions for vendor order notifications.
    """
    CREATE TABLE IF NOT EXISTS push_subscriptions (
        endpoint text PRIMARY KEY,
        shop_id text NOT NULL,
        p256dh text NOT NULL,
        auth text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_push_subscriptions_shop_id ON push_subscriptions (shop_id)",
    # Forgot-password double OTP verification (mirrors local_demo_db).
    """
    CREATE TABLE IF NOT EXISTS password_resets (
        id bigserial PRIMARY KEY,
        username text NOT NULL,
        otp text NOT NULL,
        step integer NOT NULL DEFAULT 1,
        expires_at timestamptz NOT NULL,
        used boolean NOT NULL DEFAULT false,
        attempts integer NOT NULL DEFAULT 0,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "ALTER TABLE password_resets ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0",
    "CREATE INDEX IF NOT EXISTS idx_password_resets_username ON password_resets (username, used)",
    # Site feedback / bug reports — students test the site and contribute
    # bugs + improvement ideas; admins review them on the Feedback page.
    """
    CREATE TABLE IF NOT EXISTS site_feedback (
        id text PRIMARY KEY,
        user_id bigint,
        username text NOT NULL DEFAULT '',
        name text NOT NULL DEFAULT '',
        email text NOT NULL DEFAULT '',
        category text NOT NULL DEFAULT 'Bug',
        subject text NOT NULL DEFAULT '',
        message text NOT NULL DEFAULT '',
        page text NOT NULL DEFAULT '',
        status text NOT NULL DEFAULT 'Open',
        -- Where the contribution came from: 'User' = submitted by a real
        -- student through the portal; 'ATS' = generated by the automated
        -- test suite. The admin Feedback page filters on this.
        source text NOT NULL DEFAULT 'User',
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "ALTER TABLE site_feedback ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'User'",
    "CREATE INDEX IF NOT EXISTS idx_site_feedback_status ON site_feedback (status)",
    "CREATE INDEX IF NOT EXISTS idx_site_feedback_user ON site_feedback (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_site_feedback_source ON site_feedback (source)",
    # Every vendor endpoint looks up their shop with LOWER(shopkeeper_email); a
    # functional index serves that query without a full-table scan.
    "CREATE INDEX IF NOT EXISTS idx_shops_shopkeeper_email_lower ON shops (LOWER(shopkeeper_email))",
    "CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders (created_at)",
    # One account per email — case-insensitive, non-empty only (legacy rows
    # with a blank email are left alone). The app-level check in register_user
    # reports the friendly error; this index is the race-safe backstop.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users (LOWER(email)) WHERE email <> ''",
    # Shop reviews
    """
    CREATE TABLE IF NOT EXISTS reviews (
        id text PRIMARY KEY,
        user_id bigint,
        username text NOT NULL DEFAULT '',
        student_name text NOT NULL DEFAULT '',
        shop_id text NOT NULL DEFAULT '',
        shop_name text NOT NULL DEFAULT '',
        rating integer NOT NULL DEFAULT 5,
        comment text NOT NULL DEFAULT '',
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_reviews_shop_id ON reviews (shop_id)",
]


def _apply_migrations() -> None:
    """Run the idempotent ALTER TABLE statements (no-op when already applied).
    Safe to call at any time — startup, or lazily after a missing-column error.

    Each statement runs inside its own SAVEPOINT. Without this, a single
    failing migration (e.g. a duplicate-key index on legacy data) would abort
    the whole transaction and Postgres' COMMIT would silently roll back every
    OTHER migration in the same run — which is how new tables/columns could
    end up missing even though migrations "ran" with no error."""
    try:
        with _DBContext(_connect()) as connection:
            with connection.cursor() as cursor:
                for statement in _MIGRATIONS:
                    cursor.execute("SAVEPOINT migration_step")
                    try:
                        cursor.execute(statement)
                    except Exception as migration_error:
                        # A failed statement marks the transaction aborted —
                        # jump back to the savepoint so the remaining
                        # migrations can still run and be committed.
                        cursor.execute("ROLLBACK TO SAVEPOINT migration_step")
                        logger.warning(f"Auto-migration skipped ({statement}): {migration_error}")
                    else:
                        cursor.execute("RELEASE SAVEPOINT migration_step")
    except Exception as e:
        logger.error(f"Auto-migrations failed: {e}")


def init_supabase_db() -> bool:
    """Verify connectivity and auto-apply any missing columns (idempotent).
    Returns True when reachable. The full schema lives in backend/supabase/schema.sql,
    but the small ALTERs below are re-run on every startup so the app never
    breaks if a new column hasn't been applied to an existing database yet."""
    try:
        with _DBContext(_connect()) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        _apply_migrations()
        logger.info("Supabase Postgres connection verified (auto-migrations applied)")
        return True
    except Exception as e:  # pragma: no cover - network dependent
        logger.error(f"Supabase Postgres connection failed: {e}")
        return False


# ─── Users ───


def register_user(
    username: str,
    password_hash: str,
    name: str,
    role: str,
    email: str = "",
    phone: str = "",
) -> tuple[dict[str, Any] | None, str | None]:
    """Register a new user. Returns ``(user, None)`` on success, or
    ``(None, 'username')`` / ``(None, 'email')`` when that field is already
    taken. Email uniqueness is case-insensitive and applies across ALL roles —
    one email can only ever own one account (mirrored by the
    ``idx_users_email_unique`` partial index, which is the race-safe backstop)."""
    normalized_email = (email or "").strip()
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE username = %s", (username.lower(),))
            if cursor.fetchone():
                return None, "username"

            if normalized_email:
                cursor.execute(
                    "SELECT id FROM users WHERE LOWER(email) = %s AND email <> ''",
                    (normalized_email.lower(),),
                )
                if cursor.fetchone():
                    return None, "email"

            try:
                cursor.execute(
                    """
                    INSERT INTO users (username, password_hash, name, email, phone, role)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id, username, name, email, phone, role, created_at
                    """,
                    (username.lower(), password_hash, name, normalized_email, phone, role),
                )
            except psycopg2.errors.UniqueViolation:
                # Race backstop: another request inserted the same email/username
                # between our checks and the insert — the unique index guarantees
                # consistency. Re-check to report the RIGHT conflict.
                # NOTE: the failed INSERT aborted the whole transaction, so
                # roll back before running the re-check SELECT (Postgres would
                # otherwise raise InFailedSqlTransaction).
                connection.rollback()
                if normalized_email:
                    cursor.execute(
                        "SELECT id FROM users WHERE LOWER(email) = %s AND email <> ''",
                        (normalized_email.lower(),),
                    )
                    if cursor.fetchone():
                        return None, "email"
                return None, "username"
            row = cursor.fetchone()
            return (dict(row) if row else None), None


def get_user_by_username(username: str) -> dict[str, Any] | None:
    """Get full user record (including password_hash) by username."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE username = %s", (username.lower(),))
            row = cursor.fetchone()
            return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    """Get user by id (without password_hash)."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, username, name, email, phone, role, created_at FROM users WHERE id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None


def save_session(email: str, name: str, role: str) -> dict[str, Any]:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM sessions WHERE email = %s AND role = %s ORDER BY id DESC LIMIT 1",
                (email, role),
            )
            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    "UPDATE sessions SET name = %s, created_at = now() WHERE id = %s RETURNING id, email, name, role, created_at",
                    (name, existing["id"]),
                )
                row = cursor.fetchone()
                return dict(row)
            cursor.execute(
                "INSERT INTO sessions (email, name, role) VALUES (%s, %s, %s) RETURNING id, email, name, role, created_at",
                (email, name, role),
            )
            row = cursor.fetchone()
            return dict(row)


# ─── Shops ───


def list_shops(public_only: bool = False) -> list[dict[str, Any]]:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM shops ORDER BY rating DESC")
            shops = _rows_to_dicts(cursor.fetchall())
        if public_only:
            # Students see every APPROVED shop (open or closed) so they can browse
            # menus and see opening hours. Ordering is still blocked server-side
            # for shops that are closed / not accepting orders.
            return [shop for shop in shops if shop["approval_status"] == "Approved"]
        return shops


def get_shop(shop_id: str) -> dict[str, Any] | None:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM shops WHERE id = %s", (shop_id,))
            row = cursor.fetchone()
            return dict(row) if row else None


def get_shop_by_shopkeeper_email(email: str) -> dict[str, Any] | None:
    """Get a vendor's shop by shopkeeper email (used by every vendor endpoint —
    avoids scanning the whole shops table on each request)."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM shops WHERE LOWER(shopkeeper_email) = %s ORDER BY created_at LIMIT 1",
                (email.lower(),),
            )
            row = cursor.fetchone()
            return dict(row) if row else None


def create_shop(values: dict[str, Any]) -> dict[str, Any]:
    with _DBContext(_connect()) as connection:
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
                upi_enabled, cod_enabled
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        _apply_migrations()
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
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"UPDATE shops SET {assignments} WHERE id = %s", params)
            cursor.execute("SELECT * FROM shops WHERE id = %s", (shop_id,))
            row = cursor.fetchone()
            return dict(row) if row else None


# ─── Products ───


def list_products(shop_id: str | None = None) -> list[dict[str, Any]]:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            if shop_id:
                cursor.execute(
                    "SELECT * FROM products WHERE shop_id = %s ORDER BY category, name",
                    (shop_id,),
                )
            else:
                cursor.execute("SELECT * FROM products ORDER BY category, name")
            return _rows_to_dicts(cursor.fetchall())


def create_product(values: dict[str, Any]) -> dict[str, Any]:
    """Create a product. Self-healing: if the database is missing a newer
    column (e.g. ``pending_price``), the migration is applied automatically
    and the insert is retried once — so vendors never hit a generic failure
    on an out-of-date Supabase schema."""
    try:
        return _create_product_impl(values)
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        logger.warning("Missing table/column in products — applying auto-migrations and retrying")
        _apply_migrations()
        return _create_product_impl(values)


def _create_product_impl(values: dict[str, Any]) -> dict[str, Any]:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            product_id = values.get("id")
            if not product_id:
                # Collision-proof: COUNT(*) + 1 reuses IDs after a delete, which
                # breaks inserts with a duplicate-key error. MAX(numeric suffix)
                # keeps the next ID unique even after rows are removed.
                cursor.execute(
                    "SELECT COALESCE(MAX(CAST(SUBSTRING(id FROM 2) AS INTEGER)), 0) + 1 AS next FROM products"
                )
                product_id = f"p{cursor.fetchone()['next']}"
            cursor.execute(
                """
                INSERT INTO products (
                    id, shop_id, name, description, price, pending_price,
                    category, inventory, prep_time, available
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    product_id,
                    values["shop_id"],
                    values["name"],
                    values.get("description", ""),
                    values["price"],
                    values.get("pending_price"),
                    values["category"],
                    values.get("inventory", 0),
                    values.get("prep_time", 10),
                    bool(values.get("available", True)),
                ),
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
    }
    updates = {key: value for key, value in values.items() if key in allowed_fields and (value is not None or key == "pending_price")}
    if not updates:
        return get_product(product_id)

    if "available" in updates:
        updates["available"] = bool(updates["available"])

    assignments = ", ".join(f"{field} = %s" for field in updates)
    params = [*updates.values(), product_id]
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"UPDATE products SET {assignments} WHERE id = %s", params)
            cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
            row = cursor.fetchone()
            return dict(row) if row else None


def get_product(product_id: str) -> dict[str, Any] | None:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
            row = cursor.fetchone()
            return dict(row) if row else None


def delete_product(product_id: str) -> bool:
    """Permanently remove a product row. Returns True when a row was deleted."""
    with _DBContext(_connect()) as connection:
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


# ─── Admin share payments (5% of vendor daily earnings → admin) ───


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
        _apply_migrations()
        return _record_share_payment_impl(shop_id, amount)


def _record_share_payment_impl(shop_id: str, amount: int) -> dict[str, Any] | None:
    shop = get_shop(shop_id)
    if not shop:
        return None
    with _DBContext(_connect()) as connection:
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
        _apply_migrations()
        return _list_share_payments_impl()


def list_share_payments_by_shop(shop_id: str) -> list[dict[str, Any]]:
    """Share payments for one shop only (vendor dashboard hot path)."""
    try:
        with _DBContext(_connect()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM share_payments WHERE shop_id = %s ORDER BY created_at DESC",
                    (shop_id,),
                )
                return _rows_to_dicts(cursor.fetchall())
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        _apply_migrations()
        with _DBContext(_connect()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM share_payments WHERE shop_id = %s ORDER BY created_at DESC",
                    (shop_id,),
                )
                return _rows_to_dicts(cursor.fetchall())


def _list_share_payments_impl() -> list[dict[str, Any]]:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM share_payments ORDER BY created_at DESC")
            return _rows_to_dicts(cursor.fetchall())


def update_share_payment_status(payment_id: str, status: str) -> dict[str, Any] | None:
    """Mark a share payment Received (Completed) or Rejected. Sets paid_at on completion."""
    try:
        return _update_share_payment_status_impl(payment_id, status)
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        _apply_migrations()
        return _update_share_payment_status_impl(payment_id, status)


def _update_share_payment_status_impl(payment_id: str, status: str) -> dict[str, Any] | None:
    with _DBContext(_connect()) as connection:
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


# ─── Orders ───


def list_orders(limit: int | None = None) -> list[dict[str, Any]]:
    """All orders, newest first. ``limit`` bounds the payload — callers that
    only need the latest rows (admin dashboard, orders page) pass it so the
    response never ships the shop's entire history on every poll."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            # Newest first — created_at desc puts today's orders on top even
            # though tokens restart every day (tokens alone mix days together).
            sql = "SELECT * FROM orders ORDER BY created_at DESC, token DESC"
            params: tuple = ()
            if limit:
                sql += " LIMIT %s"
                params = (limit,)
            cursor.execute(sql, params)
            return _rows_to_dicts(cursor.fetchall())


def list_orders_by_shop(shop_id: str) -> list[dict[str, Any]]:
    """Orders for one shop only — the vendor dashboard/history hot path. Uses
    the ``idx_orders_shop_id`` index instead of shipping every order to Python."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM orders WHERE shop_id = %s ORDER BY token DESC",
                (shop_id,),
            )
            return _rows_to_dicts(cursor.fetchall())


def list_recent_orders_by_shop(shop_id: str, limit: int = 250) -> list[dict[str, Any]]:
    """Latest orders for one shop (newest first) — the live feed shown in the
    vendor app. Bounded so the 30s auto-refresh never ships the shop's entire
    order history (that payload grew with every order and made the vendor app
    feel slow). Stats are still computed from the full list via
    ``list_orders_by_shop``."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM orders WHERE shop_id = %s ORDER BY created_at DESC LIMIT %s",
                (shop_id, limit),
            )
            return _rows_to_dicts(cursor.fetchall())


def get_order(order_id: str) -> dict[str, Any] | None:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
            row = cursor.fetchone()
            return dict(row) if row else None


def update_order_status(order_id: str, status: str) -> dict[str, Any] | None:
    with _DBContext(_connect()) as connection:
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
                create_notification(
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
        _apply_migrations()
        return _create_order_impl(values)


def _create_order_impl(values: dict[str, Any]) -> dict[str, Any] | None:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM shops WHERE id = %s", (values["shop_id"],))
            shop = cursor.fetchone()
            if not shop:
                return None
            if not _shop_is_orderable(dict(shop)):
                return None

            product_ids = [item["product_id"] for item in values["items"]]
            products_by_id = {}
            for product_id in product_ids:
                cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
                row = cursor.fetchone()
                if row:
                    products_by_id[product_id] = dict(row)

            subtotal = 0
            item_labels = []
            for item in values["items"]:
                product = products_by_id.get(item["product_id"])
                if not product:
                    continue
                quantity = int(item["quantity"])
                subtotal += int(product["price"]) * quantity
                item_labels.append(f"{quantity}x {product['name']}")

            if not item_labels:
                return None

            # ─── Fees: the customer pays only the subtotal. The admin's 5% is
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
            payment_method = str(values.get("payment_method", "") or "").strip()
            if payment_method == "COD":
                initial_status = "Pending Acceptance"
            elif payment_method == "UPI":
                initial_status = "Pending Payment"
            elif payment_method == "Razorpay":
                initial_status = "Pending Acceptance"
            else:
                # Legacy callers without a payment method keep old behavior
                initial_status = "Pending Payment" if values.get("pending_payment") else "Pending Acceptance"
                payment_method = "UPI" if initial_status == "Pending Payment" else "COD"

            # ─── Order IDs: o<IST date>-<daily token> ───
            # The token restarts daily in India time (Asia/Kolkata), so the
            # "today" boundary must be IST too — using the server's CURRENT_DATE
            # (usually UTC) lets orders placed between 12:00–5:30 AM IST share a
            # token bucket with the previous day and collide on the same ID.
            today_key = _now_kolkata().strftime("%Y%m%d")
            ist_day_start = _now_kolkata().replace(hour=0, minute=0, second=0, microsecond=0)
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
                            id, token, student_name, student_phone, shop_id, shop_name,
                            items, subtotal, service_fee, tax, delivery_fee, total,
                            delivery_location, delivery_slot, status, payment_method, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                        """,
                        (
                            order_id,
                            next_token,
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
                create_notification(
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


# ─── Payments ───


def create_payment(
    order_id: str,
    amount: int,
    method: str,
    utr_number: str | None = None,
    screenshot_name: str | None = None,
) -> dict[str, Any] | None:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
            order = cursor.fetchone()
            if not order:
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
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM payments ORDER BY created_at DESC")
            return _rows_to_dicts(cursor.fetchall())


def update_payment_status(payment_id: str, status: str) -> dict[str, Any] | None:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE payments SET status = %s WHERE id = %s", (status, payment_id))
            cursor.execute("SELECT * FROM payments WHERE id = %s", (payment_id,))
            row = cursor.fetchone()
            if row and status == "Success":
                cursor.execute("UPDATE orders SET status = %s WHERE id = %s", ("Pending Acceptance", row["order_id"]))
                cursor.execute("SELECT * FROM orders WHERE id = %s", (row["order_id"],))
                order_row = cursor.fetchone()
                if order_row:
                    create_notification(
                        title="Payment confirmed",
                        message=f"Payment for token {order_row['token']} confirmed — the shop will accept your order soon.",
                        order_id=row["order_id"],
                        status="Pending Acceptance",
                        target_role="student",
                        connection=connection,
                    )
            if row and status == "Failed":
                cursor.execute("UPDATE orders SET status = %s WHERE id = %s", ("Failed", row["order_id"]))
            return dict(row) if row else None


def get_payment_by_order_id(order_id: str) -> dict[str, Any] | None:
    """Get the most recent payment record for an order."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM payments WHERE order_id = %s ORDER BY created_at DESC, id DESC LIMIT 1",
                (order_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None


def set_payment_utr(order_id: str, utr_number: str) -> dict[str, Any] | None:
    """Stamp the student-provided UTR on the latest payment for an order."""
    with _DBContext(_connect()) as connection:
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
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM payments WHERE utr_number = %s ORDER BY created_at DESC, id DESC LIMIT 1",
                (utr_number,),
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
    with _DBContext(_connect()) as connection:
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
    with _DBContext(_connect()) as connection:
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


# ─── Tickets ───


def create_ticket(values: dict[str, Any]) -> dict[str, Any]:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) + 1 AS next FROM tickets")
            next_id = cursor.fetchone()["next"]
            ticket_id = f"t{next_id}"
            ticket_number = f"TKT-{1000 + next_id}"
            cursor.execute(
                """
                INSERT INTO tickets (
                    id, ticket_number, name, email, phone_number, category,
                    title, description, status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    ticket_id,
                    ticket_number,
                    values["name"],
                    values["email"],
                    values["phone_number"],
                    values["category"],
                    values["title"],
                    values["description"],
                    "Open",
                ),
            )
            cursor.execute("SELECT * FROM tickets WHERE id = %s", (ticket_id,))
            row = cursor.fetchone()
            return dict(row)


def list_tickets() -> list[dict[str, Any]]:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM tickets ORDER BY created_at DESC")
            return _rows_to_dicts(cursor.fetchall())


# ─── Notifications ───


def create_notification(
    title: str,
    message: str,
    order_id: str | None = None,
    status: str | None = None,
    target_role: str | None = None,
    connection: Any | None = None,
) -> dict[str, Any] | None:
    owns_connection = connection is None
    active_connection = connection or _connect()
    cursor = None
    try:
        cursor = active_connection.cursor()
        # Collision-proof id (MAX, not COUNT) so deleted notification rows can
        # never make the next insert fail with a duplicate-key error.
        cursor.execute(
            "SELECT COALESCE(MAX(CAST(SUBSTRING(id FROM 2) AS INTEGER)), 0) + 1 AS next FROM notifications"
        )
        notification_id = f"n{cursor.fetchone()['next']}"
        cursor.execute(
            "INSERT INTO notifications (id, title, message, order_id, status, target_role) VALUES (%s, %s, %s, %s, %s, %s)",
            (notification_id, title, message, order_id, status, target_role),
        )
        cursor.execute("SELECT * FROM notifications WHERE id = %s", (notification_id,))
        row = cursor.fetchone()
        if owns_connection:
            active_connection.commit()
        return dict(row) if row else None
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if owns_connection:
            _release(active_connection)


def list_notifications(role: str | None = None) -> list[dict[str, Any]]:
    """List notifications. When ``role`` is given, only notifications targeted at
    that exact role are returned (strict role separation)."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            if role:
                cursor.execute(
                    "SELECT * FROM notifications WHERE target_role = %s ORDER BY created_at DESC LIMIT 20",
                    (role,),
                )
            else:
                cursor.execute("SELECT * FROM notifications ORDER BY created_at DESC LIMIT 20")
            return _rows_to_dicts(cursor.fetchall())


# ─── Web push subscriptions (vendor order notifications) ───


def save_push_subscription(
    shop_id: str,
    endpoint: str,
    p256dh: str,
    auth: str,
) -> dict[str, Any] | None:
    """Save (or refresh) a browser push subscription for a vendor's shop.
    ``endpoint`` is unique per device+browser, so it's the natural key."""
    try:
        return _save_push_subscription_impl(shop_id, endpoint, p256dh, auth)
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        logger.warning("Missing push_subscriptions table — applying auto-migrations and retrying")
        _apply_migrations()
        return _save_push_subscription_impl(shop_id, endpoint, p256dh, auth)


def _save_push_subscription_impl(
    shop_id: str,
    endpoint: str,
    p256dh: str,
    auth: str,
) -> dict[str, Any] | None:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO push_subscriptions (endpoint, shop_id, p256dh, auth)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (endpoint) DO UPDATE SET
                    shop_id = EXCLUDED.shop_id,
                    p256dh = EXCLUDED.p256dh,
                    auth = EXCLUDED.auth
                """,
                (endpoint, shop_id, p256dh, auth),
            )
            cursor.execute(
                "SELECT * FROM push_subscriptions WHERE endpoint = %s",
                (endpoint,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None


def list_push_subscriptions(shop_id: str) -> list[dict[str, Any]]:
    """All push subscriptions registered for a shop (used to deliver pushes)."""
    try:
        return _list_push_subscriptions_impl(shop_id)
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        _apply_migrations()
        return _list_push_subscriptions_impl(shop_id)


def _list_push_subscriptions_impl(shop_id: str) -> list[dict[str, Any]]:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM push_subscriptions WHERE shop_id = %s ORDER BY created_at",
                (shop_id,),
            )
            return _rows_to_dicts(cursor.fetchall())


def remove_push_subscription(shop_id: str, endpoint: str) -> bool:
    """Remove a push subscription (e.g. when the browser reports it's dead)."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM push_subscriptions WHERE endpoint = %s AND shop_id = %s",
                (endpoint, shop_id),
            )
            return cursor.rowcount > 0


# ─── Admin helpers ───


def list_users() -> list[dict[str, Any]]:
    """List all registered users (without password_hash)."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, username, name, email, phone, role, created_at FROM users ORDER BY created_at DESC"
            )
            return _rows_to_dicts(cursor.fetchall())


def list_users_by_role(role: str) -> list[dict[str, Any]]:
    """List users filtered by role."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, username, name, email, phone, role, created_at FROM users WHERE role = %s ORDER BY created_at DESC",
                (role,),
            )
            return _rows_to_dicts(cursor.fetchall())


def record_registration(user: dict[str, Any]) -> None:
    """Record a user registration for admin notifications."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO user_registrations (username, name, email, phone, role) VALUES (%s, %s, %s, %s, %s)",
                (user.get("username", ""), user.get("name", ""), user.get("email", ""), user.get("phone", ""), user.get("role", "")),
            )


def list_registrations() -> list[dict[str, Any]]:
    """List all user registrations for admin."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM user_registrations ORDER BY created_at DESC")
            return _rows_to_dicts(cursor.fetchall())


# ─── Forgot password (double email OTP verification) ───


def get_user_by_email(email: str) -> dict[str, Any] | None:
    """Find a user by their registered email (case-insensitive)."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM users WHERE LOWER(email) = %s LIMIT 1",
                (email.lower(),),
            )
            row = cursor.fetchone()
            return dict(row) if row else None


def create_password_reset(username: str, otp: str, step: int) -> dict[str, Any] | None:
    """Store an OTP for a password-reset step (1 or 2) for the given user.
    Older unused codes for the same user are cleared so only the newest counts."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM password_resets WHERE username = %s",
                (username.lower(),),
            )
            cursor.execute(
                "INSERT INTO password_resets (username, otp, step, expires_at) "
                "VALUES (%s, %s, %s, now() + make_interval(mins => %s)) RETURNING *",
                (username.lower(), otp, step, int(settings.RESET_OTP_EXPIRE_MINUTES)),
            )
            row = cursor.fetchone()
            return dict(row) if row else None


def get_password_reset(username: str, otp: str, step: int) -> dict[str, Any] | None:
    """Return the valid, unused, unexpired reset code for this user/step.
    Codes are locked out after 5 wrong attempts (brute-force protection)."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM password_resets
                WHERE username = %s AND otp = %s AND step = %s AND used = false
                  AND attempts < 5
                  AND expires_at > now()
                ORDER BY id DESC LIMIT 1
                """,
                (username.lower(), otp, step),
            )
            row = cursor.fetchone()
            return dict(row) if row else None


def bump_password_reset_attempts(username: str) -> None:
    """Count one wrong OTP guess for this user's pending reset."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE password_resets SET attempts = attempts + 1 WHERE username = %s AND used = false",
                (username.lower(),),
            )


def invalidate_password_resets(username: str) -> None:
    """Mark every pending reset code for this user as used."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE password_resets SET used = true WHERE username = %s",
                (username.lower(),),
            )


def update_user_password(username: str, new_password_hash: str) -> bool:
    """Set a new password hash for a user (by username)."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET password_hash = %s WHERE username = %s",
                (new_password_hash, username.lower()),
            )
            return cursor.rowcount > 0


# ─── Site feedback / bug reports (students → admin) ───


def create_site_feedback(values: dict[str, Any]) -> dict[str, Any] | None:
    """Store a student's bug report / improvement contribution.

    The admin is notified through the notifications bell (target_role='admin')
    so new contributions surface immediately on the admin Feedback page."""
    try:
        return _create_site_feedback_impl(values)
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        logger.warning("Missing site_feedback table/columns — applying auto-migrations and retrying")
        _apply_migrations()
        return _create_site_feedback_impl(values)


def _create_site_feedback_impl(values: dict[str, Any]) -> dict[str, Any] | None:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            # Collision-proof id (MAX, not COUNT) so deleted rows never cause
            # the next insert to fail with a duplicate-key error.
            cursor.execute(
                "SELECT COALESCE(MAX(CAST(SUBSTRING(id FROM 3) AS INTEGER)), 0) + 1 AS next FROM site_feedback"
            )
            feedback_id = f"fb{cursor.fetchone()['next']}"
            cursor.execute(
                """
                INSERT INTO site_feedback (
                    id, user_id, username, name, email, category,
                    subject, message, page, status, source
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'Open', %s)
                """,
                (
                    feedback_id,
                    values.get("user_id"),
                    values.get("username", ""),
                    values.get("name", ""),
                    values.get("email", ""),
                    values.get("category", "Bug"),
                    values.get("subject", ""),
                    values.get("message", ""),
                    values.get("page", ""),
                    values.get("source", "User"),
                ),
            )
            cursor.execute("SELECT * FROM site_feedback WHERE id = %s", (feedback_id,))
            row = cursor.fetchone()
            if row:
                create_notification(
                    title=f"New {row['category'].lower()} reported",
                    message=f"{row['name'] or row['username'] or 'A user'}: {row['subject'] or row['message'][:60]}",
                    target_role="admin",
                    connection=connection,
                )
            return dict(row) if row else None


def list_site_feedback(source: str | None = None) -> list[dict[str, Any]]:
    """All site feedback, newest first (admin Feedback page).
    Pass ``source`` = 'User' or 'ATS' to see only real students or only
    automated-test contributions."""
    try:
        return _list_site_feedback_impl(source)
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        _apply_migrations()
        return _list_site_feedback_impl(source)


def _list_site_feedback_impl(source: str | None = None) -> list[dict[str, Any]]:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            if source:
                cursor.execute(
                    "SELECT * FROM site_feedback WHERE source = %s ORDER BY created_at DESC",
                    (source,),
                )
            else:
                cursor.execute("SELECT * FROM site_feedback ORDER BY created_at DESC")
            return _rows_to_dicts(cursor.fetchall())


def list_site_feedback_by_user(user_id: int) -> list[dict[str, Any]]:
    """A student's own submissions (student portal "my contributions")."""
    try:
        return _list_site_feedback_by_user_impl(user_id)
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        _apply_migrations()
        return _list_site_feedback_by_user_impl(user_id)


def _list_site_feedback_by_user_impl(user_id: int) -> list[dict[str, Any]]:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM site_feedback WHERE user_id = %s ORDER BY created_at DESC",
                (user_id,),
            )
            return _rows_to_dicts(cursor.fetchall())


def update_site_feedback_status(feedback_id: str, status: str) -> dict[str, Any] | None:
    """Admin marks a contribution as Open / In Review / Fixed / Won't Fix."""
    allowed = {"Open", "In Review", "Fixed", "Won't Fix"}
    if status not in allowed:
        return None
    try:
        return _update_site_feedback_status_impl(feedback_id, status)
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        _apply_migrations()
        return _update_site_feedback_status_impl(feedback_id, status)


def _update_site_feedback_status_impl(feedback_id: str, status: str) -> dict[str, Any] | None:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE site_feedback SET status = %s WHERE id = %s",
                (status, feedback_id),
            )
            cursor.execute("SELECT * FROM site_feedback WHERE id = %s", (feedback_id,))
            row = cursor.fetchone()
            return dict(row) if row else None


def delete_site_feedback(source: str | None = None) -> int:
    """Permanently delete feedback rows.

    Pass ``source='ATS'`` to clear automated-test contributions, ``'User'`` to
    clear real reports, or ``None`` for everything. Returns how many rows were
    removed — the admin Feedback page uses this to purge test data so the page
    shows ONLY real student feedback."""
    try:
        return _delete_site_feedback_impl(source)
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        _apply_migrations()
        return _delete_site_feedback_impl(source)


def _delete_site_feedback_impl(source: str | None = None) -> int:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            if source:
                cursor.execute(
                    "DELETE FROM site_feedback WHERE source = %s",
                    (source,),
                )
            else:
                cursor.execute("DELETE FROM site_feedback")
            return cursor.rowcount


# --- Shop reviews ---


def create_review(values: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return _create_review_impl(values)
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        _apply_migrations()
        return _create_review_impl(values)


def _create_review_impl(values: dict[str, Any]) -> dict[str, Any] | None:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COALESCE(MAX(CAST(SUBSTRING(id FROM 3) AS integer)), 0) + 1 FROM reviews")
            next_id = cursor.fetchone()[0]
            review_id = f"rv{next_id}"
            shop_name = values.get("shop_name", "")
            if not shop_name and values.get("shop_id"):
                try:
                    cursor.execute("SELECT name FROM shops WHERE id = %s", (values["shop_id"],))
                    row = cursor.fetchone()
                    if row:
                        shop_name = row["name"]
                except Exception:
                    pass
            cursor.execute(
                """INSERT INTO reviews (id, user_id, username, student_name, shop_id, shop_name, rating, comment)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    review_id,
                    values.get("user_id"),
                    values.get("username", ""),
                    values.get("student_name", ""),
                    values.get("shop_id", ""),
                    shop_name,
                    values.get("rating", 5),
                    values.get("comment", ""),
                ),
            )
            cursor.execute("SELECT * FROM reviews WHERE id = %s", (review_id,))
            row = cursor.fetchone()
            return dict(row) if row else None


def list_reviews(shop_id: str | None = None) -> list[dict[str, Any]]:
    try:
        return _list_reviews_impl(shop_id)
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        _apply_migrations()
        return _list_reviews_impl(shop_id)


def _list_reviews_impl(shop_id: str | None = None) -> list[dict[str, Any]]:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            if shop_id:
                cursor.execute("SELECT * FROM reviews WHERE shop_id = %s ORDER BY created_at DESC", (shop_id,))
            else:
                cursor.execute("SELECT * FROM reviews ORDER BY created_at DESC")
            return _rows_to_dicts(cursor.fetchall())


def list_reviews_by_user(user_id: int) -> list[dict[str, Any]]:
    try:
        return _list_reviews_by_user_impl(user_id)
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        _apply_migrations()
        return _list_reviews_by_user_impl(user_id)


def _list_reviews_by_user_impl(user_id: int) -> list[dict[str, Any]]:
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM reviews WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
            return _rows_to_dicts(cursor.fetchall())


def delete_user(user_id: int) -> bool:
    """Permanently delete a user and EVERY record that references them, so a
    deleted account's username/email become re-registrable immediately and no
    stale rows keep the old data around.

    Cascades: sessions (by email), user_registrations (by username),
    site_feedback (by user_id), password_resets (by username), and a
    shopkeeper's linked shop (soft-removed so orders keep their history).
    Each cleanup is guarded so a missing/legacy table can never block the
    delete of the user row itself."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            if not user:
                return False

            username = str(user["username"])
            email = str(user.get("email") or "").strip().lower()
            if email:
                try:
                    cursor.execute(
                        "DELETE FROM sessions WHERE LOWER(email) = %s",
                        (email,),
                    )
                except psycopg2.Error:
                    connection.rollback()
            for table, column, value in (
                ("user_registrations", "username", username),
                ("password_resets", "username", username),
                ("site_feedback", "user_id", user_id),
            ):
                try:
                    cursor.execute(
                        f"DELETE FROM {table} WHERE {column} = %s",
                        (value,),
                    )
                except psycopg2.Error:
                    connection.rollback()
            if str(user.get("role") or "") == "shopkeeper" and email:
                try:
                    cursor.execute(
                        "UPDATE shops SET is_removed = true, present = false, status = 'Closed', "
                        "approval_status = 'Removed' WHERE LOWER(shopkeeper_email) = %s",
                        (email,),
                    )
                except psycopg2.Error:
                    connection.rollback()
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
            return cursor.rowcount > 0


def get_admin_dashboard_stats(today: str) -> dict[str, Any]:
    """Admin dashboard numbers computed in SQL (COUNT/SUM subqueries) instead
    of loading every row into Python. The old approach pulled the entire
    orders/payments/products tables on every 15s poll and aggregated them in
    Python, which is what made the admin panel feel slow as data grew.
    ``today`` is the Asia/Kolkata date string (YYYY-MM-DD)."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM shops) AS total_shops,
                  (SELECT COUNT(*) FROM shops WHERE approval_status = 'Approved') AS approved_shops,
                  (SELECT COUNT(*) FROM shops WHERE approval_status = 'Pending Approval') AS pending_approvals,
                  (SELECT COUNT(*) FROM orders) AS total_orders,
                  (SELECT COUNT(*) FROM orders WHERE status NOT IN ('Completed', 'Cancelled')) AS active_orders,
                  (SELECT COALESCE(SUM(total), 0) FROM orders) AS total_revenue,
                  (SELECT COUNT(*) FROM orders WHERE (created_at AT TIME ZONE 'Asia/Kolkata')::date = %s::date) AS today_orders,
                  (SELECT COALESCE(SUM(total), 0) FROM orders WHERE (created_at AT TIME ZONE 'Asia/Kolkata')::date = %s::date) AS today_revenue,
                  (SELECT COUNT(*) FROM products) AS total_products,
                  (SELECT COUNT(*) FROM payments WHERE status = 'Pending Verification') AS pending_payments
                """,
                (today, today),
            )
            row = cursor.fetchone()
            return dict(row) if row else {}


def get_orders_grouped_by_date() -> list[dict[str, Any]]:
    """Get orders grouped by date for revenue tracking."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT created_at::date::text AS created_at, COUNT(*) AS count, SUM(total) AS revenue, "
                "SUM(subtotal) AS subtotal, ROUND(SUM(total) * 0.05) AS service_fee, "
                "SUM(tax) AS tax, SUM(delivery_fee) AS delivery_fee, "
                "STRING_AGG(id, ',') AS ids FROM orders GROUP BY created_at::date ORDER BY created_at::date DESC"
            )
            return _rows_to_dicts(cursor.fetchall())


def get_orders_by_date(date_key: str) -> list[dict[str, Any]]:
    """Get orders for a specific date (YYYY-MM-DD) for daily log filtering."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM orders WHERE created_at::date = %s::date ORDER BY token DESC",
                (date_key,),
            )
            return _rows_to_dicts(cursor.fetchall())


def get_payments_by_date(date_key: str) -> list[dict[str, Any]]:
    """Get payments for a specific date (YYYY-MM-DD) for daily log filtering."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM payments WHERE created_at::date = %s::date ORDER BY created_at DESC",
                (date_key,),
            )
            return _rows_to_dicts(cursor.fetchall())


def get_daily_stats() -> dict[str, Any]:
    """Get today's statistics."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS count, COALESCE(SUM(total), 0) AS revenue, "
                "ROUND(COALESCE(SUM(total), 0) * 0.05) AS service_fee FROM orders WHERE created_at::date = CURRENT_DATE"
            )
            today_orders = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) AS count FROM users")
            total_users = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) AS count FROM shops WHERE approval_status = 'Approved'")
            total_shops = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) AS count FROM orders")
            total_orders = cursor.fetchone()
            cursor.execute("SELECT ROUND(COALESCE(SUM(total), 0) * 0.05) AS total FROM orders")
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
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT created_at::date::text AS created_at, COUNT(*) AS count,
                       SUM(total) AS revenue, ROUND(SUM(total) * 0.05) AS admin_fee
                FROM orders WHERE shop_id = %s
                GROUP BY created_at::date ORDER BY created_at::date DESC
                """,
                (shop_id,),
            )
            return _rows_to_dicts(cursor.fetchall())


def get_vendor_orders(shop_id: str) -> list[dict[str, Any]]:
    """All orders for one shop (admin vendor logs)."""
    with _DBContext(_connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM orders WHERE shop_id = %s ORDER BY created_at DESC",
                (shop_id,),
            )
            return _rows_to_dicts(cursor.fetchall())


def get_summary() -> dict[str, Any]:
    shops = list_shops()
    orders = list_orders()
    products = list_products()
    return {
        "shops": len(shops),
        "orderable_shops": len([
            shop for shop in shops
            if _shop_is_orderable(shop)
        ]),
        "products": len(products),
        "active_orders": len([order for order in orders if order["status"] != "Completed"]),
        "revenue": sum(order["total"] for order in orders),
        "token_starts_at": 18,
    }


# ═══════════════════════════════════════════════════════════════════════
#  MULTI-SHOP ORDERING — parent orders, sub-orders, batch stock, tokens
#  Signatures mirror app/core/local_demo_db.py exactly so the API layer
#  (app/api/v1/local.py) works against either store via the `store` facade.
# ═══════════════════════════════════════════════════════════════════════

def _day_key() -> str:
    """Today's date in IST as YYYY-MM-DD (matches local_demo_db)."""
    return _now_kolkata().strftime("%Y-%m-%d")


def _day_key_compact() -> str:
    """Today's date in IST as YYYYMMDD (used in order ids like p20240320-18)."""
    return _now_kolkata().strftime("%Y%m%d")


def get_current_batch(now: str | None = None) -> str:
    """Return the active delivery batch name ('Afternoon' or 'Night')."""
    hour = _now_kolkata().hour
    return "Afternoon" if hour < 15 else "Night"


def get_next_token() -> int:
    """Next parent-order token for today. Tokens start at 18 each day."""
    dk = _day_key()
    connection = _connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(MAX(token), 17) + 1 AS next_token FROM parent_orders WHERE date_key = %s",
                (dk,),
            )
            row = cursor_row(cur)
            return int(row["next_token"]) if row else 18
    finally:
        _release(connection)


def consume_token() -> int:
    """Reserve the next token number and return it."""
    return get_next_token()


def get_product_stock(product_id: str, batch_type: str, date_key: str | None = None) -> int:
    """Remaining stock for a product in the given batch."""
    dk = date_key or _day_key()
    connection = _connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT total_stock, sold FROM product_stock WHERE product_id = %s AND date_key = %s AND batch_type = %s",
                (product_id, dk, batch_type),
            )
            row = cursor_row(cur)
            if row:
                return max(0, int(row["total_stock"]) - int(row["sold"]))
            cur.execute("SELECT inventory FROM products WHERE id = %s", (product_id,))
            prow = cursor_row(cur)
            return int(prow["inventory"]) if prow else 0
    finally:
        _release(connection)


def init_batch_stock(product_id: str, batch_type: str, default_stock: int, date_key: str | None = None) -> None:
    """Insert a default stock row for a product in a batch (no-op if present)."""
    dk = date_key or _day_key()
    connection = _connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                """INSERT INTO product_stock (product_id, date_key, batch_type, total_stock, sold)
                   VALUES (%s, %s, %s, %s, 0)
                   ON CONFLICT (product_id, date_key, batch_type) DO NOTHING""",
                (product_id, dk, batch_type, default_stock),
            )
            connection.commit()
    except Exception:
        connection.rollback()
    finally:
        _release(connection)


def consume_batch_stock(product_id: str, batch_type: str, qty: int, date_key: str | None = None) -> bool:
    """Consume qty from a batch. Returns False when insufficient stock."""
    dk = date_key or _day_key()
    connection = _connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT id, total_stock, sold FROM product_stock WHERE product_id = %s AND date_key = %s AND batch_type = %s",
                (product_id, dk, batch_type),
            )
            row = cursor_row(cur)
            if row:
                remaining = int(row["total_stock"]) - int(row["sold"])
                if remaining < qty:
                    return False
                cur.execute(
                    "UPDATE product_stock SET sold = sold + %s WHERE id = %s",
                    (qty, row["id"]),
                )
                connection.commit()
                return True
            # No stock row — fall back to product inventory.
            cur.execute("SELECT inventory FROM products WHERE id = %s", (product_id,))
            prow = cursor_row(cur)
            if prow and int(prow["inventory"]) >= qty:
                return True
            return False
    except Exception:
        connection.rollback()
        return False
    finally:
        _release(connection)


def release_batch_stock(product_id: str, batch_type: str, qty: int, date_key: str | None = None) -> None:
    """Give back stock (e.g. cancellation)."""
    dk = date_key or _day_key()
    connection = _connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE product_stock SET sold = GREATEST(0, sold - %s) WHERE product_id = %s AND date_key = %s AND batch_type = %s",
                (qty, product_id, dk, batch_type),
            )
            connection.commit()
    except Exception:
        connection.rollback()
    finally:
        _release(connection)


def create_parent_order(
    student_name: str,
    student_phone: str,
    delivery_location: str,
    payment_method: str,
    shops: list[dict[str, Any]],
    student_email: str = "",
    student_id: str = "",
) -> dict[str, Any] | None:
    """Create a multi-shop parent order with per-shop sub-orders.

    ``shops`` is a list like::

        [{"shop_id": "...", "items": [{"product_id": "...", "quantity": 2}]}, ...]

    Returns the parent order dict (with nested ``sub_orders``) or raises
    ``ValueError`` when no valid sub-order can be created. One token is shared
    across ALL sub-orders. The student pays ONE bill (sum of sub-order
    subtotals); each shop's 5% commission is recorded per sub-order but never
    charged to the student.
    """
    token = consume_token()
    today_key = _day_key_compact()
    parent_id = f"p{today_key}-{token}"
    batch_type = get_current_batch()

    sub_orders: list[dict[str, Any]] = []
    grand_total = 0
    connection = _connect()
    try:
        with connection.cursor() as cur:
            for group in shops:
                cur.execute("SELECT * FROM shops WHERE id = %s", (group["shop_id"],))
                shop = cursor_row(cur)
                if not shop or not _shop_is_orderable(shop):
                    continue

                product_ids = [item["product_id"] for item in group.get("items", [])]
                products_by_id: dict[str, Any] = {}
                for pid in product_ids:
                    cur.execute("SELECT * FROM products WHERE id = %s", (pid,))
                    prow = cursor_row(cur)
                    if prow:
                        products_by_id[pid] = prow

                subtotal = 0
                order_item_rows: list[tuple] = []
                for item in group.get("items", []):
                    product = products_by_id.get(item["product_id"])
                    if not product:
                        continue
                    quantity = int(item["quantity"])
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

                commission = round(subtotal * 0.05)
                sub_order_id = f"{parent_id}-{len(sub_orders) + 1}"
                shop_whatsapp = str(shop.get("whatsapp_number") or "").strip()
                shop_phone = str(shop.get("phone") or "").strip()

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
                grand_total += subtotal

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

            if not sub_orders:
                raise ValueError("No valid shops or items in order")

            cur.execute(
                """INSERT INTO parent_orders (
                       id, token, date_key, student_name, student_phone, student_email,
                       student_id, total, payment_method, payment_status,
                       delivery_location, status, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'Pending', %s, 'Pending', NOW())""",
                (
                    parent_id,
                    token,
                    _day_key(),
                    student_name,
                    student_phone,
                    student_email,
                    student_id,
                    grand_total,
                    payment_method,
                    delivery_location,
                ),
            )
            connection.commit()

            cur.execute("SELECT * FROM parent_orders WHERE id = %s", (parent_id,))
            parent = cursor_row(cur)
            if parent:
                parent["sub_orders"] = sub_orders
            return parent
    except Exception:
        connection.rollback()
        raise
    finally:
        _release(connection)


def get_parent_order(parent_order_id: str, with_items: bool = True) -> dict[str, Any] | None:
    """Parent order with its shop sub-orders and their items."""
    connection = _connect()
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT * FROM parent_orders WHERE id = %s", (parent_order_id,))
            parent = cursor_row(cur)
            if not parent:
                return None
            cur.execute(
                "SELECT * FROM shop_sub_orders WHERE parent_order_id = %s ORDER BY id",
                (parent_order_id,),
            )
            sub_orders: list[dict[str, Any]] = []
            for raw in cur.fetchall():
                sub = dict(raw)
                if with_items:
                    cur.execute(
                        "SELECT * FROM order_items WHERE sub_order_id = %s",
                        (sub["id"],),
                    )
                    sub["items"] = _rows_to_dicts(cur.fetchall())
                sub_orders.append(sub)
            parent["sub_orders"] = sub_orders
            return parent
    finally:
        _release(connection)


def list_parent_orders(limit: int = 200, status: str | None = None) -> list[dict[str, Any]]:
    """List parent orders, newest first, optional status filter."""
    connection = _connect()
    try:
        with connection.cursor() as cur:
            if status:
                cur.execute(
                    "SELECT * FROM parent_orders WHERE status = %s ORDER BY created_at DESC LIMIT %s",
                    (status, limit),
                )
            else:
                cur.execute("SELECT * FROM parent_orders ORDER BY created_at DESC LIMIT %s", (limit,))
            return _rows_to_dicts(cur.fetchall())
    finally:
        _release(connection)


def get_shop_sub_orders(shop_id: str, status: str | None = None) -> list[dict[str, Any]]:
    """All sub-orders for a shop (shopkeeper portal). Only this shop's items."""
    connection = _connect()
    try:
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
            sub_orders: list[dict[str, Any]] = []
            for row in cur.fetchall():
                sub = dict(row)
                cur.execute(
                    "SELECT * FROM order_items WHERE sub_order_id = %s",
                    (sub["id"],),
                )
                sub["items"] = _rows_to_dicts(cur.fetchall())
                cur.execute(
                    "SELECT student_name, student_phone, delivery_location, total, payment_method, created_at FROM parent_orders WHERE id = %s",
                    (sub["parent_order_id"],),
                )
                parent = cursor_row(cur)
                sub["parent"] = parent or {}
                sub_orders.append(sub)
            return sub_orders
    finally:
        _release(connection)


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
    connection = _connect()
    try:
        with connection.cursor() as cur:
            if ts_col:
                cur.execute(
                    f"""UPDATE shop_sub_orders SET status = %s, {ts_col} = NOW(),
                        rejection_reason = CASE WHEN %s = 'Rejected' THEN %s ELSE rejection_reason END
                        WHERE id = %s RETURNING *""",
                    (status, status, notes, sub_order_id),
                )
            else:
                cur.execute("UPDATE shop_sub_orders SET status = %s WHERE id = %s RETURNING *", (status, sub_order_id))
            connection.commit()
            return cursor_row(cur)
    except Exception:
        connection.rollback()
        return None
    finally:
        _release(connection)


def get_daily_token_count(date_key: str | None = None) -> int:
    """Number of parent orders today."""
    dk = date_key or _day_key()
    connection = _connect()
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM parent_orders WHERE date_key = %s", (dk,))
            row = cursor_row(cur)
            return int(row["cnt"]) if row else 0
    finally:
        _release(connection)


def auto_complete_expired_deliveries() -> int:
    """Auto-complete sub-orders delivered more than 30 minutes ago.

    Per spec section 36: after the 30-minute problem window the order is
    auto-confirmed, and the parent order completes once every sub-order is
    terminal. Idempotent + fast, so it is safe to call on every request —
    this makes it work on serverless hosts (Vercel) with no background loop.
    Returns the number of sub-orders completed just now.
    """
    completed_now = 0
    connection = _connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                """SELECT id, parent_order_id, delivered_at
                   FROM shop_sub_orders
                   WHERE status = 'Delivered' AND delivered_at IS NOT NULL"""
            )
            rows = cur.fetchall()
            from datetime import datetime, timedelta

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
        _release(connection)
    return completed_now


# ═══════════════════════════════════════════════════════════════════════
#  SHOP ANNOUNCEMENTS
# ═══════════════════════════════════════════════════════════════════════

def create_shop_announcement(shop_id: str, message: str) -> dict[str, Any] | None:
    """Create a shop announcement (shown as notification bar on student page)."""
    aid = f"ann_{secrets.token_hex(8)}"
    connection = _connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                """INSERT INTO shop_announcements (id, shop_id, message, is_active)
                   VALUES (%s, %s, %s, true) RETURNING *""",
                (aid, shop_id, message),
            )
            connection.commit()
            return cursor_row(cur)
    except Exception:
        connection.rollback()
        return None
    finally:
        _release(connection)


def list_shop_announcements(shop_id: str | None = None, active_only: bool = True) -> list[dict[str, Any]]:
    """All active (or shop-filtered) announcements."""
    connection = _connect()
    try:
        with connection.cursor() as cur:
            if shop_id:
                cur.execute(
                    "SELECT * FROM shop_announcements WHERE shop_id = %s ORDER BY created_at DESC",
                    (shop_id,),
                )
            else:
                if active_only:
                    cur.execute("SELECT * FROM shop_announcements WHERE is_active = true ORDER BY created_at DESC")
                else:
                    cur.execute("SELECT * FROM shop_announcements ORDER BY created_at DESC")
            return _rows_to_dicts(cur.fetchall())
    finally:
        _release(connection)


def toggle_shop_announcement(ann_id: str, is_active: bool) -> dict[str, Any] | None:
    """Toggle an announcement on/off."""
    connection = _connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE shop_announcements SET is_active = %s WHERE id = %s RETURNING *",
                (is_active, ann_id),
            )
            connection.commit()
            return cursor_row(cur)
    except Exception:
        connection.rollback()
        return None
    finally:
        _release(connection)


# ═══════════════════════════════════════════════════════════════════════
#  COMPLAINTS
# ═══════════════════════════════════════════════════════════════════════

def create_complaint(
    parent_order_id: str,
    student_name: str,
    student_phone: str,
    shop_id: str,
    shop_name: str,
    subject: str,
    message: str,
    sub_order_id: str = "",
    proof_url: str = "",
) -> dict[str, Any] | None:
    """File a student complaint against an order."""
    cid = f"cmp_{secrets.token_hex(8)}"
    connection = _connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                """INSERT INTO complaints (
                       id, parent_order_id, sub_order_id, student_name, student_phone,
                       shop_id, shop_name, subject, message, proof_url, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Open') RETURNING *""",
                (
                    cid, parent_order_id, sub_order_id, student_name, student_phone,
                    shop_id, shop_name, subject, message, proof_url,
                ),
            )
            connection.commit()
            return cursor_row(cur)
    except Exception:
        connection.rollback()
        return None
    finally:
        _release(connection)


def list_complaints(status: str | None = None) -> list[dict[str, Any]]:
    """All complaints (optional status filter)."""
    connection = _connect()
    try:
        with connection.cursor() as cur:
            if status:
                cur.execute("SELECT * FROM complaints WHERE status = %s ORDER BY created_at DESC", (status,))
            else:
                cur.execute("SELECT * FROM complaints ORDER BY created_at DESC")
            return _rows_to_dicts(cur.fetchall())
    finally:
        _release(connection)


def update_complaint(complaint_id: str, status: str, admin_notes: str = "") -> dict[str, Any] | None:
    """Update a complaint's status + admin note."""
    connection = _connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE complaints SET status = %s, admin_notes = %s WHERE id = %s RETURNING *",
                (status, admin_notes, complaint_id),
            )
            connection.commit()
            return cursor_row(cur)
    except Exception:
        connection.rollback()
        return None
    finally:
        _release(connection)


# ═══════════════════════════════════════════════════════════════════════
#  REFUNDS
# ═══════════════════════════════════════════════════════════════════════

def create_refund(
    parent_order_id: str,
    student_name: str,
    shop_name: str,
    original_amount: int,
    refund_amount: int,
    refund_type: str = "Full",
    sub_order_id: str = "",
    shop_id: str = "",
) -> dict[str, Any] | None:
    """Create a refund request."""
    rid = f"ref_{secrets.token_hex(8)}"
    connection = _connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                """INSERT INTO refunds (
                       id, parent_order_id, sub_order_id, student_name, shop_name,
                       original_amount, refund_amount, refund_type, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Pending') RETURNING *""",
                (
                    rid, parent_order_id, sub_order_id, student_name, shop_name,
                    original_amount, refund_amount, refund_type,
                ),
            )
            connection.commit()
            return cursor_row(cur)
    except Exception:
        connection.rollback()
        return None
    finally:
        _release(connection)


def list_refunds(status: str | None = None) -> list[dict[str, Any]]:
    """All refunds (optional status filter)."""
    connection = _connect()
    try:
        with connection.cursor() as cur:
            if status:
                cur.execute("SELECT * FROM refunds WHERE status = %s ORDER BY created_at DESC", (status,))
            else:
                cur.execute("SELECT * FROM refunds ORDER BY created_at DESC")
            return _rows_to_dicts(cur.fetchall())
    finally:
        _release(connection)


def update_refund(
    refund_id: str, status: str, refund_utr: str = "", admin_notes: str = ""
) -> dict[str, Any] | None:
    """Update a refund's status (mark processed/completed etc.)."""
    connection = _connect()
    try:
        with connection.cursor() as cur:
            completion_sql = (
                ", completed_at = NOW()" if status in ("Processed", "Completed") else ""
            )
            cur.execute(
                f"UPDATE refunds SET status = %s, refund_utr = %s, admin_notes = %s{completion_sql} WHERE id = %s RETURNING *",
                (status, refund_utr, admin_notes, refund_id),
            )
            connection.commit()
            return cursor_row(cur)
    except Exception:
        connection.rollback()
        return None
    finally:
        _release(connection)


# ═══════════════════════════════════════════════════════════════════════
#  SETTLEMENTS
# ═══════════════════════════════════════════════════════════════════════

def list_settlements(status: str | None = None) -> list[dict[str, Any]]:
    """All settlements (optional status filter)."""
    connection = _connect()
    try:
        with connection.cursor() as cur:
            if status:
                cur.execute("SELECT * FROM settlements WHERE status = %s ORDER BY created_at DESC", (status,))
            else:
                cur.execute("SELECT * FROM settlements ORDER BY created_at DESC")
            return _rows_to_dicts(cur.fetchall())
    finally:
        _release(connection)


def run_daily_settlements() -> list[dict[str, Any]]:
    """Process 9 PM settlements for all shops for today's delivered sub-orders."""
    dk = _day_key()
    connection = _connect()
    results: list[dict[str, Any]] = []
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT shop_id, shop_name FROM shop_sub_orders WHERE status IN ('Delivered', 'Completed') AND created_at::date = %s::date",
                (dk,),
            )
            shop_rows = _rows_to_dicts(cur.fetchall())
            for shop in shop_rows:
                sid = shop["shop_id"]
                cur.execute(
                    "SELECT COALESCE(SUM(subtotal), 0) AS gross FROM shop_sub_orders WHERE shop_id = %s AND status IN ('Delivered', 'Completed') AND created_at::date = %s::date",
                    (sid, dk),
                )
                gross = int(cursor_row(cur)["gross"])
                commission = round(gross * 0.05)
                settlement_id = f"set_{sid}_{dk}"
                cur.execute(
                    """INSERT INTO settlements (
                           id, shop_id, shop_name, date_key, gross_sales, commission_5pct,
                           refunds_adjusted, net_payable, cod_collected, status)
                       VALUES (%s, %s, %s, %s, %s, %s, 0, %s, 0, 'Pending')
                       ON CONFLICT (id) DO UPDATE SET
                           gross_sales = EXCLUDED.gross_sales,
                           commission_5pct = EXCLUDED.commission_5pct,
                           net_payable = EXCLUDED.net_payable
                       RETURNING *""",
                    (settlement_id, sid, shop["shop_name"], dk, gross, commission, gross - commission),
                )
                results.append(cursor_row(cur))
            connection.commit()
            return results
    except Exception:
        connection.rollback()
        return results
    finally:
        _release(connection)


# ═══════════════════════════════════════════════════════════════════════
#  MENU CHANGE REQUESTS
# ═══════════════════════════════════════════════════════════════════════

def create_menu_change_request(
    shop_id: str,
    product_id: str,
    change_type: str,
    old_value: str,
    new_value: str,
    field_name: str = "",
) -> dict[str, Any] | None:
    """A shop asks admin to change a menu field (price, availability...)."""
    mid = f"mcr_{secrets.token_hex(8)}"
    connection = _connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                """INSERT INTO menu_change_requests (
                       id, shop_id, product_id, change_type, field_name, old_value, new_value, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'Pending') RETURNING *""",
                (mid, shop_id, product_id, change_type, field_name, old_value, new_value),
            )
            connection.commit()
            return cursor_row(cur)
    except Exception:
        connection.rollback()
        return None
    finally:
        _release(connection)


def list_menu_change_requests(status: str | None = None) -> list[dict[str, Any]]:
    """Menu change requests (optional status filter)."""
    connection = _connect()
    try:
        with connection.cursor() as cur:
            if status:
                cur.execute("SELECT * FROM menu_change_requests WHERE status = %s ORDER BY created_at DESC", (status,))
            else:
                cur.execute("SELECT * FROM menu_change_requests ORDER BY created_at DESC")
            return _rows_to_dicts(cur.fetchall())
    finally:
        _release(connection)


def update_menu_change_request(req_id: str, status: str, admin_notes: str = "") -> dict[str, Any] | None:
    """Approve/reject a menu change request."""
    connection = _connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE menu_change_requests SET status = %s, admin_notes = %s, reviewed_at = NOW() WHERE id = %s RETURNING *",
                (status, admin_notes, req_id),
            )
            connection.commit()
            return cursor_row(cur)
    except Exception:
        connection.rollback()
        return None
    finally:
        _release(connection)


# ═══════════════════════════════════════════════════════════════════════
#  AUDIT + WHATSAPP LOGS
# ═══════════════════════════════════════════════════════════════════════

def add_audit_log(
    actor: str,
    actor_role: str,
    action: str,
    target_type: str = "",
    target_id: str = "",
    details: str = "",
) -> None:
    connection = _connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                """INSERT INTO audit_logs (actor, actor_role, action, target_type, target_id, details)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (actor, actor_role, action, target_type, target_id, details),
            )
            connection.commit()
    except Exception:
        connection.rollback()
    finally:
        _release(connection)


def list_audit_logs(limit: int = 200) -> list[dict[str, Any]]:
    connection = _connect()
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT %s", (limit,))
            return _rows_to_dicts(cur.fetchall())
    finally:
        _release(connection)


def list_whatsapp_logs(limit: int = 100) -> list[dict[str, Any]]:
    connection = _connect()
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT * FROM whatsapp_logs ORDER BY created_at DESC LIMIT %s", (limit,))
            return _rows_to_dicts(cur.fetchall())
    finally:
        _release(connection)


def log_sms(
    sub_order_id: str = "",
    phone: str = "",
    message: str = "",
    status: str = "Sent",
    direction: str = "out",
) -> dict[str, Any] | None:
    """Persist one SMS (out = sent to a phone, in = received from a phone)."""
    connection = _connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                """INSERT INTO sms_logs (sub_order_id, phone, message, direction, status)
                   VALUES (%s, %s, %s, %s, %s) RETURNING *""",
                (sub_order_id, phone or "", message or "", direction, status),
            )
            return _rows_to_dicts(cur.fetchall())[0]
    finally:
        _release(connection)


def list_sms_logs(limit: int = 100) -> list[dict[str, Any]]:
    connection = _connect()
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT * FROM sms_logs ORDER BY created_at DESC LIMIT %s", (limit,))
            return _rows_to_dicts(cur.fetchall())
    finally:
        _release(connection)
