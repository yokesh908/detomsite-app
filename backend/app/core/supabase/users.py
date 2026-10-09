from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import psycopg2
import psycopg2.errors

from app.core import supabase_db, ttl_cache
from app.core.config import settings


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
    with supabase_db._DBContext(supabase_db._connect()) as connection:
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
    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE username = %s", (username.lower(),))
            row = cursor.fetchone()
            return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    """Get user by id (without password_hash). Cached in memory for 15s to eliminate
    redundant DB roundtrips on every authenticated request."""
    cache_k = f"user:id:{user_id}"
    cached = ttl_cache.get(cache_k)
    if cached is not None:
        return cached

    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, username, name, email, phone, role, created_at FROM users WHERE id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
            result = dict(row) if row else None
            if result is not None:
                ttl_cache.set(cache_k, result, ttl=15.0)
            return result


def save_session(email: str, name: str, role: str) -> dict[str, Any]:
    with supabase_db._DBContext(supabase_db._connect()) as connection:
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


def list_users() -> list[dict[str, Any]]:
    """List all registered users (without password_hash) with summary order/spend metrics.
    Cached for 10s for fast admin directory paging/browsing."""
    cache_k = "admin:users_list"
    cached = ttl_cache.get(cache_k)
    if cached is not None:
        return cached

    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT 
                    u.id, 
                    u.username, 
                    u.name, 
                    u.email, 
                    u.phone, 
                    u.role, 
                    COALESCE(u.status, 'active') as status,
                    COALESCE(u.avatar_url, '') as avatar_url,
                    u.created_at,
                    COALESCE(ord.orders_count, 0) as orders_count,
                    COALESCE(ord.total_spent, 0) as total_spent,
                    sess.last_login
                FROM users u
                LEFT JOIN (
                    SELECT 
                        u_inner.id as user_id,
                        COUNT(o.id) as orders_count,
                        COALESCE(SUM(CASE WHEN o.status IN ('Completed', 'Delivered') THEN o.total ELSE 0 END), 0) as total_spent
                    FROM users u_inner
                    LEFT JOIN orders o ON (
                        o.owner_user_id = u_inner.id::text 
                        OR (o.owner_user_id = '' AND lower(o.student_name) = lower(u_inner.name))
                        OR (o.student_phone <> '' AND o.student_phone = u_inner.phone)
                    )
                    GROUP BY u_inner.id
                ) ord ON ord.user_id = u.id
                LEFT JOIN (
                    SELECT 
                        lower(email) as s_email,
                        MAX(created_at) as last_login
                    FROM sessions
                    WHERE email <> ''
                    GROUP BY lower(email)
                ) sess ON sess.s_email = lower(u.email)
                ORDER BY u.created_at DESC
                """
            )
            rows = supabase_db._rows_to_dicts(cursor.fetchall())
            ttl_cache.set(cache_k, rows, ttl=10.0)
            return rows


def get_user_overview(user_id: int) -> dict[str, Any] | None:
    """Retrieve full 360 overview of a user: profile, stats, orders, payments, addresses, reviews, feedback, activity.
    Uses _DBReadContext and 15s TTL cache."""
    cache_k = f"admin:user_overview:{user_id}"
    cached = ttl_cache.get(cache_k)
    if cached is not None:
        return cached

    with supabase_db._DBReadContext() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, username, name, email, phone, role, 
                       COALESCE(status, 'active') as status,
                       COALESCE(avatar_url, '') as avatar_url,
                       created_at
                FROM users WHERE id = %s
                """,
                (user_id,)
            )
            user_row = cursor.fetchone()
            if not user_row:
                return None
            user = dict(user_row)

            # Get last login
            cursor.execute(
                "SELECT created_at FROM sessions WHERE lower(email) = lower(%s) ORDER BY created_at DESC LIMIT 1",
                (user.get("email", ""),)
            )
            sess_row = cursor.fetchone()
            user["last_login"] = sess_row["created_at"] if sess_row else None

            # User orders
            uid_str = str(user_id)
            cursor.execute(
                """
                SELECT id, token, student_name, student_phone, shop_id, shop_name, items,
                       subtotal, service_fee, tax, delivery_fee, total,
                       delivery_location, delivery_slot, status, payment_method, created_at
                FROM orders
                WHERE owner_user_id = %s
                   OR (owner_user_id = '' AND lower(student_name) = lower(%s))
                   OR (student_phone <> '' AND student_phone = %s)
                ORDER BY created_at DESC
                """,
                (uid_str, user.get("name", ""), user.get("phone", ""))
            )
            orders = supabase_db._rows_to_dicts(cursor.fetchall())

            # Payments
            order_ids = [o["id"] for o in orders]
            payments = []
            if order_ids:
                cursor.execute(
                    """
                    SELECT id, order_id, amount, method, status, utr_number, created_at
                    FROM payments
                    WHERE order_id = ANY(%s)
                    ORDER BY created_at DESC
                    """,
                    (order_ids,)
                )
                payments = supabase_db._rows_to_dicts(cursor.fetchall())

            # Reviews
            cursor.execute(
                """
                SELECT id, shop_id, shop_name, rating, comment, created_at
                FROM reviews
                WHERE user_id = %s OR lower(username) = lower(%s)
                ORDER BY created_at DESC
                """,
                (user_id, user.get("username", ""))
            )
            reviews = supabase_db._rows_to_dicts(cursor.fetchall())

            # Feedback
            cursor.execute(
                """
                SELECT id, category, subject, message, page, status, source, created_at
                FROM site_feedback
                WHERE user_id = %s OR lower(username) = lower(%s) OR (email <> '' AND lower(email) = lower(%s))
                ORDER BY created_at DESC
                """,
                (user_id, user.get("username", ""), user.get("email", ""))
            )
            feedback = supabase_db._rows_to_dicts(cursor.fetchall())

            # Addresses
            addresses_map = {}
            for o in orders:
                loc = (o.get("delivery_location") or "").strip()
                if not loc:
                    continue
                slot = (o.get("delivery_slot") or "").strip()
                key = f"{loc}::{slot}".lower()
                if key not in addresses_map:
                    addresses_map[key] = {
                        "location": loc,
                        "slot": slot,
                        "order_count": 1,
                        "last_used": o.get("created_at"),
                    }
                else:
                    addresses_map[key]["order_count"] += 1
            addresses = sorted(addresses_map.values(), key=lambda a: a["order_count"], reverse=True)

            # Shop
            shop = None
            if user.get("role") == "shopkeeper":
                cursor.execute(
                    """
                    SELECT id, name, category, description, rating, status, approval_status,
                           orders_today, revenue_today, upi_id, cod_enabled, admin_dues_balance, phone
                    FROM shops
                    WHERE lower(shopkeeper_email) = lower(%s) OR (phone <> '' AND phone = %s)
                    LIMIT 1
                    """,
                    (user.get("email", ""), user.get("phone", ""))
                )
                s_row = cursor.fetchone()
                if s_row:
                    shop = dict(s_row)

            # Stats
            total_orders = len(orders)
            completed_orders = sum(1 for o in orders if o.get("status") in ("Completed", "Delivered"))
            cancelled_orders = sum(1 for o in orders if o.get("status") in ("Cancelled", "Rejected", "Failed"))
            pending_orders = sum(1 for o in orders if o.get("status") in ("Pending Acceptance", "Pending Payment", "Accepted", "Preparing", "Ready", "Placed"))
            total_spent = sum(o.get("total", 0) for o in orders if o.get("status") in ("Completed", "Delivered"))

            cursor.execute(
                "SELECT COUNT(*) as cnt FROM refunds WHERE lower(student_name) = lower(%s)",
                (user.get("name", ""),)
            )
            ref_row = cursor.fetchone()
            refunds_count = ref_row["cnt"] if ref_row else 0

            stats = {
                "total_orders": total_orders,
                "total_spent": total_spent,
                "completed_orders": completed_orders,
                "cancelled_orders": cancelled_orders,
                "pending_orders": pending_orders,
                "refunds_count": refunds_count,
                "reviews_count": len(reviews),
                "feedback_count": len(feedback),
            }

            # Activity Timeline
            activity_events = []
            if user.get("created_at"):
                activity_events.append({
                    "id": f"reg-{user_id}",
                    "type": "registration",
                    "title": "Account Registered",
                    "description": f"Created {user.get('role', 'student')} account as @{user.get('username')}",
                    "timestamp": user["created_at"],
                })

            cursor.execute(
                "SELECT created_at FROM sessions WHERE lower(email) = lower(%s) ORDER BY created_at DESC LIMIT 5",
                (user.get("email", ""),)
            )
            for idx, s in enumerate(cursor.fetchall()):
                activity_events.append({
                    "id": f"sess-{idx}",
                    "type": "login",
                    "title": "Account Sign-in",
                    "description": "Authenticated session started",
                    "timestamp": s["created_at"],
                })

            for o in orders[:25]:
                activity_events.append({
                    "id": f"ord-{o['id']}",
                    "type": "order",
                    "title": f"Placed Order #{o['token'] or o['id']}",
                    "description": f"Order total ₹{o.get('total', 0)} ({o.get('status')}) at {o.get('shop_name', 'Campus Kitchen')}",
                    "timestamp": o["created_at"],
                    "status": o.get("status"),
                })

            for r in reviews[:15]:
                activity_events.append({
                    "id": f"rev-{r['id']}",
                    "type": "review",
                    "title": f"Reviewed {r.get('shop_name', 'Shop')}",
                    "description": f"{r.get('rating')}★: \"{r.get('comment', '')[:80]}\"",
                    "timestamp": r["created_at"],
                })

            for f in feedback[:15]:
                activity_events.append({
                    "id": f"fb-{f['id']}",
                    "type": "feedback",
                    "title": f"Submitted {f.get('category', 'Feedback')}",
                    "description": f.get("subject", ""),
                    "timestamp": f["created_at"],
                    "status": f.get("status"),
                })

            def _get_ts(e):
                ts = e.get("timestamp")
                if isinstance(ts, str):
                    try:
                        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except Exception:
                        return datetime.min.replace(tzinfo=timezone.utc)
                if isinstance(ts, datetime):
                    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
                return datetime.min.replace(tzinfo=timezone.utc)

            activity_events.sort(key=_get_ts, reverse=True)

            res = {
                "user": user,
                "stats": stats,
                "orders": orders,
                "payments": payments,
                "addresses": addresses,
                "reviews": reviews,
                "feedback": feedback,
                "activity": activity_events[:50],
                "shop": shop,
            }
            ttl_cache.set(cache_k, res, ttl=15.0)
            return res


def update_user_admin(user_id: int, updates: dict[str, Any]) -> dict[str, Any] | None:
    """Admin update of user fields: name, email, phone, role, status."""
    allowed = {"name", "email", "phone", "role", "status"}
    filtered = {k: v for k, v in updates.items() if k in allowed and v is not None}
    if not filtered:
        return get_user_by_id(user_id)

    set_clauses = []
    params = []
    for k, v in filtered.items():
        set_clauses.append(f"{k} = %s")
        params.append(str(v).strip())
    params.append(user_id)

    ttl_cache.pop(f"user:id:{user_id}")
    ttl_cache.pop(f"admin:user_overview:{user_id}")
    ttl_cache.pop("admin:users_list")

    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE users SET {', '.join(set_clauses)} WHERE id = %s RETURNING id, username, name, email, phone, role, status, created_at",
                tuple(params),
            )
            row = cursor.fetchone()
            return dict(row) if row else None


def set_user_status(user_id: int, status: str) -> bool:
    """Set status ('active' | 'blocked')."""
    ttl_cache.pop(f"user:id:{user_id}")
    ttl_cache.pop(f"admin:user_overview:{user_id}")
    ttl_cache.pop("admin:users_list")

    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE users SET status = %s WHERE id = %s", (status, user_id))
            return cursor.rowcount > 0


def list_users_by_role(role: str) -> list[dict[str, Any]]:
    """List users filtered by role."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT 
                    u.id, 
                    u.username, 
                    u.name, 
                    u.email, 
                    u.phone, 
                    u.role, 
                    COALESCE(u.status, 'active') as status,
                    COALESCE(u.avatar_url, '') as avatar_url,
                    u.created_at,
                    COALESCE(ord.orders_count, 0) as orders_count,
                    COALESCE(ord.total_spent, 0) as total_spent,
                    sess.last_login
                FROM users u
                LEFT JOIN (
                    SELECT 
                        u_inner.id as user_id,
                        COUNT(o.id) as orders_count,
                        COALESCE(SUM(CASE WHEN o.status IN ('Completed', 'Delivered') THEN o.total ELSE 0 END), 0) as total_spent
                    FROM users u_inner
                    LEFT JOIN orders o ON (
                        o.owner_user_id = u_inner.id::text 
                        OR (o.owner_user_id = '' AND lower(o.student_name) = lower(u_inner.name))
                        OR (o.student_phone <> '' AND o.student_phone = u_inner.phone)
                    )
                    GROUP BY u_inner.id
                ) ord ON ord.user_id = u.id
                LEFT JOIN (
                    SELECT 
                        lower(email) as s_email,
                        MAX(created_at) as last_login
                    FROM sessions
                    WHERE email <> ''
                    GROUP BY lower(email)
                ) sess ON sess.s_email = lower(u.email)
                WHERE u.role = %s
                ORDER BY u.created_at DESC
                """,
                (role,),
            )
            return supabase_db._rows_to_dicts(cursor.fetchall())


def record_registration(user: dict[str, Any]) -> None:
    """Record a user registration for admin notifications."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO user_registrations (username, name, email, phone, role) VALUES (%s, %s, %s, %s, %s)",
                (user.get("username", ""), user.get("name", ""), user.get("email", ""), user.get("phone", ""), user.get("role", "")),
            )


def list_registrations() -> list[dict[str, Any]]:
    """List all user registrations for admin."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM user_registrations ORDER BY created_at DESC")
            return supabase_db._rows_to_dicts(cursor.fetchall())


def get_user_by_email(email: str) -> dict[str, Any] | None:
    """Find a user by their registered email (case-insensitive)."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
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
    with supabase_db._DBContext(supabase_db._connect()) as connection:
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
    with supabase_db._DBContext(supabase_db._connect()) as connection:
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
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE password_resets SET attempts = attempts + 1 WHERE username = %s AND used = false",
                (username.lower(),),
            )


def invalidate_password_resets(username: str) -> None:
    """Mark every pending reset code for this user as used."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE password_resets SET used = true WHERE username = %s",
                (username.lower(),),
            )


def update_user_password(username: str, new_password_hash: str) -> bool:
    """Set a new password hash for a user (by username)."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET password_hash = %s WHERE username = %s",
                (new_password_hash, username.lower()),
            )
            return cursor.rowcount > 0


def update_user_profile(user_id: int, name: str | None = None, email: str | None = None, phone: str | None = None) -> dict[str, Any] | None:
    """Update a user's editable profile fields (name, email, phone) by id.
    Returns the full clean user row (without password_hash) or None if the
    user doesn't exist. Email is left untouched when not provided so a caller
    can't accidentally blank it."""
    updates: list[str] = []
    params: list[Any] = []
    if name is not None:
        updates.append("name = %s")
        params.append(name.strip() or "")
    if email is not None:
        updates.append("email = %s")
        params.append(email.strip())
    if phone is not None:
        updates.append("phone = %s")
        params.append(phone.strip())
    if not updates:
        return get_user_by_id(user_id)
    params.append(user_id)
    with supabase_db._DBContext(supabase_db._connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = %s", params)
            cursor.execute(
                "SELECT id, username, name, email, phone, role, created_at FROM users WHERE id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None


def delete_user(user_id: int) -> bool:
    """Permanently delete a user and EVERY record that references them, so a
    deleted account's username/email become re-registrable immediately and no
    stale rows keep the old data around."""
    with supabase_db._DBContext(supabase_db._connect()) as connection:
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
