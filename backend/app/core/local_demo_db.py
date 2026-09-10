"""
Local SQLite data store for a runnable development build.

This keeps the app usable without a MongoDB service. The production MongoDB
routes are still present, but the frontend can use these local endpoints during
development.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import settings


class _NamedRow(dict):
    def __init__(self, columns: list[str], values: Any):
        super().__init__(zip(columns, values))
        self._values = tuple(values)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


class _NamedRowCursor:
    def __init__(self, cursor: Any):
        self._cursor = cursor

    def _row_to_dict(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        columns = [column[0] for column in self._cursor.description or []]
        if not columns:
            return row
        return _NamedRow(columns, row)

    @property
    def lastrowid(self) -> Any:
        return getattr(self._cursor, "lastrowid", None)

    def fetchone(self) -> dict[str, Any] | None:
        return self._row_to_dict(self._cursor.fetchone())

    def fetchall(self) -> list[dict[str, Any]]:
        return [self._row_to_dict(row) for row in self._cursor.fetchall()]


class _NamedRowConnection:
    def __init__(self, connection: Any):
        self._connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self._connection.commit()
        self._connection.close()
        return False

    def execute(self, *args, **kwargs) -> _NamedRowCursor:
        return _NamedRowCursor(self._connection.execute(*args, **kwargs))

    def executemany(self, *args, **kwargs) -> _NamedRowCursor:
        return _NamedRowCursor(self._connection.executemany(*args, **kwargs))

    def executescript(self, *args, **kwargs) -> _NamedRowCursor:
        return _NamedRowCursor(self._connection.executescript(*args, **kwargs))

    def commit(self) -> None:
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()


def _db_path() -> Path:
    path = Path(settings.LOCAL_DB_PATH)
    if not path.is_absolute():
        # Resolve relative to the backend package dir (backend/), not the
        # process cwd — so the DB is stable no matter where the app is started
        # from (e.g. pytest, uvicorn from another directory, cron jobs).
        path = Path(__file__).resolve().parents[2] / path
    return path


def _connect() -> Any:
    if settings.USE_TURSO_DB:
        import libsql

        return _NamedRowConnection(
            libsql.connect(
                settings.TURSO_DATABASE_URL,
                auth_token=settings.TURSO_AUTH_TOKEN,
            )
        )

    connection = sqlite3.connect(_db_path(), timeout=10)
    connection.row_factory = sqlite3.Row
    # ─── Speed: WAL journaling keeps readers and the writer from blocking each
    # other, and NORMAL synchronous gives crash-safe-enough durability while
    # skipping the fsync-per-write that makes SQLite feel slow under load. ───
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA busy_timeout=8000")
    return connection


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]





def _day_key(now: str | None = None) -> str:
    """YYYY-MM-DD key for daily resets (token, batch stock, settlements)."""
    from datetime import datetime
    if now:
        return now[:10]
    return datetime.now().strftime("%Y-%m-%d")


def get_current_batch(now: str | None = None) -> str:
    """Determine current delivery batch by time of day. Afternoon window is
    9:00-12:30 (delivery 1:00-1:30 PM); Night window is up to 6 PM (delivery
    7:30 PM). Returns 'Afternoon' or 'Night'."""
    from datetime import datetime
    try:
        if now:
            t = datetime.strptime(now[:19], "%Y-%m-%d %H:%M:%S")
        else:
            t = datetime.now()
    except ValueError:
        return "Night"
    hour = t.hour + t.minute / 60.0
    if hour < 12.5:
        return "Afternoon"
    return "Night"


def get_default_stock(product: dict[str, Any]) -> int:
    """Default per-batch stock for a product (products.inventory is the cap)."""
    base = int(product.get("inventory") or 0)
    if base <= 0:
        return 0
    return base


def get_product_stock(product_id: str, batch_type: str, date_key: str | None = None) -> int:
    """Current available stock for a product in a batch. Falls back to full
    inventory when no explicit stock row exists yet."""
    date_key = date_key or _day_key()
    with _connect() as connection:
        row = connection.execute(
            "SELECT current_stock FROM product_stock WHERE product_id = ? AND batch_type = ? AND date_key = ? ORDER BY id DESC LIMIT 1",
            (product_id, batch_type, date_key),
        ).fetchone()
        if row:
            return int(row["current_stock"])
        product = connection.execute("SELECT inventory FROM products WHERE id = ?", (product_id,)).fetchone()
        return int(product["inventory"]) if product else 0


def init_batch_stock(product_id: str, batch_type: str, default_stock: int, date_key: str | None = None) -> None:
    """Ensure batch stock exists for today's batch. Reinitialized daily."""
    date_key = date_key or _day_key()
    with _connect() as connection:
        existing = connection.execute(
            "SELECT id FROM product_stock WHERE product_id = ? AND batch_type = ? AND date_key = ?",
            (product_id, batch_type, date_key),
        ).fetchone()
        if existing:
            return
        connection.execute(
            "INSERT INTO product_stock (product_id, batch_type, default_stock, current_stock, date_key) VALUES (?, ?, ?, ?, ?)",
            (product_id, batch_type, default_stock, default_stock, date_key),
        )


def consume_batch_stock(product_id: str, batch_type: str, qty: int, date_key: str | None = None) -> bool:
    """Atomically decrement stock. Returns False if insufficient."""
    date_key = date_key or _day_key()
    with _connect() as connection:
        product = connection.execute("SELECT inventory FROM products WHERE id = ?", (product_id,)).fetchone()
        if not product:
            return False
        row = connection.execute(
            "SELECT id, current_stock FROM product_stock WHERE product_id = ? AND batch_type = ? AND date_key = ? ORDER BY id DESC LIMIT 1",
            (product_id, batch_type, date_key),
        ).fetchone()
        if row:
            stock_id, current = row["id"], int(row["current_stock"])
            if current < qty:
                return False
            connection.execute(
                "UPDATE product_stock SET current_stock = current_stock - ? WHERE id = ?",
                (qty, stock_id),
            )
        else:
            inventory = int(product["inventory"] or 0)
            if inventory < qty:
                return False
            connection.execute(
                "INSERT INTO product_stock (product_id, batch_type, default_stock, current_stock, date_key) VALUES (?, ?, ?, ?, ?)",
                (product_id, batch_type, inventory - qty, inventory - qty, date_key),
            )
        return True


def release_batch_stock(product_id: str, batch_type: str, qty: int, date_key: str | None = None) -> None:
    date_key = date_key or _day_key()
    with _connect() as connection:
        row = connection.execute(
            "SELECT id, current_stock FROM product_stock WHERE product_id = ? AND batch_type = ? AND date_key = ? ORDER BY id DESC LIMIT 1",
            (product_id, batch_type, date_key),
        ).fetchone()
        if row:
            connection.execute(
                "UPDATE product_stock SET current_stock = current_stock + ? WHERE id = ?",
                (qty, row["id"]),
            )


def get_next_token() -> int:
    """Next token number. Starts at #18 each day and daily resets to 18."""
    date_key = _day_key()
    with _connect() as connection:
        value = connection.execute(
            "SELECT value FROM app_settings WHERE key = ?", (f"token_base_{date_key}",)
        ).fetchone()
        if value:
            return int(value["value"])
        connection.execute(
            "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
            (f"token_base_{date_key}", "18"),
        )
        return 18


def consume_token() -> int:
    """Allocate the next token and record it in today's counter."""
    date_key = _day_key()
    with _connect() as connection:
        token = get_next_token()
        connection.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
            (f"token_base_{date_key}", str(token + 1)),
        )
    return token


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


def _column_exists(connection: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row["name"] == column_name for row in rows)


def init_local_demo_db() -> None:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS shops (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                rating REAL NOT NULL,
                opening_time TEXT NOT NULL,
                closing_time TEXT NOT NULL,
                present INTEGER NOT NULL,
                status TEXT NOT NULL,
                approval_status TEXT NOT NULL,
                shopkeeper_email TEXT DEFAULT '',
                shopkeeper_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                upi_id TEXT DEFAULT '',
                upi_enabled INTEGER NOT NULL DEFAULT 1,
                cod_enabled INTEGER NOT NULL DEFAULT 1,
                orders_today INTEGER NOT NULL,
                revenue_today INTEGER NOT NULL,
                current_token INTEGER NOT NULL,
                is_removed INTEGER NOT NULL DEFAULT 0,
                admin_dues_balance INTEGER NOT NULL DEFAULT 0,
                admin_dues_last_paid_at TEXT
            );

            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                shop_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                price INTEGER NOT NULL,
                pending_price INTEGER,
                category TEXT NOT NULL,
                inventory INTEGER NOT NULL,
                prep_time INTEGER NOT NULL,
                available INTEGER NOT NULL,
                FOREIGN KEY (shop_id) REFERENCES shops(id)
            );

            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                token INTEGER NOT NULL,
                student_name TEXT NOT NULL,
                student_phone TEXT NOT NULL,
                shop_id TEXT NOT NULL,
                shop_name TEXT NOT NULL,
                items TEXT NOT NULL,
                subtotal INTEGER NOT NULL DEFAULT 0,
                service_fee INTEGER NOT NULL DEFAULT 0,
                tax INTEGER NOT NULL DEFAULT 0,
                delivery_fee INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL,
                delivery_location TEXT NOT NULL,
                delivery_slot TEXT NOT NULL,
                status TEXT NOT NULL,
                payment_method TEXT NOT NULL DEFAULT 'UPI',
                created_at TEXT NOT NULL,
                FOREIGN KEY (shop_id) REFERENCES shops(id)
            );

            CREATE TABLE IF NOT EXISTS payments (
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                method TEXT NOT NULL,
                status TEXT NOT NULL,
                utr_number TEXT,
                screenshot_name TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (order_id) REFERENCES orders(id)
            );

            CREATE TABLE IF NOT EXISTS tickets (
                id TEXT PRIMARY KEY,
                ticket_number TEXT NOT NULL,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone_number TEXT NOT NULL,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                order_id TEXT,
                status TEXT,
                target_role TEXT DEFAULT '',
                is_read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                name TEXT NOT NULL,
                email TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                role TEXT NOT NULL CHECK(role IN ('student','shopkeeper','admin')),
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                name TEXT NOT NULL,
                email TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                role TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS share_payments (
                id TEXT PRIMARY KEY,
                shop_id TEXT NOT NULL,
                shop_name TEXT NOT NULL DEFAULT '',
                amount INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'Pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                paid_at TEXT
            );

            CREATE TABLE IF NOT EXISTS push_subscriptions (
                endpoint TEXT PRIMARY KEY,
                shop_id TEXT NOT NULL,
                p256dh TEXT NOT NULL,
                auth TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_push_subscriptions_shop_id ON push_subscriptions (shop_id);

            CREATE TABLE IF NOT EXISTS password_resets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                otp TEXT NOT NULL,
                step INTEGER NOT NULL DEFAULT 1,
                expires_at TEXT NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            -- ─── Site feedback / bug reports: students test the site and
            -- contribute bugs + improvement ideas; the admin reviews them on
            -- the Feedback page (who sent it, what was said, status). ───
            CREATE TABLE IF NOT EXISTS site_feedback (
                id TEXT PRIMARY KEY,
                user_id INTEGER,
                username TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'Bug',
                subject TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL DEFAULT '',
                page TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Open',
                -- Where the contribution came from: 'User' = submitted by a
                -- real student through the portal; 'ATS' = generated by the
                -- automated test suite. The admin Feedback page filters on this.
                source TEXT NOT NULL DEFAULT 'User',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_site_feedback_status ON site_feedback (status);
            CREATE INDEX IF NOT EXISTS idx_site_feedback_user ON site_feedback (user_id);

            -- ─── Indexes: every hot query below ships through an index instead
            -- of a full table scan (big speed win as order/product volume grows). ───
            CREATE INDEX IF NOT EXISTS idx_orders_shop_id ON orders (shop_id);
            CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders (created_at);
            CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status);
            CREATE INDEX IF NOT EXISTS idx_products_shop_id ON products (shop_id);
            CREATE INDEX IF NOT EXISTS idx_payments_order_id ON payments (order_id);
            CREATE INDEX IF NOT EXISTS idx_notifications_target_role ON notifications (target_role, id);
            CREATE INDEX IF NOT EXISTS idx_users_role ON users (role);
            CREATE INDEX IF NOT EXISTS idx_share_payments_shop_id ON share_payments (shop_id);
            CREATE INDEX IF NOT EXISTS idx_password_resets_username ON password_resets (username, used);

            -- ─── Shop reviews: students rate shops after ordering. ───
            CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY,
                user_id INTEGER,
                username TEXT NOT NULL DEFAULT '',
                student_name TEXT NOT NULL DEFAULT '',
                shop_id TEXT NOT NULL DEFAULT '',
                shop_name TEXT NOT NULL DEFAULT '',
                rating INTEGER NOT NULL DEFAULT 5,
                comment TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_reviews_shop_id ON reviews (shop_id);

            -- ─── Multi-shop order system ───
            CREATE TABLE IF NOT EXISTS parent_orders (
                id TEXT PRIMARY KEY,
                token INTEGER NOT NULL,
                student_name TEXT NOT NULL,
                student_phone TEXT NOT NULL,
                student_email TEXT NOT NULL DEFAULT '',
                student_id TEXT NOT NULL DEFAULT '',
                total INTEGER NOT NULL DEFAULT 0,
                payment_method TEXT NOT NULL DEFAULT 'UTR',
                payment_status TEXT NOT NULL DEFAULT 'Pending',
                delivery_location TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_parent_orders_token ON parent_orders (token);
            CREATE INDEX IF NOT EXISTS idx_parent_orders_student ON parent_orders (student_name);

            CREATE TABLE IF NOT EXISTS shop_sub_orders (
                id TEXT PRIMARY KEY,
                parent_order_id TEXT NOT NULL,
                shop_id TEXT NOT NULL,
                shop_name TEXT NOT NULL,
                shop_phone TEXT NOT NULL DEFAULT '',
                shop_whatsapp TEXT NOT NULL DEFAULT '',
                token INTEGER NOT NULL,
                items_summary TEXT NOT NULL DEFAULT '',
                subtotal INTEGER NOT NULL DEFAULT 0,
                commission_5pct INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'Pending',
                accepted_at TEXT,
                prepared_at TEXT,
                ready_at TEXT,
                completed_at TEXT,
                delivered_at TEXT,
                rejection_reason TEXT NOT NULL DEFAULT '',
                cancellation_reason TEXT NOT NULL DEFAULT '',
                batch_type TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (parent_order_id) REFERENCES parent_orders(id),
                FOREIGN KEY (shop_id) REFERENCES shops(id)
            );
            CREATE INDEX IF NOT EXISTS idx_sub_orders_parent ON shop_sub_orders (parent_order_id);
            CREATE INDEX IF NOT EXISTS idx_sub_orders_shop ON shop_sub_orders (shop_id);
            CREATE INDEX IF NOT EXISTS idx_sub_orders_status ON shop_sub_orders (status);

            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sub_order_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                product_name TEXT NOT NULL,
                price INTEGER NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                total INTEGER NOT NULL,
                FOREIGN KEY (sub_order_id) REFERENCES shop_sub_orders(id)
            );
            CREATE INDEX IF NOT EXISTS idx_order_items_sub ON order_items (sub_order_id);

            -- ─── Delivery batches ───
            CREATE TABLE IF NOT EXISTS delivery_batches (
                id TEXT PRIMARY KEY,
                batch_type TEXT NOT NULL,
                order_start TEXT NOT NULL,
                order_end TEXT NOT NULL,
                delivery_start TEXT NOT NULL,
                delivery_end TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            -- ─── Per-batch product stock ───
            CREATE TABLE IF NOT EXISTS product_stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL,
                batch_type TEXT NOT NULL,
                default_stock INTEGER NOT NULL DEFAULT 0,
                current_stock INTEGER NOT NULL DEFAULT 0,
                date_key TEXT NOT NULL,
                FOREIGN KEY (product_id) REFERENCES products(id)
            );
            CREATE INDEX IF NOT EXISTS idx_product_stock_product ON product_stock (product_id, batch_type, date_key);

            -- ─── Complaints ───
            CREATE TABLE IF NOT EXISTS complaints (
                id TEXT PRIMARY KEY,
                parent_order_id TEXT NOT NULL,
                sub_order_id TEXT NOT NULL DEFAULT '',
                student_name TEXT NOT NULL DEFAULT '',
                student_phone TEXT NOT NULL DEFAULT '',
                shop_id TEXT NOT NULL DEFAULT '',
                shop_name TEXT NOT NULL DEFAULT '',
                subject TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL DEFAULT '',
                proof_url TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'New',
                admin_notes TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (parent_order_id) REFERENCES parent_orders(id)
            );
            CREATE INDEX IF NOT EXISTS idx_complaints_status ON complaints (status);

            -- ─── Refunds ───
            CREATE TABLE IF NOT EXISTS refunds (
                id TEXT PRIMARY KEY,
                parent_order_id TEXT NOT NULL,
                sub_order_id TEXT NOT NULL DEFAULT '',
                student_name TEXT NOT NULL DEFAULT '',
                shop_name TEXT NOT NULL DEFAULT '',
                original_amount INTEGER NOT NULL DEFAULT 0,
                refund_amount INTEGER NOT NULL DEFAULT 0,
                refund_type TEXT NOT NULL DEFAULT 'Full',
                refund_utr TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Pending',
                admin_notes TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                FOREIGN KEY (parent_order_id) REFERENCES parent_orders(id)
            );
            CREATE INDEX IF NOT EXISTS idx_refunds_status ON refunds (status);

            -- ─── Daily settlements ───
            CREATE TABLE IF NOT EXISTS settlements (
                id TEXT PRIMARY KEY,
                shop_id TEXT NOT NULL,
                shop_name TEXT NOT NULL DEFAULT '',
                date_key TEXT NOT NULL,
                gross_sales INTEGER NOT NULL DEFAULT 0,
                commission_5pct INTEGER NOT NULL DEFAULT 0,
                refunds_adjusted INTEGER NOT NULL DEFAULT 0,
                net_payable INTEGER NOT NULL DEFAULT 0,
                cod_collected INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'Pending',
                settlement_utr TEXT NOT NULL DEFAULT '',
                admin_notes TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                FOREIGN KEY (shop_id) REFERENCES shops(id)
            );
            CREATE INDEX IF NOT EXISTS idx_settlements_shop ON settlements (shop_id, date_key);

            -- ─── Menu change requests (approval workflow) ───
            CREATE TABLE IF NOT EXISTS menu_change_requests (
                id TEXT PRIMARY KEY,
                shop_id TEXT NOT NULL,
                product_id TEXT NOT NULL DEFAULT '',
                change_type TEXT NOT NULL,
                field_name TEXT NOT NULL DEFAULT '',
                old_value TEXT NOT NULL DEFAULT '',
                new_value TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Pending',
                admin_notes TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TEXT,
                FOREIGN KEY (shop_id) REFERENCES shops(id)
            );
            CREATE INDEX IF NOT EXISTS idx_menu_changes_shop ON menu_change_requests (shop_id, status);

            -- ─── Shop notification bar (shop can post announcements to students) ───
            CREATE TABLE IF NOT EXISTS shop_announcements (
                id TEXT PRIMARY KEY,
                shop_id TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (shop_id) REFERENCES shops(id)
            );
            CREATE INDEX IF NOT EXISTS idx_shop_announcements_shop ON shop_announcements (shop_id, is_active);

            -- ─── Student favorites ───
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_name TEXT NOT NULL DEFAULT '',
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_favorites_student ON favorites (student_name, target_type);

            -- ─── WhatsApp message logs ───
            CREATE TABLE IF NOT EXISTS whatsapp_logs (
                id TEXT PRIMARY KEY,
                sub_order_id TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Sent',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            -- ─── SMS logs (order confirm/reject via phone text) ───
            CREATE TABLE IF NOT EXISTS sms_logs (
                id TEXT PRIMARY KEY,
                sub_order_id TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL DEFAULT '',
                direction TEXT NOT NULL DEFAULT 'out',
                status TEXT NOT NULL DEFAULT 'Sent',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            -- ─── Shop ordering position (admin-controlled) ───
            -- Added to shops table via ALTER below.

            -- ─── Audit logs ───
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_user TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL DEFAULT '',
                entity_type TEXT NOT NULL DEFAULT '',
                entity_id TEXT NOT NULL DEFAULT '',
                old_value TEXT NOT NULL DEFAULT '',
                new_value TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs (entity_type, entity_id);

            -- ─── Shop order lock time (auto-delivery after 30 min) ───
            -- added to shop_sub_orders via delivered_at/completed_at timestamps.

            -- ─── Duplicate UTR protection ───
            CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_utr_unique ON payments (utr_number) WHERE utr_number IS NOT NULL AND utr_number != '';
            """
        )

        if not _column_exists(connection, "payments", "screenshot_name"):
            connection.execute("ALTER TABLE payments ADD COLUMN screenshot_name TEXT")
        if not _column_exists(connection, "shops", "shopkeeper_email"):
            connection.execute("ALTER TABLE shops ADD COLUMN shopkeeper_email TEXT DEFAULT ''")
        if not _column_exists(connection, "users", "email"):
            connection.execute("ALTER TABLE users ADD COLUMN email TEXT DEFAULT ''")
        if not _column_exists(connection, "users", "phone"):
            connection.execute("ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''")
        if not _column_exists(connection, "shops", "upi_id"):
            connection.execute("ALTER TABLE shops ADD COLUMN upi_id TEXT DEFAULT ''")
        if not _column_exists(connection, "shops", "upi_enabled"):
            connection.execute("ALTER TABLE shops ADD COLUMN upi_enabled INTEGER NOT NULL DEFAULT 1")
        if not _column_exists(connection, "shops", "cod_enabled"):
            connection.execute("ALTER TABLE shops ADD COLUMN cod_enabled INTEGER NOT NULL DEFAULT 1")
        if not _column_exists(connection, "shops", "is_removed"):
            connection.execute("ALTER TABLE shops ADD COLUMN is_removed INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(connection, "shops", "admin_dues_balance"):
            connection.execute("ALTER TABLE shops ADD COLUMN admin_dues_balance INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(connection, "shops", "admin_dues_last_paid_at"):
            connection.execute("ALTER TABLE shops ADD COLUMN admin_dues_last_paid_at TEXT")
        if not _column_exists(connection, "shops", "ordering_position"):
            connection.execute("ALTER TABLE shops ADD COLUMN ordering_position INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(connection, "shops", "whatsapp_number"):
            connection.execute("ALTER TABLE shops ADD COLUMN whatsapp_number TEXT DEFAULT ''")
        if not _column_exists(connection, "shops", "is_featured"):
            connection.execute("ALTER TABLE shops ADD COLUMN is_featured INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(connection, "shops", "shop_image"):
            connection.execute("ALTER TABLE shops ADD COLUMN shop_image TEXT DEFAULT ''")
        if not _column_exists(connection, "orders", "parent_order_id"):
            connection.execute("ALTER TABLE orders ADD COLUMN parent_order_id TEXT DEFAULT ''")
        if not _column_exists(connection, "orders", "batch_type"):
            connection.execute("ALTER TABLE orders ADD COLUMN batch_type TEXT DEFAULT ''")
        if not _column_exists(connection, "orders", "is_combo"):
            connection.execute("ALTER TABLE orders ADD COLUMN is_combo INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(connection, "orders", "subtotal"):
            connection.execute("ALTER TABLE orders ADD COLUMN subtotal INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(connection, "orders", "service_fee"):
            connection.execute("ALTER TABLE orders ADD COLUMN service_fee INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(connection, "orders", "tax"):
            connection.execute("ALTER TABLE orders ADD COLUMN tax INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(connection, "orders", "delivery_fee"):
            connection.execute("ALTER TABLE orders ADD COLUMN delivery_fee INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(connection, "notifications", "target_role"):
            connection.execute("ALTER TABLE notifications ADD COLUMN target_role TEXT DEFAULT ''")
        if not _column_exists(connection, "orders", "payment_method"):
            connection.execute("ALTER TABLE orders ADD COLUMN payment_method TEXT NOT NULL DEFAULT 'UPI'")
        if not _column_exists(connection, "password_resets", "attempts"):
            connection.execute("ALTER TABLE password_resets ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(connection, "site_feedback", "subject"):
            connection.execute("ALTER TABLE site_feedback ADD COLUMN subject TEXT NOT NULL DEFAULT ''")
        if not _column_exists(connection, "site_feedback", "page"):
            connection.execute("ALTER TABLE site_feedback ADD COLUMN page TEXT NOT NULL DEFAULT ''")
        if not _column_exists(connection, "site_feedback", "source"):
            connection.execute("ALTER TABLE site_feedback ADD COLUMN source TEXT NOT NULL DEFAULT 'User'")
            # One-time backfill: every row that existed BEFORE this column was
            # added was generated by the automated test suite (the feature
            # didn't exist for real users yet) → tag them all as ATS.
            connection.execute("UPDATE site_feedback SET source = 'ATS'")
        # The index lives OUTSIDE the big executescript so it can only be
        # created after the ALTER fallback above guarantees the column exists
        # (legacy databases fail otherwise).
        connection.execute("CREATE INDEX IF NOT EXISTS idx_site_feedback_source ON site_feedback (source)")

        # One account per email (case-insensitive, non-empty only so legacy
        # rows with a blank email aren't blocked). Created OUTSIDE the big
        # executescript so a legacy database that already contains duplicate
        # emails logs the failure instead of breaking app startup.
        try:
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users (LOWER(email)) WHERE email != ''"
            )
        except sqlite3.Error:
            pass  # legacy duplicate emails — the app-level check still blocks new ones

        # No seed data. All shops, products, and orders are created by real users.

        # ─── Seed default delivery batches (Afternoon / Night). ───
        connection.execute(
            """
            INSERT OR IGNORE INTO delivery_batches
            (id, batch_type, order_start, order_end, delivery_start, delivery_end, is_active)
            VALUES
            ('batch-afternoon', 'Afternoon', '09:00', '12:30', '13:00', '13:30', 1),
            ('batch-night', 'Night', '13:00', '18:00', '19:30', '19:45', 1)
            """
        )

        # Seed default delivery batches (Afternoon + Night).
        connection.execute(
            """INSERT OR IGNORE INTO delivery_batches
            (id, batch_type, order_start, order_end, delivery_start, delivery_end, is_active)
            VALUES
            ('batch-afternoon', 'Afternoon', '09:00', '12:30', '13:00', '13:30', 1),
            ('batch-night', 'Night', '13:00', '18:00', '19:30', '19:45', 1)
            """
        )


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
    with _connect() as connection:
        existing = connection.execute(
            "SELECT id FROM users WHERE username = ?",
            (username.lower(),),
        ).fetchone()
        if existing:
            return None, "username"

        if normalized_email:
            existing_email = connection.execute(
                "SELECT id FROM users WHERE LOWER(email) = ? AND email != ''",
                (normalized_email.lower(),),
            ).fetchone()
            if existing_email:
                return None, "email"

        try:
            cursor = connection.execute(
                "INSERT INTO users (username, password_hash, name, email, phone, role) VALUES (?, ?, ?, ?, ?, ?)",
                (username.lower(), password_hash, name, normalized_email, phone, role),
            )
        except sqlite3.IntegrityError:
            # Race backstop: another request inserted the same email/username
            # between our checks and the insert — the unique index guarantees
            # consistency. Re-check to report the RIGHT conflict.
            if normalized_email:
                existing_email = connection.execute(
                    "SELECT id FROM users WHERE LOWER(email) = ? AND email != ''",
                    (normalized_email.lower(),),
                ).fetchone()
                if existing_email:
                    return None, "email"
            return None, "username"

        row = connection.execute(
            "SELECT id, username, name, email, phone, role, created_at FROM users WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return dict(row), None


def get_user_by_username(username: str) -> dict[str, Any] | None:
    """Get full user record (including password_hash) by username."""
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE username = ?",
            (username.lower(),),
        ).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    """Get user by id (without password_hash)."""
    with _connect() as connection:
        row = connection.execute(
            "SELECT id, username, name, email, phone, role, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def save_session(email: str, name: str, role: str) -> dict[str, Any]:
    with _connect() as connection:
        existing = connection.execute(
            "SELECT id FROM sessions WHERE email = ? AND role = ? ORDER BY id DESC LIMIT 1",
            (email, role),
        ).fetchone()
        if existing:
            connection.execute(
                "UPDATE sessions SET name = ?, created_at = CURRENT_TIMESTAMP WHERE id = ?",
                (name, existing["id"]),
            )
            row = connection.execute(
                "SELECT id, email, name, role, created_at FROM sessions WHERE id = ?",
                (existing["id"],),
            ).fetchone()
            return dict(row)

        cursor = connection.execute(
            "INSERT INTO sessions (email, name, role) VALUES (?, ?, ?)",
            (email, name, role),
        )
        row = connection.execute(
            "SELECT id, email, name, role, created_at FROM sessions WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return dict(row)


def list_shops(public_only: bool = False) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute("SELECT * FROM shops ORDER BY rating DESC").fetchall()
        shops = _rows_to_dicts(rows)
        if public_only:
            # Students see every APPROVED shop (open or closed) so they can browse
            # menus and see opening hours. Ordering is still blocked server-side
            # for shops that are closed / not accepting orders.
            return [shop for shop in shops if shop.get("approval_status") == "Approved" and shop.get("is_removed", 0) != 1]
        return shops


def get_shop(shop_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
        return dict(row) if row else None


def get_shop_by_shopkeeper_email(email: str) -> dict[str, Any] | None:
    """Get a vendor's shop by shopkeeper email (avoids scanning the whole shops
    table on every vendor request)."""
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM shops WHERE LOWER(shopkeeper_email) = ? LIMIT 1",
            (email.lower(),),
        ).fetchone()
        return dict(row) if row else None


def create_shop(values: dict[str, Any]) -> dict[str, Any]:
    with _connect() as connection:
        next_id = connection.execute("SELECT COUNT(*) + 1 FROM shops").fetchone()[0]
        shop_id = f"s{next_id}"
        connection.execute(
            """
            INSERT INTO shops (
                id, name, category, description, rating, opening_time,
                closing_time, present, status, approval_status, shopkeeper_email,
                shopkeeper_name, phone, upi_id, orders_today, revenue_today, current_token,
                is_removed, admin_dues_balance, admin_dues_last_paid_at,
                upi_enabled, cod_enabled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                shop_id,
                values["name"],
                values["category"],
                values.get("description", ""),
                0,
                values.get("opening_time", "09:00 AM"),
                values.get("closing_time", "09:00 PM"),
                0,
                "Closed",
                "Pending Approval",
                values.get("shopkeeper_email", ""),
                values["shopkeeper_name"],
                values["phone"],
                values.get("upi_id", ""),
                0,
                0,
                18,
                0,
                0,
                None,
                values.get("upi_enabled", 1),
                values.get("cod_enabled", 1),
            ),
        )
        row = connection.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
        return dict(row)


def update_shop(shop_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
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
    }
    updates = {key: value for key, value in values.items() if key in allowed_fields and value is not None}
    if not updates:
        return get_shop(shop_id)

    if "present" in updates:
        updates["present"] = 1 if updates["present"] else 0
        # The vendor UI has a single Start/Stop toggle. Keep the separate
        # ``status`` field in sync so students see Open/Closed consistently
        # (both fields are required by the orderability check).
        if "status" not in updates:
            updates["status"] = "Open" if updates["present"] else "Closed"

    if "approval_status" in updates and updates["approval_status"] in {"Suspended", "Removed"}:
        updates["present"] = 0
        updates["status"] = "Closed"

    assignments = ", ".join(f"{field} = ?" for field in updates)
    params = [*updates.values(), shop_id]
    with _connect() as connection:
        connection.execute(f"UPDATE shops SET {assignments} WHERE id = ?", params)
        row = connection.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
        return dict(row) if row else None


def suspend_shop(shop_id: str) -> dict[str, Any] | None:
    return update_shop(shop_id, {"approval_status": "Suspended", "present": False, "status": "Closed"})


def remove_shop(shop_id: str) -> dict[str, Any] | None:
    return update_shop(shop_id, {"approval_status": "Removed", "present": False, "status": "Closed", "is_removed": True})


def pay_admin_dues(shop_id: str, amount: int | None = None) -> dict[str, Any] | None:
    with _connect() as connection:
        shop = connection.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
        if not shop:
            return None
        current_balance = int(shop.get("admin_dues_balance", 0) or 0)
        pay_amount = amount if amount is not None else current_balance
        new_balance = max(0, current_balance - pay_amount)
        connection.execute(
            "UPDATE shops SET admin_dues_balance = ?, admin_dues_last_paid_at = ? WHERE id = ?",
            (new_balance, datetime.now().isoformat(), shop_id),
        )
        row = connection.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
        return dict(row) if row else None


# ─── Admin share payments (5% of vendor daily earnings → admin) ───


def record_share_payment(shop_id: str, amount: int) -> dict[str, Any] | None:
    """Record a vendor's share payment to the admin.

    When the vendor taps Pay, the UPI app opens to the admin's UPI ID. We log a
    Pending record here; the admin marks it Received once the money lands.
    Returns an existing pending payment for today if one already exists."""
    with _connect() as connection:
        existing = connection.execute(
            "SELECT * FROM share_payments WHERE shop_id = ? AND status = 'Pending' AND substr(created_at, 1, 10) = date('now') ORDER BY created_at DESC LIMIT 1",
            (shop_id,),
        ).fetchone()
        if existing:
            return dict(existing)
        shop = connection.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
        if not shop:
            return None
        next_id = connection.execute("SELECT COUNT(*) + 1 FROM share_payments").fetchone()[0]
        payment_id = f"sp{next_id}"
        connection.execute(
            "INSERT INTO share_payments (id, shop_id, shop_name, amount, status) VALUES (?, ?, ?, ?, 'Pending')",
            (payment_id, shop_id, shop["name"], int(amount)),
        )
        connection.execute(
            "UPDATE shops SET admin_dues_last_paid_at = ? WHERE id = ?",
            (datetime.now().isoformat(), shop_id),
        )
        row = connection.execute("SELECT * FROM share_payments WHERE id = ?", (payment_id,)).fetchone()
        return dict(row) if row else None


def list_share_payments() -> list[dict[str, Any]]:
    """All vendor→admin share payments, newest first."""
    with _connect() as connection:
        rows = connection.execute("SELECT * FROM share_payments ORDER BY rowid DESC").fetchall()
        return _rows_to_dicts(rows)


def list_share_payments_by_shop(shop_id: str) -> list[dict[str, Any]]:
    """Share payments for one shop only (vendor dashboard hot path)."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM share_payments WHERE shop_id = ? ORDER BY rowid DESC",
            (shop_id,),
        ).fetchall()
        return _rows_to_dicts(rows)


def update_share_payment_status(payment_id: str, status: str) -> dict[str, Any] | None:
    """Mark a share payment Received (Completed) or Rejected. Sets paid_at on completion."""
    with _connect() as connection:
        if status == "Completed":
            connection.execute(
                "UPDATE share_payments SET status = ?, paid_at = ? WHERE id = ?",
                (status, datetime.now().isoformat(), payment_id),
            )
        else:
            connection.execute(
                "UPDATE share_payments SET status = ? WHERE id = ?",
                (status, payment_id),
            )
        row = connection.execute("SELECT * FROM share_payments WHERE id = ?", (payment_id,)).fetchone()
        return dict(row) if row else None


def list_products(shop_id: str | None = None) -> list[dict[str, Any]]:
    with _connect() as connection:
        if shop_id:
            rows = connection.execute(
                "SELECT * FROM products WHERE shop_id = ? ORDER BY category, name",
                (shop_id,),
            ).fetchall()
        else:
            rows = connection.execute("SELECT * FROM products ORDER BY category, name").fetchall()
        return _rows_to_dicts(rows)


def create_product(values: dict[str, Any]) -> dict[str, Any]:
    with _connect() as connection:
        # Collision-proof: COUNT(*) + 1 reuses IDs after a delete, which breaks
        # inserts with a duplicate-key error. MAX(numeric suffix) keeps the next
        # ID unique even after rows are removed.
        next_num = connection.execute(
            "SELECT COALESCE(MAX(CAST(substr(id, 2) AS INTEGER)), 0) + 1 FROM products"
        ).fetchone()[0]
        product_id = values.get("id") or f"p{next_num}"
        connection.execute(
            """
            INSERT INTO products (
                id, shop_id, name, description, price, pending_price,
                category, inventory, prep_time, available
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                1 if values.get("available", True) else 0,
            ),
        )
        row = connection.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
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
        updates["available"] = 1 if updates["available"] else 0

    assignments = ", ".join(f"{field} = ?" for field in updates)
    params = [*updates.values(), product_id]
    with _connect() as connection:
        connection.execute(f"UPDATE products SET {assignments} WHERE id = ?", params)
        row = connection.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        return dict(row) if row else None


def get_product(product_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        return dict(row) if row else None


def delete_product(product_id: str) -> bool:
    """Permanently remove a product row. Returns True when a row was deleted."""
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM products WHERE id = ?", (product_id,))
        return cursor.rowcount > 0


def list_orders(limit: int | None = None) -> list[dict[str, Any]]:
    """All orders, newest first. ``limit`` bounds the payload so hot endpoints
    never ship the entire order history on every poll."""
    with _connect() as connection:
        # Newest first — created_at desc puts today's orders on top even though
        # tokens restart every day (tokens alone would mix days together).
        sql = "SELECT * FROM orders ORDER BY created_at DESC, token DESC"
        params: tuple = ()
        if limit:
            sql += " LIMIT ?"
            params = (limit,)
        rows = connection.execute(sql, params).fetchall()
        return _rows_to_dicts(rows)


def list_orders_by_shop(shop_id: str) -> list[dict[str, Any]]:
    """Orders for one shop only (vendor dashboard/history hot path)."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM orders WHERE shop_id = ? ORDER BY token DESC",
            (shop_id,),
        ).fetchall()
        return _rows_to_dicts(rows)


def list_recent_orders_by_shop(shop_id: str, limit: int = 250) -> list[dict[str, Any]]:
    """Latest orders for one shop (newest first) — the live feed in the vendor
    app. Bounded so the 30s auto-refresh never ships the shop's entire history."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM orders WHERE shop_id = ? ORDER BY created_at DESC LIMIT ?",
            (shop_id, limit),
        ).fetchall()
        return _rows_to_dicts(rows)


def get_order(order_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        return dict(row) if row else None


def find_order_by_token(token: str) -> dict[str, Any] | None:
    """Find the most recent order for a token number (tokens restart daily)."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM orders WHERE token = ? ORDER BY created_at DESC LIMIT 1",
            (token,),
        ).fetchall()
        return dict(rows[0]) if rows else None


def update_order_status(order_id: str, status: str) -> dict[str, Any] | None:
    with _connect() as connection:
        connection.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        row = connection.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
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
                connection=connection,
            )
        return dict(row) if row else None


def create_order(values: dict[str, Any]) -> dict[str, Any] | None:
    with _connect() as connection:
        shop = connection.execute("SELECT * FROM shops WHERE id = ?", (values["shop_id"],)).fetchone()
        if not shop:
            return None
        if not _shop_is_orderable(dict(shop)):
            return None

        product_ids = [item["product_id"] for item in values["items"]]
        products_by_id = {}
        for product_id in product_ids:
            row = connection.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
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

        # created_at is stored in IST (see the INSERT below) — every "today"
        # boundary must use IST too, otherwise midnight-5:30 AM IST orders would
        # collide on the same token/order id (UTC date is still "yesterday").
        next_token = connection.execute(
            "SELECT COALESCE(MAX(token), 17) + 1 FROM orders WHERE substr(created_at, 1, 10) = date('now', '+05:30')"
        ).fetchone()[0]
        today_key = connection.execute("SELECT strftime('%Y%m%d', 'now', '+05:30')").fetchone()[0]
        order_id = f"o{today_key}-{next_token}"

        connection.execute(
            """
            INSERT INTO orders (
                id, token, student_name, student_phone, shop_id, shop_name,
                items, subtotal, service_fee, tax, delivery_fee, total,
                delivery_location, delivery_slot, status, payment_method, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%d %H:%M:%S', 'now', '+05:30'))
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
        row = connection.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row:
            connection.execute(
                """
                UPDATE shops
                SET orders_today = orders_today + 1,
                    revenue_today = revenue_today + ?,
                    current_token = ?
                WHERE id = ?
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
            row = connection.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        return dict(row) if row else None


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

    Returns the parent order dict (with nested ``sub_orders``) or ``None`` when
    any shop/item is invalid. One token is shared across ALL sub-orders.
    The student pays ONE bill (sum of every sub-order subtotal); each shop's
    5% commission is recorded per sub-order but never charged to the student.
    """
    with _connect() as connection:
        token = consume_token()
        today_key = connection.execute(
            "SELECT strftime('%Y%m%d', 'now', '+05:30')"
        ).fetchone()[0]
        parent_id = f"p{today_key}-{token}"
        batch_type = get_current_batch()

        sub_orders: list[dict[str, Any]] = []
        grand_total = 0

        for group in shops:
            shop_row = connection.execute(
                "SELECT * FROM shops WHERE id = ?", (group["shop_id"],)
            ).fetchone()
            if not shop_row:
                continue
            shop = dict(shop_row)
            if not _shop_is_orderable(shop):
                continue

            products_by_id = {}
            product_ids = [item["product_id"] for item in group.get("items", [])]
            for product_id in product_ids:
                row = connection.execute(
                    "SELECT * FROM products WHERE id = ?", (product_id,)
                ).fetchone()
                if row:
                    products_by_id[product_id] = dict(row)

            subtotal = 0
            order_item_rows: list[tuple] = []
            for item in group.get("items", []):
                product = products_by_id.get(item["product_id"])
                if not product:
                    continue
                quantity = int(item["quantity"])
                if quantity <= 0:
                    continue
                if not consume_batch_stock(
                    product["id"], batch_type, quantity
                ):
                    raise ValueError(
                        f"Insufficient stock for {product['name']}"
                    )
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

            connection.execute(
                """
                INSERT INTO shop_sub_orders (
                    id, parent_order_id, shop_id, shop_name, shop_phone,
                    shop_whatsapp, token, subtotal, commission_5pct, status,
                    batch_type, created_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?,
                    strftime('%Y-%m-%d %H:%M:%S', 'now', '+05:30')
                )
                """,
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
                connection.execute(
                    """
                    INSERT INTO order_items (sub_order_id, product_id, product_name, price, quantity, total)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (sub_order_id, product_id, name, price, qty, line_total),
                )

            item_labels = [f"{q}x {n}" for _, n, _, q, _ in order_item_rows]
            grand_total += subtotal

            sub_orders.append(
                {
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
                }
            )

            connection.execute(
                """
                UPDATE shops
                SET orders_today = orders_today + 1,
                    revenue_today = revenue_today + ?,
                    current_token = ?
                WHERE id = ?
                """,
                (subtotal, token, shop["id"]),
            )

        if not sub_orders:
            raise ValueError("No valid shops or items in order")

        connection.execute(
            """
            INSERT INTO parent_orders (
                id, token, student_name, student_phone, student_email,
                student_id, total, payment_method, payment_status,
                delivery_location, status, created_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?, 'Pending',
                strftime('%Y-%m-%d %H:%M:%S', 'now', '+05:30')
            )
            """,
            (
                parent_id,
                token,
                student_name,
                student_phone,
                student_email,
                student_id,
                grand_total,
                payment_method,
                delivery_location,
            ),
        )

        row = connection.execute(
            "SELECT * FROM parent_orders WHERE id = ?", (parent_id,)
        ).fetchone()
        parent = dict(row)
        parent["sub_orders"] = sub_orders
        return parent


def get_parent_order(parent_order_id: str, with_items: bool = True) -> dict[str, Any] | None:
    """Get a parent order including its shop sub-orders (and their items)."""
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM parent_orders WHERE id = ?", (parent_order_id,)
        ).fetchone()
        if not row:
            return None
        parent = dict(row)
        sub_rows = connection.execute(
            "SELECT * FROM shop_sub_orders WHERE parent_order_id = ? ORDER BY rowid",
            (parent_order_id,),
        ).fetchall()
        sub_orders = []
        for sub_row in sub_rows:
            sub = dict(sub_row)
            if with_items:
                item_rows = connection.execute(
                    "SELECT * FROM order_items WHERE sub_order_id = ?",
                    (sub["id"],),
                ).fetchall()
                sub["items"] = _rows_to_dicts(item_rows)
            sub_orders.append(sub)
        parent["sub_orders"] = sub_orders
        return parent


def list_parent_orders(limit: int = 200, status: str | None = None) -> list[dict[str, Any]]:
    """List parent orders, newest first, optional status filter."""
    with _connect() as connection:
        sql = "SELECT * FROM parent_orders"
        args: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            args.append(status)
        sql += " ORDER BY rowid DESC LIMIT ?"
        args.append(limit)
        rows = connection.execute(sql, args).fetchall()
        return _rows_to_dicts(rows)


def get_shop_sub_orders(shop_id: str, status: str | None = None) -> list[dict[str, Any]]:
    """All sub-orders for a shop. Only the shop's own orders."""
    with _connect() as connection:
        sql = "SELECT * FROM shop_sub_orders WHERE shop_id = ?"
        args: list[Any] = [shop_id]
        if status:
            sql += " AND status = ?"
            args.append(status)
        sql += " ORDER BY rowid DESC"
        rows = connection.execute(sql, args).fetchall()
        sub_orders = []
        for row in rows:
            sub = dict(row)
            item_rows = connection.execute(
                "SELECT * FROM order_items WHERE sub_order_id = ?",
                (sub["id"],),
            ).fetchall()
            sub["items"] = _rows_to_dicts(item_rows)
            parent = connection.execute(
                "SELECT student_name, student_phone, delivery_location, total, payment_method, created_at FROM parent_orders WHERE id = ?",
                (sub["parent_order_id"],),
            ).fetchone()
            sub["parent"] = dict(parent) if parent else {}
            sub_orders.append(sub)
        return sub_orders


def update_sub_order_status(
    sub_order_id: str, status: str, notes: str = ""
) -> dict[str, Any] | None:
    """Update a shop sub-order's status and record the transition timestamp."""
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM shop_sub_orders WHERE id = ?", (sub_order_id,)
        ).fetchone()
        if not row:
            return None
        sub = dict(row)
        timestamps = {
            "Accepted": "accepted_at",
            "Preparing": "prepared_at",
            "Ready": "ready_at",
            "Delivered": "delivered_at",
            "Completed": "completed_at",
        }
        ts_col = timestamps.get(status)
        now = "datetime('now', '+05:30')"
        # Build safe dynamic SET (column names come from our fixed dict above).
        if ts_col:
            connection.execute(
                f"UPDATE shop_sub_orders SET status = ?, {ts_col} = {now} WHERE id = ?",
                (status, sub_order_id),
            )
        else:
            connection.execute(
                "UPDATE shop_sub_orders SET status = ?, rejection_reason = COALESCE(?, rejection_reason) WHERE id = ?",
                (status, notes, sub_order_id),
            )
        updated = connection.execute(
            "SELECT * FROM shop_sub_orders WHERE id = ?", (sub_order_id,)
        ).fetchone()
        # Sync parent order status: if all sub-orders terminal, mark parent.
        if status in ("Delivered", "Completed"):
            sub_rows = connection.execute(
                "SELECT status FROM shop_sub_orders WHERE parent_order_id = ?",
                (sub["parent_order_id"],),
            ).fetchall()
            if all(s["status"] in ("Delivered", "Completed") for s in sub_rows):
                connection.execute(
                    "UPDATE parent_orders SET status = 'Completed' WHERE id = ?",
                    (sub["parent_order_id"],),
                )
        return dict(updated) if updated else None


def auto_complete_expired_deliveries() -> int:
    """Auto-complete sub-orders that were delivered more than 30 minutes ago.

    Per spec section 36: after the 30-minute problem window, the order is
    auto-confirmed and the parent order completes once every sub-order is
    terminal. Safe to call on every request (it's fast and idempotent) so it
    also works on serverless/backgroundless hosts. Returns how many
    sub-orders were completed just now.
    """
    from datetime import datetime, timedelta

    completed_now = 0
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, parent_order_id, delivered_at
            FROM shop_sub_orders
            WHERE status = 'Delivered' AND delivered_at IS NOT NULL
            """
        ).fetchall()
        now = datetime.utcnow()
        for row in rows:
            try:
                dt_str = str(row["delivered_at"] or "")
                dt_str_clean = dt_str.replace("+05:30", "").replace("+00:00", "")
                delivered = datetime.strptime(dt_str_clean[:19], "%Y-%m-%d %H:%M:%S")
                if (now - delivered) >= timedelta(minutes=30):
                    connection.execute(
                        "UPDATE shop_sub_orders SET status = 'Completed', completed_at = datetime('now', '+05:30') WHERE id = ?",
                        (row["id"],),
                    )
                    completed_now += 1
                    sub_rows = connection.execute(
                        "SELECT status FROM shop_sub_orders WHERE parent_order_id = ?",
                        (row["parent_order_id"],),
                    ).fetchall()
                    if all(s["status"] in ("Delivered", "Completed") for s in sub_rows):
                        connection.execute(
                            "UPDATE parent_orders SET status = 'Completed' WHERE id = ?",
                            (row["parent_order_id"],),
                        )
            except Exception:
                continue
    return completed_now


def get_daily_token_count(date_key: str | None = None) -> int:
    """Number of parent orders today (for the dashboard's token display)."""
    date_key = date_key or _day_key()
    with _connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS c FROM parent_orders WHERE substr(created_at, 1, 10) = ?",
            (date_key,),
        ).fetchone()
        return int(row["c"])


def create_shop_announcement(shop_id: str, message: str) -> dict[str, Any] | None:
    with _connect() as connection:
        import uuid
        ann_id = f"ann-{uuid.uuid4().hex[:12]}"
        connection.execute(
            "INSERT INTO shop_announcements (id, shop_id, message, is_active, created_at) VALUES (?, ?, ?, 1, datetime('now', '+05:30'))",
            (ann_id, shop_id, message),
        )
        row = connection.execute(
            "SELECT * FROM shop_announcements WHERE id = ?", (ann_id,)
        ).fetchone()
        return dict(row) if row else None


def list_shop_announcements(shop_id: str | None = None, active_only: bool = True) -> list[dict[str, Any]]:
    with _connect() as connection:
        sql = "SELECT * FROM shop_announcements"
        args: list[Any] = []
        if active_only:
            sql += " WHERE is_active = 1"
        if shop_id:
            sql += " AND shop_id = ?" if "WHERE" in sql else " WHERE shop_id = ?"
            args.append(shop_id)
        sql += " ORDER BY rowid DESC"
        rows = connection.execute(sql, args).fetchall()
        return _rows_to_dicts(rows)


def toggle_shop_announcement(ann_id: str, is_active: bool) -> dict[str, Any] | None:
    """Turn an announcement on/off."""
    with _connect() as connection:
        connection.execute(
            "UPDATE shop_announcements SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, ann_id),
        )
        row = connection.execute(
            "SELECT * FROM shop_announcements WHERE id = ?", (ann_id,)
        ).fetchone()
        return dict(row) if row else None


def create_complaint(
    parent_order_id: str,
    student_name: str,
    student_phone: str,
    shop_id: str,
    shop_name: str,
    subject: str,
    message: str,
) -> dict[str, Any] | None:
    with _connect() as connection:
        import uuid
        complaint_id = f"cmp-{uuid.uuid4().hex[:12]}"
        connection.execute(
            """
            INSERT INTO complaints (
                id, parent_order_id, student_name, student_phone, shop_id,
                shop_name, subject, message, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'New', datetime('now', '+05:30'))
            """,
            (
                complaint_id, parent_order_id, student_name, student_phone,
                shop_id, shop_name, subject, message,
            ),
        )
        row = connection.execute(
            "SELECT * FROM complaints WHERE id = ?", (complaint_id,)
        ).fetchone()
        return dict(row) if row else None


def list_complaints(status: str | None = None) -> list[dict[str, Any]]:
    with _connect() as connection:
        sql = "SELECT * FROM complaints"
        args: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            args.append(status)
        sql += " ORDER BY rowid DESC"
        rows = connection.execute(sql, args).fetchall()
        return _rows_to_dicts(rows)


def update_complaint(complaint_id: str, status: str, admin_notes: str = "") -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM complaints WHERE id = ?", (complaint_id,)
        ).fetchone()
        if not row:
            return None
        connection.execute(
            "UPDATE complaints SET status = ?, admin_notes = ? WHERE id = ?",
            (status, admin_notes, complaint_id),
        )
        updated = connection.execute(
            "SELECT * FROM complaints WHERE id = ?", (complaint_id,)
        ).fetchone()
        return dict(updated) if updated else None


def create_refund(
    parent_order_id: str,
    sub_order_id: str,
    student_name: str,
    shop_name: str,
    original_amount: int,
    refund_amount: int,
    refund_type: str = "Full",
) -> dict[str, Any] | None:
    with _connect() as connection:
        import uuid
        refund_id = f"ref-{uuid.uuid4().hex[:12]}"
        connection.execute(
            """
            INSERT INTO refunds (
                id, parent_order_id, sub_order_id, student_name, shop_name,
                original_amount, refund_amount, refund_type, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pending', datetime('now', '+05:30'))
            """,
            (
                refund_id, parent_order_id, sub_order_id, student_name,
                shop_name, original_amount, refund_amount, refund_type,
            ),
        )
        row = connection.execute(
            "SELECT * FROM refunds WHERE id = ?", (refund_id,)
        ).fetchone()
        return dict(row) if row else None


def list_refunds(status: str | None = None) -> list[dict[str, Any]]:
    with _connect() as connection:
        sql = "SELECT * FROM refunds"
        args: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            args.append(status)
        sql += " ORDER BY rowid DESC"
        rows = connection.execute(sql, args).fetchall()
        return _rows_to_dicts(rows)


def update_refund(
    refund_id: str, status: str, refund_utr: str = "", admin_notes: str = ""
) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM refunds WHERE id = ?", (refund_id,)
        ).fetchone()
        if not row:
            return None
        connection.execute(
            "UPDATE refunds SET status = ?, refund_utr = COALESCE(?, refund_utr), admin_notes = ?, completed_at = CASE WHEN ? IN ('Completed','Refunded') THEN datetime('now', '+05:30') ELSE completed_at END WHERE id = ?",
            (status, refund_utr, admin_notes, status, refund_id),
        )
        updated = connection.execute(
            "SELECT * FROM refunds WHERE id = ?", (refund_id,)
        ).fetchone()
        return dict(updated) if updated else None


def list_settlements(status: str | None = None) -> list[dict[str, Any]]:
    with _connect() as connection:
        sql = "SELECT * FROM settlements"
        args: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            args.append(status)
        sql += " ORDER BY date_key DESC, rowid DESC"
        rows = connection.execute(sql, args).fetchall()
        return _rows_to_dicts(rows)


def run_daily_settlements() -> list[dict[str, Any]]:
    """Compute every shop's gross sales, 5% commission, and net payable for
    today and upsert a settlement record. Called by admin or a 9 PM job."""
    from datetime import datetime
    date_key = _day_key()
    with _connect() as connection:
        shops = connection.execute("SELECT id, name FROM shops").fetchall()
        settlements: list[dict[str, Any]] = []
        for shop_row in shops:
            shop_id = shop_row["id"]
            gross = connection.execute(
                """
                SELECT COALESCE(SUM(total), 0) AS g FROM order_items oi
                JOIN shop_sub_orders sso ON sso.id = oi.sub_order_id
                WHERE sso.shop_id = ?
                """,
                (shop_id,),
            ).fetchone()["g"]
            commission = round(gross * 0.05)
            net = gross - commission
            existing = connection.execute(
                "SELECT id FROM settlements WHERE shop_id = ? AND date_key = ?",
                (shop_id, date_key),
            ).fetchone()
            import uuid
            settlement_id = existing["id"] if existing else f"set-{shop_id}-{uuid.uuid4().hex[:6]}"
            connection.execute(
                """
                INSERT OR REPLACE INTO settlements (
                    id, shop_id, shop_name, date_key, gross_sales,
                    commission_5pct, refunds_adjusted, net_payable, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, 'Pending', datetime('now', '+05:30'))
                """,
                (settlement_id, shop_id, shop_row["name"], date_key, gross, commission, net),
            )
            settlements.append({
                "id": settlement_id,
                "shop_id": shop_id,
                "shop_name": shop_row["name"],
                "gross_sales": gross,
                "commission_5pct": commission,
                "net_payable": net,
            })
        return settlements


def create_menu_change_request(
    shop_id: str, product_id: str, change_type: str, old_value: str, new_value: str
) -> dict[str, Any] | None:
    with _connect() as connection:
        import uuid
        req_id = f"mcr-{uuid.uuid4().hex[:12]}"
        connection.execute(
            """
            INSERT INTO menu_change_requests (
                id, shop_id, product_id, change_type, old_value, new_value, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'Pending', datetime('now', '+05:30'))
            """,
            (req_id, shop_id, product_id, change_type, old_value, new_value),
        )
        row = connection.execute(
            "SELECT * FROM menu_change_requests WHERE id = ?", (req_id,)
        ).fetchone()
        return dict(row) if row else None


def list_menu_change_requests(status: str | None = None) -> list[dict[str, Any]]:
    with _connect() as connection:
        sql = "SELECT * FROM menu_change_requests"
        args: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            args.append(status)
        sql += " ORDER BY rowid DESC"
        rows = connection.execute(sql, args).fetchall()
        return _rows_to_dicts(rows)


def update_menu_change_request(req_id: str, status: str, admin_notes: str = "") -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM menu_change_requests WHERE id = ?", (req_id,)
        ).fetchone()
        if not row:
            return None
        connection.execute(
            "UPDATE menu_change_requests SET status = ?, admin_notes = ?, reviewed_at = datetime('now', '+05:30') WHERE id = ?",
            (status, admin_notes, req_id),
        )
        updated = connection.execute(
            "SELECT * FROM menu_change_requests WHERE id = ?", (req_id,)
        ).fetchone()
        return dict(updated) if updated else None


def add_audit_log(
    admin_user: str, action: str, entity_type: str, entity_id: str,
    old_value: str = "", new_value: str = "",
) -> None:
    with _connect() as connection:
        connection.execute(
            "INSERT INTO audit_logs (admin_user, action, entity_type, entity_id, old_value, new_value) VALUES (?, ?, ?, ?, ?, ?)",
            (admin_user, action, entity_type, entity_id, old_value, new_value),
        )


def list_audit_logs(limit: int = 200) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM audit_logs ORDER BY rowid DESC LIMIT ?", (limit,)
        ).fetchall()
        return _rows_to_dicts(rows)


def list_whatsapp_logs(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM whatsapp_logs ORDER BY rowid DESC LIMIT ?", (limit,)
        ).fetchall()
        return _rows_to_dicts(rows)


def log_sms(
    sub_order_id: str = "",
    phone: str = "",
    message: str = "",
    status: str = "Sent",
    direction: str = "out",
) -> dict[str, Any] | None:
    """Persist one SMS (out = sent to a phone, in = received from a phone)."""
    with _connect() as connection:
        next_id = connection.execute(
            "SELECT COALESCE(MAX(CAST(substr(id, 2) AS INTEGER)), 0) + 1 FROM sms_logs"
        ).fetchone()[0]
        sms_id = f"s{next_id}"
        connection.execute(
            "INSERT INTO sms_logs (id, sub_order_id, phone, message, direction, status) VALUES (?, ?, ?, ?, ?, ?)",
            (sms_id, sub_order_id, phone or "", message or "", direction, status),
        )
        row = connection.execute("SELECT * FROM sms_logs WHERE id = ?", (sms_id,)).fetchone()
        return dict(row) if row else None


def list_sms_logs(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM sms_logs ORDER BY rowid DESC LIMIT ?", (limit,)
        ).fetchall()
        return _rows_to_dicts(rows)


def create_payment(
    order_id: str,
    amount: int,
    method: str,
    utr_number: str | None = None,
    screenshot_name: str | None = None,
) -> dict[str, Any] | None:
    with _connect() as connection:
        order = connection.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not order:
            return None
        next_id = connection.execute("SELECT COUNT(*) + 1 FROM payments").fetchone()[0]
        payment_id = f"pay{next_id}"
        status = "Pending" if method in ("Manual UTR", "UPI") else "Success"
        connection.execute(
            """
            INSERT INTO payments (id, order_id, amount, method, status, utr_number, screenshot_name)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (payment_id, order_id, amount, method, status, utr_number, screenshot_name),
        )
        row = connection.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        return dict(row) if row else None


def list_payments() -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute("SELECT * FROM payments ORDER BY rowid DESC").fetchall()
        return _rows_to_dicts(rows)


def get_payment_by_order_id(order_id: str) -> dict[str, Any] | None:
    """Get the most recent payment record for an order."""
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM payments WHERE order_id = ? ORDER BY rowid DESC LIMIT 1",
            (order_id,),
        ).fetchone()
        return dict(row) if row else None


def set_payment_utr(order_id: str, utr_number: str) -> dict[str, Any] | None:
    """Stamp the student-provided UTR on the latest payment for an order."""
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM payments WHERE order_id = ? ORDER BY rowid DESC LIMIT 1",
            (order_id,),
        ).fetchone()
        if not row:
            return None
        connection.execute(
            "UPDATE payments SET utr_number = ? WHERE id = ?",
            (utr_number, row["id"]),
        )
        updated = connection.execute("SELECT * FROM payments WHERE id = ?", (row["id"],)).fetchone()
        return dict(updated) if updated else None


def get_payment_by_utr(utr_number: str) -> dict[str, Any] | None:
    """Find the most recent payment record carrying this UTR (student-entered).

    UTRs are unique per transaction, but SQLite has no per-row uniqueness on a
    nullable column — so the newest match wins (a student re-entering the same
    UTR on a second order would otherwise match twice).
    """
    if not utr_number:
        return None
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM payments WHERE utr_number = ? ORDER BY rowid DESC LIMIT 1",
            (utr_number,),
        ).fetchone()
        return dict(row) if row else None


def update_payment_record(order_id: str, screenshot_name: str, utr_number: str | None = None) -> dict[str, Any] | None:
    """Attach a payment screenshot (and optional UTR) to the latest payment for an order."""
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM payments WHERE order_id = ? ORDER BY rowid DESC LIMIT 1",
            (order_id,),
        ).fetchone()
        if not row:
            return None
        connection.execute(
            "UPDATE payments SET screenshot_name = ?, utr_number = COALESCE(?, utr_number) WHERE id = ?",
            (screenshot_name, utr_number, row["id"]),
        )
        updated = connection.execute("SELECT * FROM payments WHERE id = ?", (row["id"],)).fetchone()
        return dict(updated) if updated else None


def update_payment_status(payment_id: str, status: str) -> dict[str, Any] | None:
    with _connect() as connection:
        connection.execute("UPDATE payments SET status = ? WHERE id = ?", (status, payment_id))
        row = connection.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        if row and status == "Success":
            connection.execute("UPDATE orders SET status = ? WHERE id = ?", ("Pending Acceptance", row["order_id"]))
            order_row = connection.execute("SELECT * FROM orders WHERE id = ?", (row["order_id"],)).fetchone()
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
            connection.execute("UPDATE orders SET status = ? WHERE id = ?", ("Failed", row["order_id"]))
        return dict(row) if row else None


def get_payment_settings() -> dict[str, Any]:
    defaults = {
        "manual_enabled": False,
        "upi_id": "",
        "receiver_name": "",
        "instructions": "",
        "razorpay_enabled": False,
    }
    with _connect() as connection:
        rows = connection.execute("SELECT key, value FROM app_settings").fetchall()
        values = {row["key"]: row["value"] for row in rows}
    return {
        "manual_enabled": values.get("manual_enabled", "false") == "true",
        "upi_id": values.get("upi_id", defaults["upi_id"]),
        "receiver_name": values.get("receiver_name", defaults["receiver_name"]),
        "instructions": values.get("instructions", defaults["instructions"]),
        "razorpay_enabled": values.get("razorpay_enabled", "false") == "true",
    }


def update_payment_settings(values: dict[str, Any]) -> dict[str, Any]:
    allowed = {"manual_enabled", "upi_id", "receiver_name", "instructions", "razorpay_enabled"}
    with _connect() as connection:
        for key, value in values.items():
            if key not in allowed or value is None:
                continue
            stored_value = str(value).lower() if isinstance(value, bool) else str(value)
            connection.execute(
                "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
                (key, stored_value),
            )
    return get_payment_settings()


def create_ticket(values: dict[str, Any]) -> dict[str, Any]:
    with _connect() as connection:
        next_id = connection.execute("SELECT COUNT(*) + 1 FROM tickets").fetchone()[0]
        ticket_id = f"t{next_id}"
        ticket_number = f"TKT-{1000 + next_id}"
        connection.execute(
            """
            INSERT INTO tickets (
                id, ticket_number, name, email, phone_number, category,
                title, description, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        row = connection.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        return dict(row)


def list_tickets() -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute("SELECT * FROM tickets ORDER BY created_at DESC").fetchall()
        return _rows_to_dicts(rows)


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
    try:
        # Collision-proof id (MAX, not COUNT) so deleted notification rows can
        # never make the next insert fail with a duplicate-key error.
        next_id = active_connection.execute(
            "SELECT COALESCE(MAX(CAST(substr(id, 2) AS INTEGER)), 0) + 1 FROM notifications"
        ).fetchone()[0]
        notification_id = f"n{next_id}"
        active_connection.execute(
            """
            INSERT INTO notifications (id, title, message, order_id, status, target_role)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (notification_id, title, message, order_id, status, target_role),
        )
        row = active_connection.execute(
            "SELECT * FROM notifications WHERE id = ?",
            (notification_id,),
        ).fetchone()
        if owns_connection:
            active_connection.commit()
        return dict(row) if row else None
    finally:
        if owns_connection:
            active_connection.close()


def list_notifications(role: str | None = None) -> list[dict[str, Any]]:
    """List notifications. When ``role`` is given, only notifications targeted at
    that exact role are returned (strict role separation)."""
    with _connect() as connection:
        if role:
            rows = connection.execute(
                "SELECT * FROM notifications WHERE target_role = ? ORDER BY rowid DESC LIMIT 20",
                (role,),
            ).fetchall()
        else:
            rows = connection.execute("SELECT * FROM notifications ORDER BY rowid DESC LIMIT 20").fetchall()
        return _rows_to_dicts(rows)


# ─── Web push subscriptions (vendor order notifications) ───


def save_push_subscription(
    shop_id: str,
    endpoint: str,
    p256dh: str,
    auth: str,
) -> dict[str, Any] | None:
    """Save (or refresh) a browser push subscription for a vendor's shop.
    ``endpoint`` is unique per device+browser, so it's the natural key."""
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO push_subscriptions (endpoint, shop_id, p256dh, auth)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET
                shop_id = excluded.shop_id,
                p256dh = excluded.p256dh,
                auth = excluded.auth
            """,
            (endpoint, shop_id, p256dh, auth),
        )
        row = connection.execute(
            "SELECT * FROM push_subscriptions WHERE endpoint = ?",
            (endpoint,),
        ).fetchone()
        return dict(row) if row else None


def list_push_subscriptions(shop_id: str) -> list[dict[str, Any]]:
    """All push subscriptions registered for a shop (used to deliver pushes)."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM push_subscriptions WHERE shop_id = ? ORDER BY rowid",
            (shop_id,),
        ).fetchall()
        return _rows_to_dicts(rows)


def remove_push_subscription(shop_id: str, endpoint: str) -> bool:
    """Remove a push subscription (e.g. when the browser reports it's dead)."""
    with _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM push_subscriptions WHERE endpoint = ? AND shop_id = ?",
            (endpoint, shop_id),
        )
        return cursor.rowcount > 0


def list_users() -> list[dict[str, Any]]:
    """List all registered users (without password_hash)."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, username, name, email, phone, role, created_at FROM users ORDER BY created_at DESC"
        ).fetchall()
        return _rows_to_dicts(rows)


def list_users_by_role(role: str) -> list[dict[str, Any]]:
    """List users filtered by role."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, username, name, email, phone, role, created_at FROM users WHERE role = ? ORDER BY created_at DESC",
            (role,),
        ).fetchall()
        return _rows_to_dicts(rows)


def record_registration(user: dict[str, Any]) -> None:
    """Record a user registration for admin notifications."""
    with _connect() as connection:
        connection.execute(
            "INSERT INTO user_registrations (username, name, email, phone, role) VALUES (?, ?, ?, ?, ?)",
            (user.get("username", ""), user.get("name", ""), user.get("email", ""), user.get("phone", ""), user.get("role", "")),
        )


def list_registrations() -> list[dict[str, Any]]:
    """List all user registrations for admin."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM user_registrations ORDER BY created_at DESC"
        ).fetchall()
        return _rows_to_dicts(rows)


# ─── Forgot password (double email OTP verification) ───


def get_user_by_email(email: str) -> dict[str, Any] | None:
    """Find a user by their registered email (case-insensitive)."""
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE LOWER(email) = ? LIMIT 1",
            (email.lower(),),
        ).fetchone()
        return dict(row) if row else None


def create_password_reset(username: str, otp: str, step: int) -> dict[str, Any] | None:
    """Store an OTP for a password-reset step (1 or 2) for the given user.
    Older unused codes for the same user are cleared so only the newest counts.
    The expiry is computed in SQLite's own datetime format so the lexicographic
    comparison in get_password_reset stays correct."""
    minutes = int(settings.RESET_OTP_EXPIRE_MINUTES)
    with _connect() as connection:
        connection.execute(
            "DELETE FROM password_resets WHERE username = ?",
            (username.lower(),),
        )
        cursor = connection.execute(
            """
            INSERT INTO password_resets (username, otp, step, expires_at)
            VALUES (?, ?, ?, datetime('now', ?))
            """,
            (username.lower(), otp, step, f"+{minutes} minutes"),
        )
        row = connection.execute(
            "SELECT * FROM password_resets WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return dict(row) if row else None


def get_password_reset(username: str, otp: str, step: int) -> dict[str, Any] | None:
    """Return the valid, unused, unexpired reset code for this user/step.
    Codes are locked out after 5 wrong attempts (brute-force protection)."""
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT * FROM password_resets
            WHERE username = ? AND otp = ? AND step = ? AND used = 0
              AND attempts < 5
              AND expires_at >= datetime('now')
            ORDER BY id DESC LIMIT 1
            """,
            (username.lower(), otp, step),
        ).fetchone()
        return dict(row) if row else None


def bump_password_reset_attempts(username: str) -> None:
    """Count one wrong OTP guess for this user's pending reset."""
    with _connect() as connection:
        connection.execute(
            "UPDATE password_resets SET attempts = attempts + 1 WHERE username = ? AND used = 0",
            (username.lower(),),
        )


def invalidate_password_resets(username: str) -> None:
    """Mark every pending reset code for this user as used."""
    with _connect() as connection:
        connection.execute(
            "UPDATE password_resets SET used = 1 WHERE username = ?",
            (username.lower(),),
        )


def update_user_password(username: str, new_password_hash: str) -> bool:
    """Set a new password hash for a user (by username)."""
    with _connect() as connection:
        cursor = connection.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (new_password_hash, username.lower()),
        )
        return cursor.rowcount > 0


# ─── Site feedback / bug reports (students → admin) ───


def create_site_feedback(values: dict[str, Any]) -> dict[str, Any] | None:
    """Store a student's bug report / improvement contribution.

    The admin is notified through the notifications bell (target_role='admin')
    so new contributions surface immediately on the admin Feedback page."""
    with _connect() as connection:
        # Collision-proof id (MAX, not COUNT) so deleted rows never cause the
        # next insert to fail with a duplicate-key error.
        next_id = connection.execute(
            "SELECT COALESCE(MAX(CAST(substr(id, 3) AS INTEGER)), 0) + 1 FROM site_feedback"
        ).fetchone()[0]
        feedback_id = f"fb{next_id}"
        connection.execute(
            """
            INSERT INTO site_feedback (
                id, user_id, username, name, email, category,
                subject, message, page, status, source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Open', ?)
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
        row = connection.execute(
            "SELECT * FROM site_feedback WHERE id = ?",
            (feedback_id,),
        ).fetchone()
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
    with _connect() as connection:
        if source:
            rows = connection.execute(
                "SELECT * FROM site_feedback WHERE source = ? ORDER BY rowid DESC",
                (source,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM site_feedback ORDER BY rowid DESC"
            ).fetchall()
        return _rows_to_dicts(rows)


def list_site_feedback_by_user(user_id: int) -> list[dict[str, Any]]:
    """A student's own submissions (student portal "my contributions")."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM site_feedback WHERE user_id = ? ORDER BY rowid DESC",
            (user_id,),
        ).fetchall()
        return _rows_to_dicts(rows)


def update_site_feedback_status(feedback_id: str, status: str) -> dict[str, Any] | None:
    """Admin marks a contribution as Open / In Review / Fixed / Won't Fix."""
    allowed = {"Open", "In Review", "Fixed", "Won't Fix"}
    if status not in allowed:
        return None
    with _connect() as connection:
        connection.execute(
            "UPDATE site_feedback SET status = ? WHERE id = ?",
            (status, feedback_id),
        )
        row = connection.execute(
            "SELECT * FROM site_feedback WHERE id = ?",
            (feedback_id,),
        ).fetchone()
        return dict(row) if row else None


def delete_site_feedback(source: str | None = None) -> int:
    """Permanently delete feedback rows.

    Pass ``source='ATS'`` to clear automated-test contributions, ``'User'`` to
    clear real reports, or ``None`` for everything. Returns how many rows were
    removed — the admin Feedback page uses this to purge test data so the page
    shows ONLY real student feedback."""
    with _connect() as connection:
        if source:
            cursor = connection.execute(
                "DELETE FROM site_feedback WHERE source = ?",
                (source,),
            )
        else:
            cursor = connection.execute("DELETE FROM site_feedback")
        return cursor.rowcount or 0


# ─── Shop reviews (students → admin portal + student "My Reviews") ───


def create_review(values: dict[str, Any]) -> dict[str, Any] | None:
    """Save a student's shop review. The admin sees it on the Reviews page."""
    with _connect() as connection:
        next_id = connection.execute(
            "SELECT COALESCE(MAX(CAST(substr(id, 3) AS INTEGER)), 0) + 1 FROM reviews"
        ).fetchone()[0]
        review_id = f"rv{next_id}"
        # Resolve shop name if only shop_id was provided.
        shop_name = values.get("shop_name", "")
        if not shop_name and values.get("shop_id"):
            try:
                shop = connection.execute(
                    "SELECT name FROM shops WHERE id = ?", (values["shop_id"],)
                ).fetchone()
                if shop:
                    shop_name = shop["name"]
            except Exception:
                pass
        connection.execute(
            """
            INSERT INTO reviews (id, user_id, username, student_name, shop_id, shop_name, rating, comment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
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
        row = connection.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
        return dict(row) if row else None


def list_reviews(shop_id: str | None = None) -> list[dict[str, Any]]:
    """All reviews, newest first. Optionally filter by shop."""
    with _connect() as connection:
        if shop_id:
            rows = connection.execute(
                "SELECT * FROM reviews WHERE shop_id = ? ORDER BY rowid DESC",
                (shop_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM reviews ORDER BY rowid DESC"
            ).fetchall()
        return _rows_to_dicts(rows)


def list_reviews_by_user(user_id: int) -> list[dict[str, Any]]:
    """A student's own reviews."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM reviews WHERE user_id = ? ORDER BY rowid DESC",
            (user_id,),
        ).fetchall()
        return _rows_to_dicts(rows)


def delete_user(user_id: int) -> bool:
    """Permanently delete a user and EVERY record that references them, so a
    deleted account's username/email become re-registrable immediately and no
    stale rows keep the old data around.

    Cascades:
    - ``sessions`` (by email) — old quick-login sessions
    - ``user_registrations`` (by username) — admin registration log
    - ``site_feedback`` (by user_id) — their bug reports
    - ``password_resets`` (by username) — pending OTPs
    - ``shops`` for a shopkeeper — soft-removed (orders keep their history)

    Each cleanup is guarded so a missing/legacy table can never block the
    delete of the user row itself."""
    with _connect() as connection:
        user = connection.execute(
            "SELECT * FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not user:
            return False

        username = str(user["username"])
        email = str(user.get("email") or "").strip().lower()
        if email:
            for table in ("sessions",):
                try:
                    connection.execute(
                        f"DELETE FROM {table} WHERE LOWER(email) = ?",
                        (email,),
                    )
                except sqlite3.Error:
                    pass
        for table, where in (
            ("user_registrations", "username = ?"),
            ("password_resets", "username = ?"),
            ("site_feedback", "user_id = ?"),
        ):
            try:
                connection.execute(
                    f"DELETE FROM {table} WHERE {where}",
                    (username if "username" in where else user_id,),
                )
            except sqlite3.Error:
                pass
        if str(user.get("role") or "") == "shopkeeper" and email:
            try:
                connection.execute(
                    "UPDATE shops SET is_removed = 1, present = 0, status = 'Closed', "
                    "approval_status = 'Removed' WHERE LOWER(shopkeeper_email) = ?",
                    (email,),
                )
            except sqlite3.Error:
                pass
        cursor = connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return cursor.rowcount > 0


def get_admin_dashboard_stats(today: str) -> dict[str, Any]:
    """Admin dashboard numbers computed in SQL instead of loading every row
    into Python. ``today`` is the Asia/Kolkata date string (YYYY-MM-DD);
    SQLite stores created_at as IST wall-clock text, so substr() matches it."""
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM shops) AS total_shops,
              (SELECT COUNT(*) FROM shops WHERE approval_status = 'Approved') AS approved_shops,
              (SELECT COUNT(*) FROM shops WHERE approval_status = 'Pending Approval') AS pending_approvals,
              (SELECT COUNT(*) FROM orders) AS total_orders,
              (SELECT COUNT(*) FROM orders WHERE status NOT IN ('Completed', 'Cancelled')) AS active_orders,
              (SELECT COALESCE(SUM(total), 0) FROM orders) AS total_revenue,
              (SELECT COUNT(*) FROM orders WHERE substr(created_at, 1, 10) = ?) AS today_orders,
              (SELECT COALESCE(SUM(total), 0) FROM orders WHERE substr(created_at, 1, 10) = ?) AS today_revenue,
              (SELECT COUNT(*) FROM products) AS total_products,
              (SELECT COUNT(*) FROM payments WHERE status = 'Pending Verification') AS pending_payments
            """,
            (today, today),
        ).fetchone()
        return dict(row) if row else {}


def get_orders_grouped_by_date() -> dict[str, Any]:
    """Get orders grouped by date for revenue tracking."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT substr(created_at, 1, 10) AS day, COUNT(*) as count, SUM(total) as revenue, "
            "SUM(subtotal) as subtotal, ROUND(SUM(total) * 0.05) as service_fee, "
            "SUM(tax) as tax, SUM(delivery_fee) as delivery_fee, "
            "GROUP_CONCAT(id) as ids FROM orders GROUP BY day ORDER BY day DESC"
        ).fetchall()
        return _rows_to_dicts(rows)


def get_orders_by_date(date_key: str) -> list[dict[str, Any]]:
    """Get orders for a specific date (YYYY-MM-DD) for daily log filtering."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM orders WHERE substr(created_at, 1, 10) = ? ORDER BY token DESC",
            (date_key,),
        ).fetchall()
        return _rows_to_dicts(rows)


def get_payments_by_date(date_key: str) -> list[dict[str, Any]]:
    """Get payments for a specific date (YYYY-MM-DD) for daily log filtering."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM payments WHERE substr(created_at, 1, 10) = ? ORDER BY rowid DESC",
            (date_key,),
        ).fetchall()
        return _rows_to_dicts(rows)


def get_daily_stats() -> dict[str, Any]:
    """Get today's statistics."""
    with _connect() as connection:
        today_orders = connection.execute(
            "SELECT COUNT(*) as count, COALESCE(SUM(total), 0) as revenue, "
            "ROUND(COALESCE(SUM(total), 0) * 0.05) as service_fee "
            "FROM orders WHERE substr(created_at, 1, 10) = date('now', '+05:30')"
        ).fetchone()
        total_users = connection.execute("SELECT COUNT(*) as count FROM users").fetchone()
        total_shops = connection.execute("SELECT COUNT(*) as count FROM shops WHERE approval_status = 'Approved'").fetchone()
        total_orders = connection.execute("SELECT COUNT(*) as count FROM orders").fetchone()
        total_service_fee = connection.execute(
            "SELECT ROUND(COALESCE(SUM(total), 0) * 0.05) as total FROM orders"
        ).fetchone()
        return {
            "today_orders": dict(today_orders) if today_orders else {"count": 0, "revenue": 0, "service_fee": 0},
            "total_users": dict(total_users)["count"] if total_users else 0,
            "approved_shops": dict(total_shops)["count"] if total_shops else 0,
            "total_orders": dict(total_orders)["count"] if total_orders else 0,
            "total_service_fee": dict(total_service_fee)["total"] if total_service_fee else 0,
        }


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


def get_vendor_daily_logs(shop_id: str) -> list[dict[str, Any]]:
    """Per-day earnings + order counts for one shop (admin vendor logs)."""
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT substr(created_at, 1, 10) AS created_at, COUNT(*) as count, SUM(total) as revenue,
                   ROUND(SUM(total) * 0.05) as admin_fee
            FROM orders WHERE shop_id = ?
            GROUP BY created_at ORDER BY created_at DESC
            """,
            (shop_id,),
        ).fetchall()
        return _rows_to_dicts(rows)


def get_vendor_orders(shop_id: str) -> list[dict[str, Any]]:
    """All orders for one shop (admin vendor logs)."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM orders WHERE shop_id = ? ORDER BY created_at DESC",
            (shop_id,),
        ).fetchall()
        return _rows_to_dicts(rows)
