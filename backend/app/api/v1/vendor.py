"""
Vendor Portal API — Shopkeeper registration, shop management, orders
"""
from fastapi import APIRouter, HTTPException, Depends, Header, Query, Request
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Any
from datetime import datetime, timedelta, timezone
import logging
import traceback

from app.core.config import settings
from app.core.rate_limit import allow as rate_allow, reset as rate_reset, client_ip as rate_ip
from app.core.store import store as db
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token
from app.services import push_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Schemas ───

class VendorRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., max_length=100)
    password: str = Field(..., min_length=4, max_length=128)
    name: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., max_length=15)
    shop_name: str = Field(..., min_length=2, max_length=100)
    shop_category: str = Field(..., max_length=50)
    shop_description: str = Field(default="", max_length=500)
    upi_id: str = Field(default="", max_length=100)


class VendorLoginRequest(BaseModel):
    username: str
    password: str


class VendorResponse(BaseModel):
    id: int
    username: str
    name: str
    role: str
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: VendorResponse


class ShopStatusUpdate(BaseModel):
    present: bool | None = None
    status: str | None = None
    opening_time: str | None = None
    closing_time: str | None = None
    upi_id: str | None = None
    upi_enabled: bool | None = None
    cod_enabled: bool | None = None
    category: str | None = None


class AdminDuesPayment(BaseModel):
    amount: int | None = None


# ─── Helper ───
# NOTE: these are *sync* endpoints on purpose. The data store is synchronous
# (psycopg2/SQLite), and running blocking DB calls inside `async def` handlers
# stalls FastAPI's event loop — which is what makes the app feel slow under
# load. Sync `def` handlers are executed by FastAPI in a thread pool, so DB
# calls no longer block other requests.

def get_current_vendor(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid authorization scheme")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    user = db.get_user_by_id(int(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user["role"] != "shopkeeper":
        raise HTTPException(status_code=403, detail="This endpoint is for shopkeepers only")
    return user


def _find_shop(current_vendor: dict) -> dict | None:
    """The vendor's shop, or ``None``.

    Some shops are auto-created with the shopkeeper's real email, others with
    ``{username}@campus.local`` — so check both (one indexed lookup each) before
    giving up. Every vendor endpoint used to look up ONLY the campus.local
    address, which meant a vendor who registered with their real email got
    "Shop not found" from the product, order and dashboard routes.
    """
    for vendor_email in (current_vendor.get("email") or "", f"{current_vendor['username']}@campus.local"):
        if not vendor_email:
            continue
        shop = db.get_shop_by_shopkeeper_email(vendor_email)
        if shop:
            return shop
    return None


def _my_shop(current_vendor: dict) -> dict:
    """The vendor's shop — 404 when the account has no shop attached."""
    shop = _find_shop(current_vendor)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    return shop


def _sub_order_shape(sub: dict) -> dict:
    """Render a multi-shop sub-order as an order-shaped dict so the vendor
    dashboard/flows treat single and multi orders the same way."""
    items = sub.get("items") or []
    parent = sub.get("parent") or {}
    return {
        "id": sub.get("id", ""),
        "token": sub.get("token"),
        "student_name": parent.get("student_name", ""),
        "student_phone": parent.get("student_phone", ""),
        "shop_id": sub.get("shop_id", ""),
        "shop_name": sub.get("shop_name", ""),
        "items": ", ".join(f"{int(i['quantity'])}x {i['product_name']}" for i in items),
        "total": int(sub.get("subtotal", 0)),
        "delivery_location": parent.get("delivery_location", ""),
        "delivery_slot": sub.get("batch_type") or parent.get("delivery_slot", ""),
        "status": sub.get("status", "Pending"),
        "payment_method": parent.get("payment_method", ""),
        "created_at": sub.get("created_at", ""),
        "parent_order_id": sub.get("parent_order_id", ""),
        "is_sub_order": True,
    }


def _shop_orders_merged(shop_id: str, limit: int | None = None) -> list[dict]:
    """Single orders + multi-shop sub-orders for ONE shop, newest first.
    Multi orders live in ``shop_sub_orders`` (not ``orders``) — without this
    merge the vendor never saw them, so multi-basket orders were invisible."""
    single = db.list_orders_by_shop(shop_id)
    subs = db.get_shop_sub_orders(shop_id)
    merged = list(single) + [_sub_order_shape(s) for s in subs]
    merged.sort(key=lambda o: str(o.get("created_at") or ""), reverse=True)
    if limit:
        return merged[:limit]
    return merged


# ─── Endpoints ───

@router.post("/register", status_code=201)
def register(data: VendorRegisterRequest, request: Request):
    """Register a new shopkeeper and auto-create their shop (Pending Approval)."""
    if not rate_allow("vendor_register", rate_ip(request), max_attempts=20, window_sec=3600):
        raise HTTPException(status_code=429, detail="Too many shop registrations from this network — try again later.")
    password_hash = hash_password(data.password)
    user, conflict = db.register_user(
        username=data.username,
        password_hash=password_hash,
        name=data.name,
        email=data.email,
        phone=data.phone,
        role="shopkeeper",
    )
    if conflict == "username":
        raise HTTPException(status_code=409, detail="Username already taken")
    if conflict == "email" or not user:
        # One email = one account across the whole platform, no matter the role.
        raise HTTPException(status_code=409, detail="This email is already registered. Try signing in instead.")

    # Auto-create shop with Pending Approval status
    try:
        shop = db.create_shop({
            "name": data.shop_name,
            "category": data.shop_category,
            "description": data.shop_description or f"{data.shop_name} - New vendor",
            "shopkeeper_email": data.email or f"{data.username}@campus.local",
            "shopkeeper_name": data.name,
            "phone": data.phone,
            "opening_time": "09:00 AM",
            "closing_time": "09:00 PM",
            "upi_id": data.upi_id,
        })
        logger.info(f"Shop '{data.shop_name}' created for vendor {data.username}")
    except Exception as e:
        logger.warning(f"Could not auto-create shop for {data.username}: {e}")
        shop = None

    # Record registration for admin notification
    try:
        db.record_registration(user)
    except Exception as e:
        logger.warning(f"Could not record vendor registration: {e}")

    # Notify the admin that a new vendor is waiting for approval
    try:
        db.create_notification(
            title="New vendor registration",
            message=f"{data.name} registered '{data.shop_name}' — pending admin approval.",
            target_role="admin",
        )
        # Ring the admin's phone too (best-effort, fire-and-forget).
        push_service.notify_admin_async(
            "New vendor registration",
            f"{data.name} registered '{data.shop_name}' — pending approval in Admin Center.",
            {"url": "/admin-dashboard", "tag": "vendor-reg"},
        )
    except Exception as e:
        logger.warning(f"Could not notify admin of vendor registration: {e}")

    return {
        "message": "Vendor registered successfully. Your shop is pending admin approval.",
        "user": user,
        "shop": shop,
    }


@router.post("/login")
def login(data: VendorLoginRequest, request: Request):
    """Login as a shopkeeper."""
    ip = rate_ip(request)
    if not rate_allow("vendor_login", f"{data.username}:{ip}", max_attempts=40, window_sec=300):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts — please wait a few minutes and try again.")
    user = db.get_user_by_username(data.username)
    # PENTEST FIX: identical message for "no such user" and "wrong password",
    # and the password is checked BEFORE the role hint — otherwise the distinct
    # 401/403 replies (and their order) let an attacker enumerate which
    # shop usernames exist on the platform.
    bad_credentials = "Invalid username or password."
    if not user or not verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail=bad_credentials)
    if user["role"] != "shopkeeper":
        raise HTTPException(status_code=403, detail=f"This account is a {user['role']} account — please sign in from the {user['role']} portal instead.")
    rate_reset("vendor_login", f"{data.username}:{ip}")

    token_data = {
        "sub": str(user["id"]),
        "username": user["username"],
        "name": user["name"],
        "role": user["role"],
    }
    return AuthResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
        user=VendorResponse(
            id=user["id"],
            username=user["username"],
            name=user["name"],
            role=user["role"],
            created_at=user["created_at"],
        ),
    )


@router.get("/dashboard")
def dashboard(current_vendor: dict = Depends(get_current_vendor)):
    """Get vendor dashboard with shop details, orders, and admin dues (₹10 per order)."""
    my_shop = _find_shop(current_vendor)

    if not my_shop:
        return {
            "user": current_vendor,
            "shop": None,
            "orders": [],
            "stats": {"message": "No shop found. Contact admin."},
        }

    # Full order history feeds the stats below; the LIVE feed shipped to the
    # app is capped to the most recent orders so the 30s auto-refresh never
    # drags the shop's entire history across the network (the payload grew
    # with every order and made the vendor app feel slow). Multi-shop
    # sub-orders are merged in so they appear too. One DB read, sliced twice.
    shop_orders = _shop_orders_merged(my_shop["id"])
    feed_orders = shop_orders[:250]
    pending = [o for o in shop_orders if o["status"] in ("Pending Payment", "Pending Acceptance")]
    active = [o for o in shop_orders if o["status"] in ("Confirmed", "Preparing", "Ready")]
    accepted = [o for o in shop_orders if o["status"] == "Accepted"]
    completed = [o for o in shop_orders if o["status"] == "Completed"]

    # Earnings count only real (paid/fulfilled) orders — exclude cancelled/failed
    earned_orders = [o for o in shop_orders if o["status"] not in ("Cancelled", "Failed")]
    revenue = sum(o["total"] for o in earned_orders)

    # 'Today' and the monthly share cycle are always Asia/Kolkata here — the
    # admin share monitor uses the same IST dates, so the vendor and admin
    # views can never disagree on which day/month a payment belongs to.
    today_key = datetime.now(_KOLKATA_TZ).strftime("%Y-%m-%d")
    today_orders = [o for o in earned_orders if _ist_date(o.get("created_at")) == today_key]
    today_revenue = sum(o["total"] for o in today_orders)

    # ─── Admin share: flat ₹10 per order ───
    # The share cycle is one calendar month (IST): on the 1st of each month
    # the counters reset automatically because they are computed from order
    # timestamps. The student is never charged a service fee; instead the
    # vendor pays the admin ₹10 for each order they earned this month.
    month_key = datetime.now(_KOLKATA_TZ).strftime("%Y-%m")
    month_orders = [o for o in earned_orders if _ist_date(o.get("created_at"))[:7] == month_key]
    month_revenue = sum(o["total"] for o in month_orders)
    platform_fee_due = len(month_orders) * 10
    net_earnings = max(0, revenue - platform_fee_due)
    today_fee_due = len(today_orders) * 10

    # Admin's UPI ID — the vendor's "Pay" button opens this to settle the share.
    payment_settings = {}
    try:
        payment_settings = db.get_payment_settings()
    except Exception as e:
        logger.warning(f"Could not load payment settings for vendor dashboard: {e}")
    admin_upi_id = (payment_settings.get("upi_id") or "").strip()
    admin_receiver_name = (payment_settings.get("receiver_name") or "DETOMSITE Admin").strip()

    # Share payment status for this month (does the admin already have the money?)
    share_paid_month = False
    latest_share_payment = None
    try:
        my_share_payments = db.list_share_payments_by_shop(my_shop["id"])
        for p in my_share_payments:
            # Normalize to the same Asia/Kolkata month the rest of the app uses
            # (Supabase stores created_at in UTC).
            created_month = _ist_date(p.get("created_at"))[:7]
            paid_month = _ist_date(p.get("paid_at"))[:7]
            if p.get("status") == "Completed" and (created_month == month_key or paid_month == month_key):
                share_paid_month = True
            if latest_share_payment is None:
                latest_share_payment = p
    except Exception as e:
        logger.warning(f"Could not load share payment status: {e}")

    return {
        "user": current_vendor,
        "shop": my_shop,
        "orders": feed_orders,
        "stats": {
            "total_orders": len(shop_orders),
            "pending_orders": len(pending),
            "active_orders": len(active),
            "accepted_orders": len(accepted),
            "completed_orders": len(completed),
            "revenue": revenue,
            "platform_fee_due": platform_fee_due,
            "net_earnings": net_earnings,
            "month_orders": len(month_orders),
            "month_revenue": month_revenue,
            "month_fee_due": platform_fee_due,
            "share_paid_month": share_paid_month,
            "today_orders": len(today_orders),
            "today_revenue": today_revenue,
            "today_fee_due": today_fee_due,
            # Backward-compatible alias so older vendor apps keep working.
            "share_paid_today": share_paid_month,
            "latest_share_payment": latest_share_payment,
            "admin_upi_id": admin_upi_id,
            "admin_receiver_name": admin_receiver_name,
            "approval_status": my_shop["approval_status"],
        },
    }


@router.patch("/shop")
def update_shop(data: ShopStatusUpdate, current_vendor: dict = Depends(get_current_vendor)):
    """Update shop status (present, open/closed, hours)."""
    my_shop = _my_shop(current_vendor)

    shop_id = my_shop["id"]
    updates = data.model_dump(exclude_unset=True)

    if my_shop["approval_status"] != "Approved" and "present" in updates:
        raise HTTPException(status_code=403, detail="Shop not approved yet. Cannot toggle availability.")

    updated = db.update_shop(shop_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Shop not found")
    return updated


@router.post("/dues/pay")
def pay_admin_dues(data: AdminDuesPayment, current_vendor: dict = Depends(get_current_vendor)):
    """Vendor pays their flat ₹10-per-order share to the admin.

    Opens a UPI payment to the admin (handled in the app UI). This endpoint
    records a Pending share payment that the admin marks as Received once the
    money lands in their bank account."""
    my_shop = _my_shop(current_vendor)
    shop_id = my_shop["id"]

    # Default to this month's ₹10-per-order share when no amount is supplied
    amount = data.amount
    if amount is None:
        shop_orders = [o for o in db.list_orders_by_shop(shop_id) if o["status"] not in ("Cancelled", "Failed")]
        # IST month, matching the vendor dashboard and the admin share monitor.
        month_key = datetime.now(_KOLKATA_TZ).strftime("%Y-%m")
        month_orders = [o for o in shop_orders if _ist_date(o.get("created_at"))[:7] == month_key]
        amount = len(month_orders) * 10

    payment = db.record_share_payment(shop_id, amount)
    if not payment:
        raise HTTPException(status_code=404, detail="Shop not found")
    return {
        "message": f"Share payment of ₹{amount} recorded — the admin will mark it received.",
        "payment": payment,
    }


@router.get("/orders")
def get_orders(current_vendor: dict = Depends(get_current_vendor)):
    """Get all orders for this vendor's shop (single + multi-shop sub-orders)."""
    my_shop = _find_shop(current_vendor)
    if not my_shop:
        return []
    orders = _shop_orders_merged(my_shop["id"])
    # Enrich each order with its payment record (method, status, UTR) so the
    # shop can verify the payment right from the order card. The screenshot
    # upload system was removed — UTR is the only proof the platform accepts.
    # Multi sub-orders pay on the PARENT order id, so resolve that one.
    for o in orders:
        pay_key = o.get("parent_order_id") if o.get("is_sub_order") else o["id"]
        payment = db.get_payment_by_order_id(pay_key)
        if payment:
            o["payment"] = {
                "id": payment.get("id"),
                "method": payment.get("method"),
                "status": payment.get("status"),
                "utr_number": payment.get("utr_number"),
                "amount": payment.get("amount"),
            }
    return orders


@router.get("/orders/lookup")
def lookup_order_by_code(code: str = Query(..., min_length=1, max_length=200), current_vendor: dict = Depends(get_current_vendor)):
    """Resolve an order from a scanned QR code or a manually typed order ID.

    The student app renders a QR whose payload is ``DETOMSITE-ORDER:<order id>``.
    Scanning it (or typing the code / order id manually in the scanner's manual
    fallback) returns the order — but only if it belongs to THIS vendor's shop,
    so scanning someone else's code never leaks data."""
    raw = code.strip()
    order_id = raw
    prefix = "DETOMSITE-ORDER:"
    if raw.upper().startswith(prefix):
        order_id = raw[len(prefix):].strip()

    order = db.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found. Check the code and try again.")

    my_shop = _find_shop(current_vendor)
    if not my_shop or order["shop_id"] != my_shop["id"]:
        raise HTTPException(status_code=403, detail="This order belongs to another shop.")

    return order


# Asia/Kolkata offset for correct per-day grouping (no tzdata dependency)
_KOLKATA_TZ = timezone(timedelta(hours=5, minutes=30))


def _ist_date(value: Any) -> str:
    """Normalize an order's created_at to an Asia/Kolkata date string (YYYY-MM-DD)."""
    try:
        text = str(value or "")
        if not text:
            return ""
        text = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_KOLKATA_TZ)
        return parsed.astimezone(_KOLKATA_TZ).strftime("%Y-%m-%d")
    except Exception:
        return str(value or "")[:10]


@router.get("/history")
def vendor_history(
    current_vendor: dict = Depends(get_current_vendor),
    from_date: str = Query("", alias="from"),
    to_date: str = Query("", alias="to"),
    range: str = Query("", description="today | yesterday | week — resolved in IST server-side"),
):
    """Orders + earnings for this vendor, filtered by date range.

    ``range=today|yesterday|week`` is resolved in Asia/Kolkata on the server
    so the filter always matches the dashboard's "today" (which also uses
    IST) — a phone/browser in a different timezone can no longer shift the
    day. ``from`` / ``to`` (YYYY-MM-DD, inclusive) are still supported for
    custom ranges. Also returns a per-day breakdown."""
    # Named ranges are authoritative — they override any client-computed dates.
    if range == "today":
        from_date = to_date = datetime.now(_KOLKATA_TZ).strftime("%Y-%m-%d")
    elif range == "yesterday":
        day = datetime.now(_KOLKATA_TZ) - timedelta(days=1)
        from_date = to_date = day.strftime("%Y-%m-%d")
    elif range == "week":
        to_date = datetime.now(_KOLKATA_TZ).strftime("%Y-%m-%d")
        from_date = (datetime.now(_KOLKATA_TZ) - timedelta(days=6)).strftime("%Y-%m-%d")

    my_shop = _find_shop(current_vendor)
    if not my_shop:
        return {"orders": [], "daily": [], "revenue": 0, "count": 0}

    shop_id = my_shop["id"]
    all_orders = db.list_orders_by_shop(shop_id)

    filtered = []
    for order in all_orders:
        day = _ist_date(order.get("created_at", ""))
        if from_date and day < from_date:
            continue
        if to_date and day > to_date:
            continue
        filtered.append({**order, "_day": day})

    # Per-day breakdown (earned orders exclude cancelled/failed)
    daily: dict[str, dict] = {}
    for order in filtered:
        if order["status"] in ("Cancelled", "Failed"):
            continue
        day = order["_day"]
        entry = daily.setdefault(day, {"date": day, "count": 0, "revenue": 0})
        entry["count"] += 1
        entry["revenue"] += int(order["total"])

    return {
        "orders": filtered,
        "daily": sorted(daily.values(), key=lambda d: d["date"], reverse=True),
        "revenue": sum(o["total"] for o in filtered if o["status"] not in ("Cancelled", "Failed")),
        "count": len([o for o in filtered if o["status"] not in ("Cancelled", "Failed")]),
        "from_date": from_date,
        "to_date": to_date,
    }


@router.patch("/orders/{order_id}/status")
def update_order_status(order_id: str, data: dict, current_vendor: dict = Depends(get_current_vendor)):
    """Update order status (accept, prepare, complete, cancel). Works for single
    orders AND multi-shop sub-orders."""
    new_status = data.get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail="Status is required")

    order = db.get_order(order_id)
    is_sub = False
    if not order:
        order = db.get_sub_order(order_id)
        is_sub = bool(order)

    my_shop = _find_shop(current_vendor)
    if not order or not my_shop or order["shop_id"] != my_shop["id"]:
        raise HTTPException(status_code=403, detail="You don't own this order")

    if is_sub:
        order = db.update_sub_order_status(order_id, new_status)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        # Keep the parent status in step with its last sub-order so the
        # student's OrderResult reflects the newest state.
        try:
            sub = db.get_sub_order(order_id)
            parent_id = (sub or {}).get("parent_order_id")
            if parent_id:
                db.update_parent_order_status(parent_id, new_status)
        except Exception as e:
            logger.warning(f"vendor update — parent status sync error: {e}")
        return order

    order = db.update_order_status(order_id, new_status)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.post("/orders/{order_id}/payment-received")
def confirm_payment_received(order_id: str, current_vendor: dict = Depends(get_current_vendor)):
    """Vendor confirms they received the UPI payment for an order.

    The money lands directly in the shop's UPI account, so the vendor is the
    one who can instantly confirm it — no admin verification needed.
    """
    order = db.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    my_shop = _find_shop(current_vendor)
    if not my_shop or order["shop_id"] != my_shop["id"]:
        raise HTTPException(status_code=403, detail="You don't own this order")

    if order["status"] != "Pending Payment":
        raise HTTPException(status_code=400, detail="Order is not awaiting payment confirmation")

    payment = db.get_payment_by_order_id(order_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment record not found")

    updated = db.update_payment_status(payment["id"], "Success")
    if not updated:
        raise HTTPException(status_code=400, detail="Could not confirm payment")
    # Payment received → the order is completed in one step (no prep/ready/done).
    order_after = db.update_order_status(order_id, "Completed")
    # Payment verified → auto-fire the shopkeeper's own WhatsApp notification
    # reminder (confirmation SMS → admin's number → shop) so the shop has an
    # auditable trail. Runs fire-and-forget on a daemon thread; never blocks
    # the confirm response (this is a sync endpoint in a thread-pool worker,
    # so there is no event loop to schedule a coroutine on).
    try:
        import threading
        threading.Thread(
            target=_notify_shop_whatsapp_verified,
            args=(order_after or order,),
            daemon=True,
        ).start()
    except Exception as e:
        logger.warning(f"WhatsApp notify after payment-confirm error: {e}")
    return {
        "message": "Payment received — order completed!",
        "payment": updated,
        "order": order_after or db.get_order(order_id),
    }


def _notify_shop_whatsapp_verified(order: dict | None) -> None:
    """Fire-and-forget (daemon thread): build the wa.me link for a
    payment-verified order and log it as a Pending WhatsApp notification for
    the admin centre. Sync on purpose — the vendor API is thread-pool based."""
    if not order:
        return
    try:
        from urllib.parse import quote
        from app.services.sms_service import compose_order_wa
        shop = db.get_shop(order.get("shop_id") or "")
        number = str((shop or {}).get("whatsapp_number") or "").strip() or str((shop or {}).get("phone") or "").strip()
        if not (shop and number):
            return
        digits = "".join(ch for ch in number if ch.isdigit())
        if len(digits) == 10:
            digits = "91" + digits
        url = f"https://wa.me/{digits}?text={quote(compose_order_wa(order))}"
        db.log_whatsapp(
            sub_order_id=order["id"], phone=number,
            message=compose_order_wa(order), url=url, status="Pending",
        )
    except Exception as e:
        logger.warning(f"WhatsApp verified-notify error for {order.get('id')}: {e}")


# ─── Product CRUD ───

class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    price: int = Field(..., ge=1)
    category: str = Field(..., max_length=50)
    inventory: int = 0
    prep_time: int = 10
    available: bool = True
    # Combo: ONE price for MANY items (Biryani + Fast Food + drink). When
    # is_combo is true the category is forced to "Combo" and combo_items holds
    # the item list text (one per line or comma-separated). Bounded so a vendor
    # can't store an unbounded blob that every student's menu then downloads.
    is_combo: bool = False
    combo_items: str = Field(default="", max_length=500)


class ProductUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price: int | None = None
    category: str | None = None
    inventory: int | None = None
    prep_time: int | None = None
    available: bool | None = None
    is_combo: bool | None = None
    combo_items: str | None = Field(default=None, max_length=500)


@router.get("/products")
def list_my_products(current_vendor: dict = Depends(get_current_vendor)):
    """List products for this vendor's shop."""
    my_shop = _find_shop(current_vendor)
    if not my_shop:
        return []
    return db.list_products(my_shop["id"])


@router.post("/products", status_code=201)
def create_product(data: ProductCreate, current_vendor: dict = Depends(get_current_vendor)):
    """Add a new product to this vendor's shop."""
    my_shop = _find_shop(current_vendor)

    if not my_shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    if my_shop["approval_status"] != "Approved":
        raise HTTPException(status_code=403, detail="Shop not approved. Cannot add products.")

    try:
        # A combo is ONE menu row holding MANY items at one price — the category
        # is forced so students always find every combo together under "Combo"
        # (the DB layer enforces the same rule, so no path can bypass it).
        is_combo = bool(data.is_combo)
        product = db.create_product({
            "shop_id": my_shop["id"],
            "name": data.name,
            "description": data.description,
            "price": data.price,
            "category": "Combo" if is_combo else data.category,
            "inventory": data.inventory,
            "prep_time": data.prep_time,
            "available": data.available,
            "is_combo": is_combo,
            "combo_items": data.combo_items if is_combo else "",
        })
    except Exception as e:
        # Full details go to the server log (Render) — the vendor only gets a
        # concise message. The store self-heals missing columns automatically,
        # so reaching here means the table is missing or truly broken.
        logger.error(
            f"Product creation failed for vendor {current_vendor['username']} "
            f"(shop {my_shop['id']}): {e}\n{traceback.format_exc()}"
        )
        raise HTTPException(
            status_code=400,
            detail="Could not add product. Please try again — if it keeps failing, contact the admin.",
        )
    if not product:
        raise HTTPException(status_code=400, detail="Could not add product — please try again.")

    # Notify admin of vendor product changes (never students)
    try:
        db.create_notification(
            title="New product added by vendor",
            message=f"{current_vendor['name']} added '{data.name}' (₹{data.price}) to {my_shop['name']}.",
            target_role="admin",
        )
    except Exception as e:
        logger.warning(f"Could not notify admin of product add: {e}")
    return product


@router.patch("/products/{product_id}")
def update_product(product_id: str, data: ProductUpdate, current_vendor: dict = Depends(get_current_vendor)):
    """Update a product in this vendor's shop."""
    product = db.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Verify this vendor owns the product's shop
    my_shop = _find_shop(current_vendor)
    if not my_shop or product["shop_id"] != my_shop["id"]:
        raise HTTPException(status_code=403, detail="You don't own this product")

    updates = data.model_dump(exclude_unset=True)
    updated = db.update_product(product_id, updates)
    # Notify admin of vendor product changes
    try:
        change_parts = [f"{k} → {v}" for k, v in updates.items() if k != "available"]
        change_desc = ", ".join(change_parts) if change_parts else "details"
        db.create_notification(
            title="Product updated by vendor",
            message=f"{current_vendor['name']} updated '{product['name']}' ({change_desc}).",
            target_role="admin",
        )
    except Exception as e:
        logger.warning(f"Could not notify admin of product update: {e}")
    return updated


@router.delete("/products/{product_id}")
def delete_product(product_id: str, current_vendor: dict = Depends(get_current_vendor)):
    """Delete a product (permanently removed from the menu)."""
    product = db.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    my_shop = _find_shop(current_vendor)
    if not my_shop or product["shop_id"] != my_shop["id"]:
        raise HTTPException(status_code=403, detail="You don't own this product")

    deleted = db.delete_product(product_id)
    if not deleted:
        raise HTTPException(status_code=400, detail="Could not delete product")
    # Notify admin of vendor product removal
    try:
        db.create_notification(
            title="Product removed by vendor",
            message=f"{current_vendor['name']} removed '{product['name']}' from the menu.",
            target_role="admin",
        )
    except Exception as e:
        logger.warning(f"Could not notify admin of product delete: {e}")
    return {"message": "Product removed", "product": product}


# ─── Web Push notifications (order alerts on the installed app) ───


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionCreate(BaseModel):
    endpoint: str = Field(..., min_length=10)
    keys: PushSubscriptionKeys


@router.get("/push/config")
def push_config(current_vendor: dict = Depends(get_current_vendor)):
    """Tell the vendor app whether web push is configured and hand it the
    public VAPID key needed to subscribe. When disabled, ``reason`` explains
    why so the app can show a helpful message instead of a dead button."""
    keys = push_service.get_vapid_keys()
    if keys:
        return {"enabled": True, "vapid_public_key": keys["public_key"], "reason": ""}
    return {
        "enabled": False,
        "vapid_public_key": "",
        "reason": "VAPID keys are not configured on the server yet.",
    }


@router.post("/push/subscribe")
def subscribe_push(
    data: PushSubscriptionCreate,
    current_vendor: dict = Depends(get_current_vendor),
):
    """Register this device's push subscription so the shop gets order alerts."""
    endpoint = data.endpoint.strip()
    if not endpoint.startswith("https://"):
        raise HTTPException(status_code=400, detail="Invalid push endpoint")
    my_shop = _my_shop(current_vendor)
    try:
        saved = db.save_push_subscription(
            shop_id=my_shop["id"],
            endpoint=endpoint,
            p256dh=data.keys.p256dh.strip(),
            auth=data.keys.auth.strip(),
        )
    except Exception as e:
        logger.error(f"Could not save push subscription for vendor {current_vendor['username']}: {e}")
        raise HTTPException(status_code=400, detail="Could not save the push subscription")
    if not saved:
        raise HTTPException(status_code=400, detail="Could not save the push subscription")
    return {"ok": True, "message": "Order notifications enabled 🔔", "subscription": saved}


@router.delete("/push/subscribe")
def unsubscribe_push(
    current_vendor: dict = Depends(get_current_vendor),
    endpoint: str = Query(..., min_length=10, description="The push subscription endpoint URL to remove"),
):
    """Remove this device's push subscription.

    The endpoint is passed as a query parameter on purpose — DELETE requests
    with a body are non-standard and can be stripped by proxies/CDNs."""
    my_shop = _my_shop(current_vendor)
    try:
        removed = db.remove_push_subscription(my_shop["id"], endpoint.strip())
    except Exception as e:
        logger.warning(f"Could not remove push subscription: {e}")
        removed = False
    return {"ok": removed, "message": "Order notifications disabled" if removed else "No subscription to remove"}


@router.post("/push/test")
def test_push(current_vendor: dict = Depends(get_current_vendor)):
    """Send a test push to THIS shop's own subscribed devices. Returns a
    human-readable result so the vendor can verify notifications work and
    see the real error if they don't."""
    my_shop = _my_shop(current_vendor)
    result = push_service.send_test_push(my_shop["id"])
    return result