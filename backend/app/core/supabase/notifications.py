from __future__ import annotations

import logging
from typing import Any

import psycopg2.errors

from app.core import supabase_db

logger = logging.getLogger(__name__)

NOTIFICATION_LIST_LIMIT = 60


def create_notification(
    title: str,
    message: str,
    order_id: str | None = None,
    status: str | None = None,
    target_role: str | None = None,
    action: str = "",
    action_state: str = "none",
    connection: Any | None = None,
) -> dict[str, Any] | None:
    """Insert one notification.

    ``action``/``action_state`` carry an INLINE admin action for the notification
    bell (e.g. ``action="confirm_order"``, ``action_state="pending"``). They are
    keyword-only in practice and default to "no action", so every existing caller
    keeps working untouched.
    """
    owns_connection = connection is None
    active_connection = connection or supabase_db._connect()
    cursor = None
    try:
        cursor = active_connection.cursor()
        # MAX (not COUNT) so deletes can never reuse an id, AND a retry on a
        # concurrent collision so a lost insert can never drop the admin's
        # "confirm this order" queue row (see _insert_with_suffixed_id).
        notification_id = supabase_db._insert_with_suffixed_id(
            cursor, "notifications", "n",
            """INSERT INTO notifications (id, title, message, order_id, status, target_role, action, action_state)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            lambda rid: (rid, title, message, order_id, status, target_role, action or "", action_state or "none"),
        )
        cursor.execute("SELECT * FROM notifications WHERE id = %s", (notification_id,))
        row = cursor.fetchone()
        if owns_connection:
            active_connection.commit()
        return dict(row) if row else None
    except (psycopg2.errors.UndefinedColumn,):
        # A deployment whose notifications table predates the inline-action
        # columns. Apply the migrations and retry once so the bell never 500s.
        logger.warning("Missing notification action columns — applying auto-migrations and retrying")
        if owns_connection:
            supabase_db._release(active_connection)
            active_connection = None
        supabase_db._apply_migrations()
        return create_notification(
            title, message, order_id, status, target_role, action, action_state, connection=None
        )
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if owns_connection and active_connection is not None:
            supabase_db._release(active_connection)


def list_notifications(role: str | None = None) -> list[dict[str, Any]]:
    """List notifications. When ``role`` is given, only notifications targeted at
    that exact role are returned (strict role separation).

    Rows that still carry a PENDING admin action are always kept at the top (and
    never truncated away) so an un-confirmed order can't fall off the bell.
    """
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            if role:
                cursor.execute(
                    """SELECT * FROM notifications
                       WHERE target_role = %s
                       ORDER BY (CASE WHEN action <> '' AND action_state = 'pending' THEN 0 ELSE 1 END),
                                 created_at DESC
                       LIMIT %s""",
                    (role, NOTIFICATION_LIST_LIMIT),
                )
            else:
                cursor.execute(
                    """SELECT * FROM notifications
                       ORDER BY (CASE WHEN action <> '' AND action_state = 'pending' THEN 0 ELSE 1 END),
                                 created_at DESC
                       LIMIT %s""",
                    (NOTIFICATION_LIST_LIMIT,),
                )
            return supabase_db._rows_to_dicts(cursor.fetchall())


def list_student_notifications(user_id: int) -> list[dict[str, Any]]:
    """List notifications for a student in ONE query.
    Eliminates the N+1 sequential order lookup loop."""
    uid_str = str(user_id)
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT n.*
                FROM notifications n
                WHERE n.target_role = 'student'
                  AND (
                    n.order_id IS NULL
                    OR EXISTS (
                      SELECT 1 FROM orders o
                      WHERE o.id = n.order_id AND (o.owner_user_id = %s OR o.owner_user_id = '' OR o.owner_user_id IS NULL)
                    )
                    OR EXISTS (
                      SELECT 1 FROM parent_orders po
                      WHERE po.id = n.order_id AND po.owner_user_id = %s
                    )
                    OR EXISTS (
                      SELECT 1 FROM shop_sub_orders sso
                      JOIN parent_orders po2 ON po2.id = sso.parent_order_id
                      WHERE sso.id = n.order_id AND po2.owner_user_id = %s
                    )
                  )
                ORDER BY n.created_at DESC
                LIMIT 50
                """,
                (uid_str, uid_str, uid_str),
            )
            return supabase_db._rows_to_dicts(cursor.fetchall())


def list_actionable_notifications(action: str, action_state: str = "pending") -> list[dict[str, Any]]:
    """Every notification carrying a given inline action in a given state.

    Powers the admin "Approvals" queue — a narrow, indexed read (no scan of the
    whole table) so the page stays instant even with a long notification history.
    """
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT * FROM notifications
                   WHERE action = %s AND action_state = %s
                   ORDER BY created_at DESC
                   LIMIT 50""",
                (action, action_state),
            )
            return supabase_db._rows_to_dicts(cursor.fetchall())


def set_notification_action_state(
    notification_id: str, action_state: str
) -> dict[str, Any] | None:
    """Move a notification's inline action to a new state (pending → done).

    Returns the updated row, or ``None`` when the id doesn't exist. A row whose
    action was already settled returns that row unchanged, which is what makes
    the confirm button safe to double-tap.
    """
    try:
        return _set_notification_action_state_impl(notification_id, action_state)
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        logger.warning("Missing notification action columns — applying auto-migrations and retrying")
        supabase_db._apply_migrations()
        return _set_notification_action_state_impl(notification_id, action_state)


def _set_notification_action_state_impl(
    notification_id: str, action_state: str
) -> dict[str, Any] | None:
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                """UPDATE notifications SET action_state = %s
                   WHERE id = %s
                   RETURNING *""",
                (action_state, notification_id),
            )
            row = supabase_db._rows_to_dicts(cur.fetchall())[0] if cur.rowcount else None
            if row:
                connection.commit()
            return row
    except Exception:
        connection.rollback()
        return None
    finally:
        supabase_db._release(connection)


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
        supabase_db._apply_migrations()
        return _save_push_subscription_impl(shop_id, endpoint, p256dh, auth)


def _save_push_subscription_impl(
    shop_id: str,
    endpoint: str,
    p256dh: str,
    auth: str,
) -> dict[str, Any] | None:
    with supabase_db._DBContext(supabase_db._connect()) as connection:
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
        supabase_db._apply_migrations()
        return _list_push_subscriptions_impl(shop_id)


def _list_push_subscriptions_impl(shop_id: str) -> list[dict[str, Any]]:
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM push_subscriptions WHERE shop_id = %s ORDER BY created_at",
                (shop_id,),
            )
            return supabase_db._rows_to_dicts(cursor.fetchall())


def remove_push_subscription(shop_id: str, endpoint: str) -> bool:
    """Remove a push subscription (e.g. when the browser reports it's dead)."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM push_subscriptions WHERE endpoint = %s AND shop_id = %s",
                (endpoint, shop_id),
            )
            return cursor.rowcount > 0
