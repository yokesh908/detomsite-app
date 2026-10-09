from __future__ import annotations

import logging
import secrets
from typing import Any

import psycopg2.errors

from app.core import supabase_db

logger = logging.getLogger(__name__)


# ─── Tickets ───


def create_ticket(values: dict[str, Any]) -> dict[str, Any]:
    with supabase_db._DBContext(supabase_db._connect()) as connection:
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
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM tickets ORDER BY created_at DESC")
            return supabase_db._rows_to_dicts(cursor.fetchall())


def list_tickets_for_user(email: str = "", name: str = "", phone: str = "") -> list[dict[str, Any]]:
    """List tickets for a specific student, filtered at database level."""
    clean_email = email.strip().lower()
    clean_name = name.strip().lower()
    clean_phone = "".join(ch for ch in phone if ch.isdigit())
    phone_pattern = f"%{clean_phone[-10:]}" if len(clean_phone) >= 10 else f"%{clean_phone}" if clean_phone else ""

    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            if clean_email:
                cursor.execute(
                    "SELECT * FROM tickets WHERE LOWER(email) = %s ORDER BY created_at DESC LIMIT 100",
                    (clean_email,)
                )
            elif clean_name and phone_pattern:
                cursor.execute(
                    "SELECT * FROM tickets WHERE LOWER(name) = %s AND phone_number LIKE %s ORDER BY created_at DESC LIMIT 100",
                    (clean_name, phone_pattern)
                )
            elif clean_name:
                cursor.execute(
                    "SELECT * FROM tickets WHERE LOWER(name) = %s ORDER BY created_at DESC LIMIT 100",
                    (clean_name,)
                )
            else:
                return []
            return supabase_db._rows_to_dicts(cursor.fetchall())


# ─── Site feedback ───


def create_site_feedback(values: dict[str, Any]) -> dict[str, Any] | None:
    """Store a student's bug report / improvement contribution.

    The admin is notified through the notifications bell (target_role='admin')
    so new contributions surface immediately on the admin Feedback page."""
    try:
        return _create_site_feedback_impl(values)
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        logger.warning("Missing site_feedback table/columns — applying auto-migrations and retrying")
        supabase_db._apply_migrations()
        return _create_site_feedback_impl(values)


def _create_site_feedback_impl(values: dict[str, Any]) -> dict[str, Any] | None:
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            _fb_sql = """
                INSERT INTO site_feedback (
                    id, user_id, username, name, email, category,
                    subject, message, page, status, source
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'Open', %s)
                """
            feedback_id = supabase_db._insert_with_suffixed_id(
                cursor, "site_feedback", "fb", _fb_sql,
                lambda rid: (
                    rid,
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
                supabase_db.create_notification(
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
        supabase_db._apply_migrations()
        return _list_site_feedback_impl(source)


def _list_site_feedback_impl(source: str | None = None) -> list[dict[str, Any]]:
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            if source:
                cursor.execute(
                    "SELECT * FROM site_feedback WHERE source = %s ORDER BY created_at DESC",
                    (source,),
                )
            else:
                cursor.execute("SELECT * FROM site_feedback ORDER BY created_at DESC")
            return supabase_db._rows_to_dicts(cursor.fetchall())


def list_site_feedback_by_user(user_id: int) -> list[dict[str, Any]]:
    """A student's own submissions (student portal "my contributions")."""
    try:
        return _list_site_feedback_by_user_impl(user_id)
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        supabase_db._apply_migrations()
        return _list_site_feedback_by_user_impl(user_id)


def _list_site_feedback_by_user_impl(user_id: int) -> list[dict[str, Any]]:
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM site_feedback WHERE user_id = %s ORDER BY created_at DESC",
                (user_id,),
            )
            return supabase_db._rows_to_dicts(cursor.fetchall())


def update_site_feedback_status(feedback_id: str, status: str) -> dict[str, Any] | None:
    """Admin marks a contribution as Open / In Review / Fixed / Won't Fix."""
    allowed = {"Open", "In Review", "Fixed", "Won't Fix"}
    if status not in allowed:
        return None
    try:
        return _update_site_feedback_status_impl(feedback_id, status)
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        supabase_db._apply_migrations()
        return _update_site_feedback_status_impl(feedback_id, status)


def _update_site_feedback_status_impl(feedback_id: str, status: str) -> dict[str, Any] | None:
    with supabase_db._DBContext(supabase_db._connect()) as connection:
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
        supabase_db._apply_migrations()
        return _delete_site_feedback_impl(source)


def _delete_site_feedback_impl(source: str | None = None) -> int:
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            if source:
                cursor.execute(
                    "DELETE FROM site_feedback WHERE source = %s",
                    (source,),
                )
            else:
                cursor.execute("DELETE FROM site_feedback")
            return cursor.rowcount


# ─── Shop reviews ───


def create_review(values: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return _create_review_impl(values)
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        supabase_db._apply_migrations()
        return _create_review_impl(values)


def _create_review_impl(values: dict[str, Any]) -> dict[str, Any] | None:
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            shop_name = values.get("shop_name", "")
            if not shop_name and values.get("shop_id"):
                try:
                    cursor.execute("SELECT name FROM shops WHERE id = %s", (values["shop_id"],))
                    row = cursor.fetchone()
                    if row:
                        shop_name = row["name"]
                except Exception:
                    pass
            review_id = supabase_db._insert_with_suffixed_id(
                cursor, "reviews", "rv",
                """INSERT INTO reviews (id, user_id, username, student_name, shop_id, shop_name, rating, comment)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                lambda rid: (
                    rid,
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
        supabase_db._apply_migrations()
        return _list_reviews_impl(shop_id)


def _list_reviews_impl(shop_id: str | None = None) -> list[dict[str, Any]]:
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            if shop_id:
                cursor.execute("SELECT * FROM reviews WHERE shop_id = %s ORDER BY created_at DESC", (shop_id,))
            else:
                cursor.execute("SELECT * FROM reviews ORDER BY created_at DESC")
            return supabase_db._rows_to_dicts(cursor.fetchall())


def list_reviews_by_user(user_id: int) -> list[dict[str, Any]]:
    try:
        return _list_reviews_by_user_impl(user_id)
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        supabase_db._apply_migrations()
        return _list_reviews_by_user_impl(user_id)


def _list_reviews_by_user_impl(user_id: int) -> list[dict[str, Any]]:
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM reviews WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
            return supabase_db._rows_to_dicts(cursor.fetchall())


# ─── Shop announcements ───


def create_shop_announcement(shop_id: str, message: str) -> dict[str, Any] | None:
    """Create a shop announcement (shown as notification bar on student page)."""
    aid = f"ann_{secrets.token_hex(8)}"
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                """INSERT INTO shop_announcements (id, shop_id, message, is_active)
                   VALUES (%s, %s, %s, true) RETURNING *""",
                (aid, shop_id, message),
            )
            connection.commit()
            return supabase_db.cursor_row(cur)
    except Exception:
        connection.rollback()
        return None
    finally:
        supabase_db._release(connection)


def list_shop_announcements(shop_id: str | None = None, active_only: bool = True) -> list[dict[str, Any]]:
    """All active (or shop-filtered) announcements."""
    with supabase_db._DBReadContext() as connection:
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
            return supabase_db._rows_to_dicts(cur.fetchall())


def toggle_shop_announcement(ann_id: str, is_active: bool) -> dict[str, Any] | None:
    """Toggle an announcement on/off."""
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE shop_announcements SET is_active = %s WHERE id = %s RETURNING *",
                (is_active, ann_id),
            )
            connection.commit()
            return supabase_db.cursor_row(cur)
    except Exception:
        connection.rollback()
        return None
    finally:
        supabase_db._release(connection)


# ─── Complaints ───


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
    connection = supabase_db._connect()
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
            return supabase_db.cursor_row(cur)
    except Exception:
        connection.rollback()
        return None
    finally:
        supabase_db._release(connection)


def list_complaints(status: str | None = None) -> list[dict[str, Any]]:
    """All complaints (optional status filter)."""
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            if status:
                cur.execute("SELECT * FROM complaints WHERE status = %s ORDER BY created_at DESC", (status,))
            else:
                cur.execute("SELECT * FROM complaints ORDER BY created_at DESC")
            return supabase_db._rows_to_dicts(cur.fetchall())
    finally:
        supabase_db._release(connection)


def update_complaint(complaint_id: str, status: str, admin_notes: str = "") -> dict[str, Any] | None:
    """Update a complaint's status + admin note."""
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE complaints SET status = %s, admin_notes = %s WHERE id = %s RETURNING *",
                (status, admin_notes, complaint_id),
            )
            connection.commit()
            return supabase_db.cursor_row(cur)
    except Exception:
        connection.rollback()
        return None
    finally:
        supabase_db._release(connection)


# ─── Refunds ───


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
    connection = supabase_db._connect()
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
            return supabase_db.cursor_row(cur)
    except Exception:
        connection.rollback()
        return None
    finally:
        supabase_db._release(connection)


def list_refunds(status: str | None = None) -> list[dict[str, Any]]:
    """All refunds (optional status filter)."""
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            if status:
                cur.execute("SELECT * FROM refunds WHERE status = %s ORDER BY created_at DESC", (status,))
            else:
                cur.execute("SELECT * FROM refunds ORDER BY created_at DESC")
            return supabase_db._rows_to_dicts(cur.fetchall())
    finally:
        supabase_db._release(connection)


def update_refund(
    refund_id: str, status: str, refund_utr: str = "", admin_notes: str = ""
) -> dict[str, Any] | None:
    """Update a refund's status (mark processed/completed etc.)."""
    connection = supabase_db._connect()
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
            return supabase_db.cursor_row(cur)
    except Exception:
        connection.rollback()
        return None
    finally:
        supabase_db._release(connection)


# ─── Settlements ───


def list_settlements(status: str | None = None) -> list[dict[str, Any]]:
    """All settlements (optional status filter)."""
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            if status:
                cur.execute("SELECT * FROM settlements WHERE status = %s ORDER BY created_at DESC", (status,))
            else:
                cur.execute("SELECT * FROM settlements ORDER BY created_at DESC")
            return supabase_db._rows_to_dicts(cur.fetchall())
    finally:
        supabase_db._release(connection)


def run_daily_settlements() -> list[dict[str, Any]]:
    """Process 9 PM settlements for all shops for today's delivered sub-orders."""
    dk = supabase_db._day_key()
    connection = supabase_db._connect()
    results: list[dict[str, Any]] = []
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT shop_id, shop_name FROM shop_sub_orders WHERE status IN ('Delivered', 'Completed') AND created_at::date = %s::date",
                (dk,),
            )
            shop_rows = supabase_db._rows_to_dicts(cur.fetchall())
            for shop in shop_rows:
                sid = shop["shop_id"]
                cur.execute(
                    "SELECT COALESCE(SUM(subtotal), 0) AS gross, COUNT(*) AS cnt FROM shop_sub_orders WHERE shop_id = %s AND status IN ('Delivered', 'Completed') AND created_at::date = %s::date",
                    (sid, dk),
                )
                _row = supabase_db.cursor_row(cur)
                gross = int(_row["gross"])
                commission = int(_row["cnt"] or 0) * 10
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
                results.append(supabase_db.cursor_row(cur))
            connection.commit()
            return results
    except Exception:
        connection.rollback()
        return results
    finally:
        supabase_db._release(connection)


# ─── Menu change requests ───


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
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                """INSERT INTO menu_change_requests (
                       id, shop_id, product_id, change_type, field_name, old_value, new_value, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'Pending') RETURNING *""",
                (mid, shop_id, product_id, change_type, field_name, old_value, new_value),
            )
            connection.commit()
            return supabase_db.cursor_row(cur)
    except Exception:
        connection.rollback()
        return None
    finally:
        supabase_db._release(connection)


def list_menu_change_requests(status: str | None = None) -> list[dict[str, Any]]:
    """Menu change requests (optional status filter)."""
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            if status:
                cur.execute("SELECT * FROM menu_change_requests WHERE status = %s ORDER BY created_at DESC", (status,))
            else:
                cur.execute("SELECT * FROM menu_change_requests ORDER BY created_at DESC")
            return supabase_db._rows_to_dicts(cur.fetchall())
    finally:
        supabase_db._release(connection)


def update_menu_change_request(req_id: str, status: str, admin_notes: str = "") -> dict[str, Any] | None:
    """Approve/reject a menu change request."""
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE menu_change_requests SET status = %s, admin_notes = %s, reviewed_at = NOW() WHERE id = %s RETURNING *",
                (status, admin_notes, req_id),
            )
            connection.commit()
            return supabase_db.cursor_row(cur)
    except Exception:
        connection.rollback()
        return None
    finally:
        supabase_db._release(connection)


# ─── Audit & SMS & WhatsApp logs ───


def add_audit_log(
    actor: str,
    actor_role: str,
    action: str,
    target_type: str = "",
    target_id: str = "",
    details: str = "",
) -> None:
    connection = supabase_db._connect()
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
        supabase_db._release(connection)


def list_audit_logs(limit: int = 200) -> list[dict[str, Any]]:
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT %s", (limit,))
            return supabase_db._rows_to_dicts(cur.fetchall())
    finally:
        supabase_db._release(connection)


def list_whatsapp_logs(limit: int = 100) -> list[dict[str, Any]]:
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT * FROM whatsapp_logs ORDER BY created_at DESC LIMIT %s", (limit,))
            return supabase_db._rows_to_dicts(cur.fetchall())
    finally:
        supabase_db._release(connection)


def log_whatsapp(
    sub_order_id: str = "",
    phone: str = "",
    message: str = "",
    url: str = "",
    status: str = "Pending",
) -> dict[str, Any] | None:
    """Persist one WhatsApp notification (link generated, ready to send).

    Note: the Supabase ``whatsapp_logs`` table stores the order reference in
    ``order_id`` (there is no ``sub_order_id``/``url`` column there), so the
    ``url`` is dropped at rest and rebuilt by the API when serving it."""
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                """INSERT INTO whatsapp_logs (order_id, phone, message, message_type, status)
                   VALUES (%s, %s, %s, %s, %s) RETURNING *""",
                (sub_order_id or "", phone or "", message or "", "shop_order", status),
            )
            row = supabase_db._rows_to_dicts(cur.fetchall())[0]
            connection.commit()  # without this the RETURNING row is rolled back
            return row
    finally:
        supabase_db._release(connection)


def mark_whatsapp_sent(whatsapp_id: str) -> dict[str, Any] | None:
    """Mark a WhatsApp notification as sent."""
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE whatsapp_logs SET status = 'Sent' WHERE id = %s RETURNING *",
                (whatsapp_id,),
            )
            row = supabase_db._rows_to_dicts(cur.fetchall())[0]
            connection.commit()  # without this the update is rolled back
            return row
    finally:
        supabase_db._release(connection)


def update_whatsapp_message(whatsapp_id: str, message: str, url: str = "") -> dict[str, Any] | None:
    """Refresh a pending WhatsApp notification (e.g. payment flipped to paid)."""
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE whatsapp_logs SET message = %s WHERE id = %s RETURNING *",
                (message or "", whatsapp_id),
            )
            row = cur.fetchall()
            result = supabase_db._rows_to_dicts(row)[0] if row else None
            if result:
                connection.commit()  # freshness only lands when committed
            return result
    finally:
        supabase_db._release(connection)


def log_sms(
    sub_order_id: str = "",
    phone: str = "",
    message: str = "",
    status: str = "Sent",
    direction: str = "out",
) -> dict[str, Any] | None:
    """Persist one SMS (out = sent to a phone, in = received from a phone)."""
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                """INSERT INTO sms_logs (sub_order_id, phone, message, direction, status)
                   VALUES (%s, %s, %s, %s, %s) RETURNING *""",
                (sub_order_id, phone or "", message or "", direction, status),
            )
            row = supabase_db._rows_to_dicts(cur.fetchall())[0]
            connection.commit()  # without this the RETURNING row is rolled back
            return row
    finally:
        supabase_db._release(connection)


def list_sms_logs(limit: int = 100) -> list[dict[str, Any]]:
    connection = supabase_db._connect()
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT * FROM sms_logs ORDER BY created_at DESC LIMIT %s", (limit,))
            return supabase_db._rows_to_dicts(cur.fetchall())
    finally:
        supabase_db._release(connection)
