from __future__ import annotations

import logging
from typing import Any

from app.core import supabase_db

logger = logging.getLogger(__name__)

# ─── Auto-migrations ─────────────────────────────────────────────────────
# New columns added to the schema after the database was first created.
# Re-applied on every startup AND re-applied automatically if a query ever
# fails with a missing-column error (self-healing) — so the app never breaks
# on a database that hasn't had the latest schema.sql run against it.
_MIGRATIONS = [
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS owner_user_id text NOT NULL DEFAULT ''",
    "ALTER TABLE parent_orders ADD COLUMN IF NOT EXISTS owner_user_id text NOT NULL DEFAULT ''",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method text NOT NULL DEFAULT 'UPI'",
    # Checkout idempotency key.
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS client_ref text",
    "CREATE INDEX IF NOT EXISTS idx_orders_client_ref ON orders (client_ref)",
    # Bounded auto-confirm sweep: serves status + delivered_at range as an index scan.
    "CREATE INDEX IF NOT EXISTS idx_shop_sub_orders_status_delivered ON shop_sub_orders (status, delivered_at)",
    # WhatsApp auto-send: durable claim stamp.
    "ALTER TABLE whatsapp_logs ADD COLUMN IF NOT EXISTS claimed_at timestamptz",
    "ALTER TABLE shops ADD COLUMN IF NOT EXISTS is_removed boolean NOT NULL DEFAULT false",
    "ALTER TABLE shops ADD COLUMN IF NOT EXISTS admin_dues_balance integer NOT NULL DEFAULT 0",
    "ALTER TABLE shops ADD COLUMN IF NOT EXISTS admin_dues_last_paid_at timestamptz",
    "ALTER TABLE shops ADD COLUMN IF NOT EXISTS upi_enabled boolean NOT NULL DEFAULT true",
    "ALTER TABLE shops ADD COLUMN IF NOT EXISTS cod_enabled boolean NOT NULL DEFAULT true",
    # Multi-shop parent payments
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS parent_order_id text",
    "ALTER TABLE parent_orders ADD COLUMN IF NOT EXISTS utr_number text",
    "ALTER TABLE parent_orders ADD COLUMN IF NOT EXISTS screenshot_name text",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS pending_price integer",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS is_combo boolean NOT NULL DEFAULT false",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS combo_items text NOT NULL DEFAULT ''",
    "ALTER TABLE product_stock DROP COLUMN IF EXISTS sold",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS prep_time integer NOT NULL DEFAULT 10",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS available boolean NOT NULL DEFAULT true",
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
    "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS action text NOT NULL DEFAULT ''",
    "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS action_state text NOT NULL DEFAULT 'none'",
    "CREATE INDEX IF NOT EXISTS idx_notifications_action ON notifications (action, action_state)",
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
        source text NOT NULL DEFAULT 'User',
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "ALTER TABLE site_feedback ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'User'",
    "CREATE INDEX IF NOT EXISTS idx_site_feedback_status ON site_feedback (status)",
    "CREATE INDEX IF NOT EXISTS idx_site_feedback_user ON site_feedback (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_site_feedback_source ON site_feedback (source)",
    "CREATE INDEX IF NOT EXISTS idx_shops_shopkeeper_email_lower ON shops (LOWER(shopkeeper_email))",
    "CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders (created_at)",
    "CREATE INDEX IF NOT EXISTS idx_orders_owner_user_id ON orders (owner_user_id)",
    "CREATE INDEX IF NOT EXISTS idx_parent_orders_owner_user_id ON parent_orders (owner_user_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users (LOWER(email)) WHERE email <> ''",
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
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'active'",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url text NOT NULL DEFAULT ''",
    "CREATE INDEX IF NOT EXISTS idx_users_status ON users (status)",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS proof_status text NOT NULL DEFAULT 'PENDING_PAYMENT'",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_screenshot_url text NOT NULL DEFAULT ''",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_screenshot_public_id text NOT NULL DEFAULT ''",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_submitted_at timestamptz",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_verified_at timestamptz",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_verified_by text NOT NULL DEFAULT ''",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_rejection_reason text NOT NULL DEFAULT ''",
    "CREATE INDEX IF NOT EXISTS idx_payments_proof_status ON payments (proof_status)",
    "ALTER TABLE parent_orders ADD COLUMN IF NOT EXISTS payment_proof_status text NOT NULL DEFAULT 'PENDING_PAYMENT'",
    "ALTER TABLE parent_orders ADD COLUMN IF NOT EXISTS payment_screenshot_url text NOT NULL DEFAULT ''",
    "ALTER TABLE parent_orders ADD COLUMN IF NOT EXISTS payment_screenshot_public_id text NOT NULL DEFAULT ''",
    "ALTER TABLE parent_orders ADD COLUMN IF NOT EXISTS payment_submitted_at timestamptz",
    "ALTER TABLE parent_orders ADD COLUMN IF NOT EXISTS payment_verified_at timestamptz",
    "ALTER TABLE parent_orders ADD COLUMN IF NOT EXISTS payment_verified_by text NOT NULL DEFAULT ''",
    "ALTER TABLE parent_orders ADD COLUMN IF NOT EXISTS payment_rejection_reason text NOT NULL DEFAULT ''",
    "CREATE INDEX IF NOT EXISTS idx_parent_orders_proof_status ON parent_orders (payment_proof_status)",
    # ─── Read-path & Hot-path Performance Indexes (0002, 0003, 0005) ───
    "CREATE INDEX IF NOT EXISTS idx_orders_owner_created_at ON orders (owner_user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_parent_orders_owner_created_at ON parent_orders (owner_user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_orders_shop_created_at ON orders (shop_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_products_shop_category_name ON products (shop_id, category, name)",
    "CREATE INDEX IF NOT EXISTS idx_shops_approved_rating ON shops (approval_status, rating DESC)",
    "CREATE INDEX IF NOT EXISTS idx_parent_orders_owner_created ON parent_orders (owner_user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_orders_owner_created ON orders (owner_user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_shop_sub_orders_shop_status ON shop_sub_orders (shop_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_order_items_sub_order ON order_items (sub_order_id)",
    "CREATE INDEX IF NOT EXISTS idx_products_shop_available ON products (shop_id, available)",
    "CREATE INDEX IF NOT EXISTS idx_shops_storefront ON shops (approval_status, present, status)",
    "CREATE INDEX IF NOT EXISTS idx_notifications_role_created ON notifications (target_role, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_email_created ON sessions (lower(email), created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_payments_parent_order_id ON payments (parent_order_id)",
    "CREATE INDEX IF NOT EXISTS idx_payments_order_created ON payments (order_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_tickets_email_lower ON tickets (lower(email))",
    "CREATE INDEX IF NOT EXISTS idx_tickets_created_at ON tickets (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets (status)",
    "CREATE INDEX IF NOT EXISTS idx_reviews_created_at ON reviews (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_reviews_user_id ON reviews (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_site_feedback_created_at ON site_feedback (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_notifications_order_id ON notifications (order_id)",
    "CREATE INDEX IF NOT EXISTS idx_orders_created_at_desc ON orders (created_at DESC)",
]


def _apply_migrations() -> None:
    """Run the idempotent ALTER TABLE statements (no-op when already applied).
    Safe to call at any time — startup, or lazily after a missing-column error."""
    try:
        with supabase_db._DBContext(supabase_db._connect()) as connection:
            with connection.cursor() as cursor:
                for statement in _MIGRATIONS:
                    cursor.execute("SAVEPOINT migration_step")
                    try:
                        cursor.execute(statement)
                    except Exception as migration_error:
                        cursor.execute("ROLLBACK TO SAVEPOINT migration_step")
                        logger.warning(f"Auto-migration skipped ({statement}): {migration_error}")
                    else:
                        cursor.execute("RELEASE SAVEPOINT migration_step")
    except Exception as e:
        logger.error(f"Auto-migrations failed: {e}")
