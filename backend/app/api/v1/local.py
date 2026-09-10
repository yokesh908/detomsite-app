"""
Local runnable API routes backed by SQLite / Supabase.
"""
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
import asyncio

from app.core.config import settings
from app.core import local_mongo_db
from app.core.store import store as db
from app.core.user_store import persist_user_profile
from app.core.order_slots import (
    CANCELLABLE_STATUSES,
    KOLKATA_TZ,
    in_delivery_window,
    now_kolkata,
    slot_cutoff_for,
)
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token
from app.services import push_service
from typing import Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


async def _db(fn, *args, **kwargs):
    """Run a blocking store call in a worker thread.

    The SQLite/Supabase stores are synchronous (psycopg2/sqlite3). Calling them
    directly inside an ``async def`` handler stalls FastAPI's event loop and
    serializes every concurrent request — which is exactly the latency users
    feel in production. Running the call in a thread keeps the loop free.
    """
    return await asyncio.to_thread(fn, *args, **kwargs)


_last_auto_confirm_run = 0.0


def _process_due_auto_confirm():
    """Fire-and-forget 30-min auto-confirm sweep, throttled to once a minute.

    On hosts with a background loop (Render/local) this is redundant — the
    loop already runs it. On serverless hosts (Vercel) there is no background
    loop, so the lazy sweep triggered on the most-polled endpoint keeps the
    spec's auto-complete behaviour working. Never raises.
    """
    import time
    global _last_auto_confirm_run
    if settings.USE_LOCAL_DB or settings.USE_TURSO_DB or settings.USE_SUPABASE_DB:
        if time.monotonic() - _last_auto_confirm_run < 60:
            return
        _last_auto_confirm_run = time.monotonic()
        try:
            def _run():
                return db.auto_complete_expired_deliveries()
            asyncio.get_event_loop().run_in_executor(None, _run)
        except Exception:
            pass


def _use_mongo() -> bool:
    return not settings.USE_LOCAL_DB and not settings.USE_TURSO_DB and not settings.USE_SUPABASE_DB


def _normalize_phone(phone: str) -> str:
    """Coerce an Indian mobile number to E.164 (+91 + 10 digits).

    Handles every form a (possibly stale) frontend build can send: plain 10
    digits ("9876543210"), the E.164 form ("+919876543210"), or 12 digits with
    the country code ("919876543210"). Anything else is returned unchanged.
    """
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) == 10:
        return f"+91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+91{digits[2:]}"
    return phone or ""


@router.get("/status")
async def database_status():
    if _use_mongo():
        return {
            "connected": True,
            "mode": "mongo",
            "database": "MongoDB Atlas",
            "persistent": True,
            "message": "MongoDB is active for production data.",
        }
    if settings.USE_TURSO_DB:
        return {
            "connected": True,
            "mode": "turso",
            "database": "Turso/libSQL",
            "persistent": True,
            "message": "Turso is active. Business data is stored in a persistent cloud database.",
        }
    return {
        "connected": True,
        "mode": "demo",
        "database": "SQLite demo database",
        "persistent": False,
        "message": "Demo database is active. Data can reset after redeploy or server restart.",
    }


class LocalSessionCreate(BaseModel):
    email: EmailStr
    name: str
    role: str


class LocalShopUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    description: str | None = None
    opening_time: str | None = None
    closing_time: str | None = None
    present: bool | None = None
    status: str | None = None
    approval_status: str | None = None
    shopkeeper_email: str | None = None
    shopkeeper_name: str | None = None
    phone: str | None = None
    upi_id: str | None = None


class LocalShopCreate(BaseModel):
    name: str
    category: str
    description: str = ""
    shopkeeper_email: EmailStr
    shopkeeper_name: str
    phone: str
    opening_time: str = "09:00 AM"
    closing_time: str = "09:00 PM"
    upi_id: str = ""


class LocalProductCreate(BaseModel):
    shop_id: str
    name: str
    description: str = ""
    price: int
    category: str
    inventory: int = 0
    prep_time: int = 10
    available: bool = True


class LocalProductUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price: int | None = None
    pending_price: int | None = None
    category: str | None = None
    inventory: int | None = None
    prep_time: int | None = None
    available: bool | None = None


class LocalOrderStatusUpdate(BaseModel):
    status: str


class LocalOrderItem(BaseModel):
    product_id: str
    quantity: int


class LocalOrderCreate(BaseModel):
    shop_id: str
    items: list[LocalOrderItem]
    student_name: str = "Student"
    student_phone: str = ""
    delivery_location: str
    delivery_slot: str
    pending_payment: bool = False
    payment_method: str = "UPI"  # 'UPI' | 'COD' | 'Razorpay'


class LocalMultiShopOrder(BaseModel):
    """Multi-shop checkout payload: one list of shops, each with items."""
    shops: list[dict]
    student_name: str = "Student"
    student_phone: str = ""
    student_email: str = ""
    delivery_location: str
    delivery_slot: str = ""
    payment_method: str = "UTR"  # 'UTR' | 'COD'


class LocalSubOrderStatusUpdate(BaseModel):
    status: str
    notes: str = ""


class LocalComplaintCreate(BaseModel):
    parent_order_id: str
    shop_id: str = ""
    shop_name: str = ""
    subject: str
    message: str
    proof_url: str = ""


class LocalRefundCreate(BaseModel):
    parent_order_id: str
    sub_order_id: str = ""
    original_amount: int = 0
    refund_amount: int = 0
    refund_type: str = "Full"


class LocalAnnouncementCreate(BaseModel):
    shop_id: str
    message: str


class LocalAnnouncementToggle(BaseModel):
    is_active: int = 1


class LocalMenuChangeCreate(BaseModel):
    shop_id: str
    product_id: str = ""
    change_type: str
    old_value: str = ""
    new_value: str = ""


class LocalComplaintStatusUpdate(BaseModel):
    status: str
    admin_notes: str = ""


class LocalRefundUpdate(BaseModel):
    status: str
    refund_utr: str = ""
    admin_notes: str = ""


class LocalMenuChangeApprove(BaseModel):
    status: str
    admin_notes: str = ""


class LocalPaymentCreate(BaseModel):
    order_id: str
    amount: int
    method: str
    utr_number: str | None = None
    screenshot_name: str | None = None


class LocalPaymentStatusUpdate(BaseModel):
    status: str


class LocalPaymentSettings(BaseModel):
    manual_enabled: bool | None = None
    upi_id: str | None = None
    receiver_name: str | None = None
    instructions: str | None = None
    razorpay_enabled: bool | None = None


class LocalTicketCreate(BaseModel):
    name: str
    email: EmailStr
    phone_number: str
    category: str
    title: str
    description: str


class LocalFeedbackCreate(BaseModel):
    """A student's bug report / improvement contribution while testing the site."""
    category: str = Field(..., pattern="^(Bug|Improvement|Suggestion|Other)$")
    subject: str = Field(..., min_length=3, max_length=150)
    message: str = Field(..., min_length=5, max_length=2000)
    page: str = Field(default="", max_length=200)
    # Where the contribution came from: 'User' (student portal, default) or
    # 'ATS' (automated test suite). The admin Feedback page filters on this so
    # real user reports and test-generated ones are easy to tell apart.
    source: str = Field(default="User", pattern="^(User|ATS)$")
    # Fallback identity for quick/session logins that have no JWT (kept in sync
    # with the server-side user record whenever a token IS present).
    name: str = Field(default="", max_length=100)
    email: str = Field(default="", max_length=200)


# ─── Auth schemas ───


class LocalAuthRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=4, max_length=128)
    name: str = Field(..., min_length=1, max_length=100)
    role: str = Field(..., pattern="^(student|shopkeeper|admin)$")
    email: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=30)


class LocalAuthLogin(BaseModel):
    username: str
    password: str


class LocalAuthUser(BaseModel):
    id: int
    username: str
    name: str
    role: str
    created_at: datetime


class LocalAuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: LocalAuthUser


# ─── Helper to extract current user from JWT ───


async def get_current_local_user(authorization: Optional[str] = Header(None)) -> dict:
    """Get current user from JWT token in Authorization header."""
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
    user = await _db(db.get_user_by_id, int(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ─── Auth endpoints ───


@router.post("/auth/register", status_code=201)
async def local_register(data: LocalAuthRegister):
    """Register a new user in the local database."""
    if _use_mongo():
        raise HTTPException(status_code=501, detail="Use the /auth/register endpoint for Mongo mode")

    password_hash_value = await asyncio.to_thread(hash_password, data.password)
    user, conflict = await _db(
        db.register_user,
        username=data.username,
        password_hash=password_hash_value,
        name=data.name,
        role=data.role,
        email=data.email,
        phone=data.phone,
    )
    if conflict == "username" or not user:
        raise HTTPException(status_code=409, detail="Username already taken")
    if conflict == "email":
        # One email = one account across the whole platform, no matter the role.
        raise HTTPException(status_code=409, detail="This email is already registered. Try signing in instead.")

    # If registering as shopkeeper, auto-create a pending shop
    if data.role == "shopkeeper":
        try:
            await _db(db.create_shop, {
                "name": f"{data.name}'s Shop",
                "category": "Campus Food",
                "description": "New shop awaiting admin approval.",
                "shopkeeper_email": data.email or f"{data.username}@campus.local",
                "shopkeeper_name": data.name,
                "phone": data.phone or "9999999999",
                "opening_time": "09:00 AM",
                "closing_time": "09:00 PM",
            })
            logger.info(f"Shop auto-created for shopkeeper: {data.username}")
        except Exception as e:
            logger.warning(f"Could not auto-create shop for {data.username}: {e}")

    return {"message": "User registered successfully", "user": user}


@router.post("/auth/login")
async def local_login(data: LocalAuthLogin):
    """Authenticate user and return JWT tokens."""
    if _use_mongo():
        raise HTTPException(status_code=501, detail="Use the /auth/login endpoint for Mongo mode")

    user = await _db(db.get_user_by_username, data.username)
    if not user:
        raise HTTPException(status_code=401, detail="No account found with this username. Check the spelling or register first.")

    if not await asyncio.to_thread(verify_password, data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect password. Please try again.")

    # Generate JWT tokens
    token_data = {
        "sub": str(user["id"]),
        "username": user["username"],
        "name": user["name"],
        "role": user["role"],
    }
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return LocalAuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=LocalAuthUser(
            id=user["id"],
            username=user["username"],
            name=user["name"],
            role=user["role"],
            created_at=user["created_at"],
        ),
    )


@router.get("/auth/me")
async def local_me(current_user: dict = Depends(get_current_local_user)):
    """Get the current authenticated user's profile."""
    return current_user


@router.get("/summary")
async def summary():
    if _use_mongo():
        return await local_mongo_db.get_summary()
    return await _db(db.get_summary)


@router.post("/sessions")
async def create_session(data: LocalSessionCreate):
    if _use_mongo():
        return await local_mongo_db.save_session(data.email, data.name, data.role)
    return await _db(persist_user_profile, data.email, data.name, data.role)


@router.get("/shops")
async def shops(public_only: bool = False):
    if _use_mongo():
        return await local_mongo_db.list_shops()
    return await _db(db.list_shops, public_only=public_only)


@router.post("/shops")
async def create_shop(data: LocalShopCreate):
    if _use_mongo():
        raise HTTPException(status_code=501, detail="Shop registration is not available for Mongo mode")
    return await _db(db.create_shop, data.model_dump())


@router.patch("/shops/{shop_id}")
async def patch_shop(shop_id: str, data: LocalShopUpdate):
    if _use_mongo():
        shop = await local_mongo_db.update_shop(shop_id, data.model_dump(exclude_unset=True))
    else:
        shop = await _db(db.update_shop, shop_id, data.model_dump(exclude_unset=True))
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    return shop


@router.get("/shops/{shop_id}")
async def shop(shop_id: str):
    result = await local_mongo_db.get_shop(shop_id) if _use_mongo() else await _db(db.get_shop, shop_id)
    if not result:
        raise HTTPException(status_code=404, detail="Shop not found")
    return result


@router.get("/products")
async def products(shop_id: str | None = None):
    if _use_mongo():
        return await local_mongo_db.list_products(shop_id)
    return await _db(db.list_products, shop_id)


@router.post("/products")
async def add_product(data: LocalProductCreate):
    if _use_mongo():
        return await local_mongo_db.create_product(data.model_dump())
    return await _db(db.create_product, data.model_dump())


@router.patch("/products/{product_id}")
async def patch_product(product_id: str, data: LocalProductUpdate):
    if _use_mongo():
        product = await local_mongo_db.update_product(product_id, data.model_dump(exclude_unset=True))
    else:
        product = await _db(db.update_product, product_id, data.model_dump(exclude_unset=True))
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.get("/orders")
async def orders():
    if _use_mongo():
        return await local_mongo_db.list_orders()
    return await _db(db.list_orders)


@router.get("/orders/{order_id}")
async def order(order_id: str):
    result = await local_mongo_db.get_order(order_id) if _use_mongo() else await _db(db.get_order, order_id)
    if not result:
        raise HTTPException(status_code=404, detail="Order not found")
    return result


@router.post("/orders")
async def add_order(data: LocalOrderCreate):
    payload = data.model_dump()
    # The student's mobile is always stored as E.164 (+91 + 10 digits) so the
    # shopkeeper/order views never see a bare 10-digit number.
    payload["student_phone"] = _normalize_phone(payload.get("student_phone", ""))
    if not _use_mongo():
        # Give the student a precise, human-readable reason instead of the old
        # cryptic "not approved, present, open, or orderable" message — the
        # usual cause is the vendor having NOT pressed Start yet, even though
        # the admin has approved the shop.
        shop = await _db(db.get_shop, payload["shop_id"])
        if not shop:
            raise HTTPException(status_code=400, detail="We couldn't find that shop — it may have been removed by the admin.")
        if shop.get("approval_status") != "Approved":
            if str(shop.get("approval_status") or "").lower() in ("removed", "suspended"):
                raise HTTPException(status_code=400, detail="This shop is no longer available — it was removed by the admin.")
            raise HTTPException(status_code=400, detail="This shop is not approved yet — wait until an admin approves it, then try again.")
        if not shop.get("present") or shop.get("status") != "Open":
            raise HTTPException(status_code=400, detail="This shop is currently closed — the vendor hasn't started accepting orders right now. Please try again a little later.")
        # The vendor controls which payment methods the shop accepts (UPI / COD
        # toggles in their Settings) — reject orders using a disabled method.
        method = str(payload.get("payment_method") or "").strip()
        if method == "UPI" and not shop.get("upi_enabled", 1):
            raise HTTPException(status_code=400, detail="This shop has turned off UPI payments — please choose Cash on Delivery instead.")
        if method == "COD" and not shop.get("cod_enabled", 1):
            raise HTTPException(status_code=400, detail="This shop has turned off Cash on Delivery — please pay via UPI instead.")
    order = await local_mongo_db.create_order(payload) if _use_mongo() else await _db(db.create_order, payload)
    if not order:
        # The store can still reject if every cart item was deleted or the shop
        # toggled closed between the check above and the insert.
        raise HTTPException(status_code=400, detail="Could not place your order — the shop stopped accepting orders or an item in your cart was removed. Please check and try again.")

    # Auto-accept: orders placed inside a delivery window (before 12:30 PM or
    # before 6:00 PM) are accepted automatically — the vendor no longer taps
    # Accept for every order. Orders outside the windows stay pending so the
    # vendor can still handle them manually.
    try:
        if in_delivery_window() and order.get("status") == "Pending Acceptance":
            if _use_mongo():
                accepted = await local_mongo_db.update_order_status(order["id"], "Accepted")
            else:
                accepted = await _db(db.update_order_status, order["id"], "Accepted")
            if accepted:
                order = accepted
    except Exception as e:
        logger.warning(f"Could not auto-accept order {order.get('id')}: {e}")

    # Fire the vendor's phone notification without blocking the student's
    # response — the web push runs in a worker thread (fire-and-forget).
    if not _use_mongo():
        try:
            asyncio.get_running_loop().create_task(
                push_service.notify_shop_new_order_async(order)
            )
        except Exception as e:
            logger.warning(f"Could not schedule order push notification: {e}")

    return order


@router.patch("/orders/{order_id}/status")
async def patch_order_status(order_id: str, data: LocalOrderStatusUpdate):
    if _use_mongo():
        order = await local_mongo_db.update_order_status(order_id, data.status)
    else:
        order = await _db(db.update_order_status, order_id, data.status)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.post("/orders/{order_id}/cancel")
async def cancel_own_order(order_id: str, current_user: dict = Depends(get_current_local_user)):
    """Let a student cancel their own order within its delivery window.

    Orders placed inside a delivery window (morning → 12:30 PM, afternoon →
    6:00 PM) are auto-accepted; the student can cancel them until the window
    closes. Once the window closes or the order is completed, cancellation
    is locked.
    """
    order = await _db(db.get_order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Ownership check — the student portal identifies a student's orders by
    # their name (the same rule the app uses to filter "My Orders"); the
    # phone number is a secondary match when names disagree.
    user_name = str(current_user.get("name") or "").strip().lower()
    order_name = str(order.get("student_name") or "").strip().lower()
    user_phone = "".join(ch for ch in str(current_user.get("phone") or "") if ch.isdigit())
    order_phone = "".join(ch for ch in str(order.get("student_phone") or "") if ch.isdigit())
    owns = (bool(user_name) and user_name == order_name) or (
        bool(user_phone) and bool(order_phone) and user_phone[-10:] == order_phone[-10:]
    )
    if not owns:
        raise HTTPException(status_code=403, detail="You can only cancel your own orders")

    # The day is split into two delivery windows (morning → 12:30 PM,
    # afternoon → 6:00 PM). Orders placed inside a window are auto-accepted;
    # the student can still cancel them until that window closes. Orders
    # outside the windows (after 6:00 PM) and terminal orders are locked.
    if order["status"] not in CANCELLABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="This order can no longer be cancelled.",
        )
    cutoff = slot_cutoff_for(order.get("created_at"))
    if cutoff is None:
        raise HTTPException(
            status_code=400,
            detail="This order was placed outside the delivery windows and can no longer be cancelled.",
        )
    if now_kolkata().time() >= cutoff:
        raise HTTPException(
            status_code=400,
            detail="The cancellation window for this order has closed.",
        )

    if _use_mongo():
        updated = await local_mongo_db.update_order_status(order_id, "Cancelled")
    else:
        updated = await _db(db.update_order_status, order_id, "Cancelled")

    # Close out any open payment intent (UPI orders create a 'Pending' payment
    # record at checkout) so the admin's payments table never shows a live
    # payment on a cancelled order. Status 'Cancelled' has no side effects on
    # the order itself (unlike 'Failed').
    if not _use_mongo():
        try:
            payment = await _db(db.get_payment_by_order_id, order_id)
            if payment and payment.get("status") == "Pending":
                await _db(db.update_payment_status, payment["id"], "Cancelled")
        except Exception as e:
            logger.warning(f"Could not mark payment cancelled for order {order_id}: {e}")

    return {
        "message": "Order cancelled — you can place a new order anytime.",
        "order": updated or await _db(db.get_order, order_id),
    }


@router.get("/payments")
async def payments():
    if _use_mongo():
        return await local_mongo_db.list_payments()
    return await _db(db.list_payments)


@router.post("/payments")
async def add_payment(data: LocalPaymentCreate):
    if not _use_mongo():
        if data.method == "Manual UTR":
            # Resolve the UPI target: the shop's own UPI ID first, then the
            # global (admin) UPI ID as a fallback. Money goes to the shop.
            order = await _db(db.get_order, data.order_id)
            shop = await _db(db.get_shop, order["shop_id"]) if order else None
            shop_upi = (shop or {}).get("upi_id", "") or ""
            payment_settings = await _db(db.get_payment_settings)
            # Shop's own UPI is the primary target; the global (admin) UPI is
            # only a fallback for shops that haven't added one yet.
            if not shop_upi and (not payment_settings["manual_enabled"] or not payment_settings["upi_id"]):
                raise HTTPException(status_code=400, detail="No UPI payment configured for this shop")
            # Respect the vendor's UPI toggle — a shop that turned UPI off must
            # not receive manual UTR payments either.
            if shop is not None and not shop.get("upi_enabled", 1):
                raise HTTPException(status_code=400, detail="This shop has turned off UPI payments.")
        # Razorpay method is validated in the create-razorpay-order endpoint

    if _use_mongo():
        payment = await local_mongo_db.create_payment(
            data.order_id,
            data.amount,
            data.method,
            data.utr_number,
            data.screenshot_name,
        )
    else:
        payment = await _db(
            db.create_payment,
            data.order_id,
            data.amount,
            data.method,
            data.utr_number,
            data.screenshot_name,
        )
    if not payment:
        raise HTTPException(status_code=400, detail="Unable to create payment")
    return payment


# ─── Razorpay endpoints ───


class LocalRazorpayOrderCreate(BaseModel):
    amount: int  # in paise (₹1 = 100 paise)
    currency: str = "INR"
    order_id: str  # Local order ID to associate payment with


class LocalRazorpayVerify(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    order_id: str  # Local order ID


@router.post("/payments/create-razorpay-order")
async def create_razorpay_order(data: LocalRazorpayOrderCreate):
    """Create a Razorpay order for payment."""
    if _use_mongo():
        raise HTTPException(status_code=501, detail="Use the /payments endpoints for Mongo mode")

    payment_settings = await _db(db.get_payment_settings)
    if not payment_settings.get("razorpay_enabled"):
        raise HTTPException(status_code=400, detail="Razorpay is not enabled by admin")

    key_id = settings.RAZORPAY_KEY_ID
    key_secret = settings.RAZORPAY_KEY_SECRET
    if not key_id or not key_secret:
        raise HTTPException(status_code=500, detail="Razorpay API keys not configured on server")

    try:
        import razorpay
        client = razorpay.Client(auth=(key_id, key_secret))

        # Create Razorpay order (network call — off the event loop)
        razorpay_order = await asyncio.to_thread(
            client.order.create,
            {
                "amount": data.amount,
                "currency": data.currency,
                "receipt": data.order_id,
                "payment_capture": 1,  # Auto-capture
            },
        )

        return {
            "razorpay_order_id": razorpay_order["id"],
            "amount": razorpay_order["amount"],
            "currency": razorpay_order["currency"],
            "key_id": key_id,
            "order_id": data.order_id,
        }
    except Exception as e:
        logger.error(f"Error creating Razorpay order: {e}")
        raise HTTPException(status_code=400, detail=f"Could not create payment: {str(e)}")


@router.post("/payments/verify-razorpay")
async def verify_razorpay_payment(data: LocalRazorpayVerify):
    """Verify Razorpay payment signature and update order."""
    if _use_mongo():
        raise HTTPException(status_code=501, detail="Use the /payments endpoints for Mongo mode")

    key_secret = settings.RAZORPAY_KEY_SECRET
    if not key_secret:
        raise HTTPException(status_code=500, detail="Razorpay secret not configured")

    try:
        import razorpay
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, key_secret))

        # Verify signature
        params_dict = {
            "razorpay_order_id": data.razorpay_order_id,
            "razorpay_payment_id": data.razorpay_payment_id,
            "razorpay_signature": data.razorpay_signature,
        }
        await asyncio.to_thread(client.utility.verify_payment_signature, params_dict)

        # Fetch payment details to get amount (network call — off the event loop)
        payment_info = await asyncio.to_thread(client.payment.fetch, data.razorpay_payment_id)
        amount_paise = payment_info.get("amount", 0)
        amount_rupees = amount_paise // 100

        # Create payment record in local DB
        payment = await _db(
            db.create_payment,
            order_id=data.order_id,
            amount=amount_rupees,
            method="Razorpay",
            utr_number=data.razorpay_payment_id,
            screenshot_name=None,
        )
        if not payment:
            raise HTTPException(status_code=400, detail="Could not save payment record")

        # Update order status to Pending Acceptance
        await _db(db.update_order_status, data.order_id, "Pending Acceptance")

        return {
            "message": "Payment verified successfully",
            "payment": payment,
        }
    except Exception as e:
        logger.error(f"Error verifying Razorpay payment: {e}")
        raise HTTPException(status_code=400, detail=f"Payment verification failed: {str(e)}")


@router.get("/payment-settings")
async def payment_settings():
    if _use_mongo():
        return {
            "manual_enabled": False,
            "upi_id": "",
            "receiver_name": "",
            "instructions": "",
            "razorpay_enabled": False,
        }
    return await _db(db.get_payment_settings)


@router.patch("/payment-settings")
async def patch_payment_settings(data: LocalPaymentSettings, authorization: Optional[str] = Header(None)):
    """Update payment settings. Only an authenticated admin may change them."""
    payload = None
    if authorization and authorization.lower().startswith("bearer "):
        payload = decode_token(authorization.split(" ", 1)[1].strip())
    if not payload or payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    if _use_mongo():
        raise HTTPException(status_code=501, detail="Payment settings are not available for Mongo mode")
    return await _db(db.update_payment_settings, data.model_dump(exclude_unset=True))


@router.patch("/payments/{payment_id}/status")
async def patch_payment_status(payment_id: str, data: LocalPaymentStatusUpdate):
    if _use_mongo():
        payment = await local_mongo_db.update_payment_status(payment_id, data.status)
    else:
        payment = await _db(db.update_payment_status, payment_id, data.status)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


@router.get("/tickets")
async def tickets():
    if _use_mongo():
        return await local_mongo_db.list_tickets()
    return await _db(db.list_tickets)


@router.post("/tickets")
async def add_ticket(data: LocalTicketCreate):
    if _use_mongo():
        return await local_mongo_db.create_ticket(data.model_dump())
    return await _db(db.create_ticket, data.model_dump())


@router.get("/notifications")
async def notifications(role: str | None = None):
    """List notifications, optionally filtered to a target role
    (e.g. ?role=student so vendor/admin alerts never reach students)."""
    if _use_mongo():
        return await local_mongo_db.list_notifications()
    return await _db(db.list_notifications, role=role)


# ─── Site feedback / bug reports (students → admin Feedback page) ───


def _resolve_feedback_user(authorization: Optional[str]):
    """Resolve the current user from the JWT when present (student portal
    logins issue a token; quick RoleGate sessions may not). Returns the user
    dict or None — feedback is never blocked for a missing identity."""
    payload = None
    if authorization and authorization.lower().startswith("bearer "):
        payload = decode_token(authorization.split(" ", 1)[1].strip())
    if not payload or not payload.get("sub"):
        return None
    user = db.get_user_by_id(int(payload["sub"]))
    return user


@router.post("/feedback")
async def add_feedback(data: LocalFeedbackCreate, authorization: Optional[str] = Header(None)):
    """Submit a bug report / improvement contribution while testing the site.
    Lands on the admin Feedback page (and in the admin notification bell).
    Identity is taken from the JWT when available, else from the client session."""
    values = data.model_dump()
    user = await _db(_resolve_feedback_user, authorization)
    if user:
        values["user_id"] = user["id"]
        values["username"] = user["username"]
        values["name"] = user["name"] or values.get("name", "")
        values["email"] = user["email"] or values.get("email", "")
    feedback = await _db(db.create_site_feedback, values)
    if not feedback:
        raise HTTPException(status_code=400, detail="Could not submit feedback. Please try again.")
    logger.info(f"Site feedback submitted by {values.get('name') or values.get('email') or 'guest'}: {values.get('subject')}")
    return feedback


@router.get("/feedback/mine")
async def my_feedback(authorization: Optional[str] = Header(None)):
    """A logged-in student's own contributions (status shown on their page)."""
    user = await _db(_resolve_feedback_user, authorization)
    if not user:
        return []
    return await _db(db.list_site_feedback_by_user, user["id"])


# ──────────────────────────────────────────────────────────────────
#  Multi-shop ordering (combo offer)
#  One parent order → per-shop sub-orders → ONE payment, ONE token.
# ──────────────────────────────────────────────────────────────────


@router.get("/batch")
async def current_batch():
    """Which delivery batch is accepting orders right now + stock info."""
    _process_due_auto_confirm()
    batch_type = db.get_current_batch()
    return {
        "batch_type": batch_type,
        "token_starts_at": 18,
        "next_token": db.get_next_token(),
        "date_key": db._day_key(),
        "accepted_until": "12:30" if batch_type == "Afternoon" else "18:00",
        "delivery_window": "13:00-13:30" if batch_type == "Afternoon" else "19:30-19:45",
    }


@router.get("/products/stock")
async def products_with_stock():
    """Every product with its per-batch remaining stock."""
    batch_type = db.get_current_batch()
    products = await _db(db.list_products)
    date_key = db._day_key()
    for p in products:
        p["batch_type"] = batch_type
        p["stock_left"] = db.get_product_stock(p["id"], batch_type, date_key)
    return products


@router.post("/orders/multi")
async def create_multi_shop_order(data: LocalMultiShopOrder):
    """Place a multi-shop order (combo). Creates one parent order + per-shop
    sub-orders sharing a single token. The student pays ONE bill."""
    if not data.shops:
        raise HTTPException(status_code=400, detail="No shops selected.")
    payload = data.model_dump()
    payload["student_phone"] = _normalize_phone(payload.get("student_phone", ""))

    # Pre-validate each shop for clear error messages.
    for group in payload["shops"]:
        shop = await _db(db.get_shop, group["shop_id"])
        if not shop:
            raise HTTPException(status_code=400, detail="One of the shops could not be found.")
        if shop.get("approval_status") != "Approved":
            raise HTTPException(status_code=400, detail=f"{shop['name']} is not approved yet.")
        if not shop.get("present") or shop.get("status") != "Open":
            raise HTTPException(status_code=400, detail=f"{shop['name']} is currently closed.")

    try:
        parent = await _db(
            db.create_parent_order,
            student_name=payload["student_name"] or "Student",
            student_phone=payload["student_phone"] or "",
            delivery_location=payload["delivery_location"],
            payment_method=payload["payment_method"],
            shops=payload["shops"],
            student_email=payload.get("student_email", ""),
            student_id=payload.get("student_id", ""),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not parent:
        raise HTTPException(status_code=400, detail="Could not place your order — a shop stopped accepting orders or an item was removed.")
    for sub in parent.get("sub_orders", []):
        try:
            asyncio.get_running_loop().create_task(
                push_service.notify_shop_new_order_async(
                    {
                        "id": sub["id"],
                        "token": sub["token"],
                        "shop_id": sub["shop_id"],
                        "shop_name": sub["shop_name"],
                        "items": sub["items_summary"],
                        "total": sub["subtotal"],
                        "student_name": parent.get("student_name", ""),
                        "student_phone": parent.get("student_phone", ""),
                        "delivery_location": parent.get("delivery_location", ""),
                    }
                )
            )
        except Exception as e:
            logger.warning(f"Could not schedule sub-order push for {sub['id']}: {e}")

    return parent


@router.get("/orders/parent")
async def parent_orders(status: str | None = None):
    """List parent (multi-shop) orders. Student portal uses this for My Orders."""
    return await _db(db.list_parent_orders, status=status)


@router.get("/orders/parent/{parent_order_id}")
async def parent_order(parent_order_id: str):
    result = await _db(db.get_parent_order, parent_order_id)
    if not result:
        raise HTTPException(status_code=404, detail="Order not found")
    return result


@router.get("/shop-orders/{shop_id}")
async def shop_sub_orders(shop_id: str, status: str | None = None):
    """A shop's own sub-orders (only THIS shop's items, never other shops')."""
    return await _db(db.get_shop_sub_orders, shop_id, status)


@router.patch("/shop-orders/{sub_order_id}/status")
async def patch_sub_order_status(sub_order_id: str, data: LocalSubOrderStatusUpdate):
    updated = await _db(db.update_sub_order_status, sub_order_id, data.status, data.notes)
    if not updated:
        raise HTTPException(status_code=404, detail="Sub-order not found")
    return updated


@router.get("/announcements")
async def announcements(shop_id: str | None = None, active_only: bool = True):
    """Shop announcement bar items shown to students on the shop page."""
    return await _db(db.list_shop_announcements, shop_id, active_only)


@router.post("/announcements")
async def add_announcement(data: LocalAnnouncementCreate):
    ann = await _db(db.create_shop_announcement, data.shop_id, data.message)
    if not ann:
        raise HTTPException(status_code=400, detail="Could not post announcement.")
    return ann


@router.patch("/announcements/{ann_id}")
async def patch_announcement(ann_id: str, data: LocalAnnouncementToggle):
    ann = await _db(db.toggle_shop_announcement, ann_id, bool(data.is_active))
    if not ann:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return ann


# ─── Complaints (student → admin review) ───


@router.get("/complaints")
async def complaints(status: str | None = None):
    return await _db(db.list_complaints, status)


@router.post("/complaints")
async def add_complaint(data: LocalComplaintCreate):
    complaint = await _db(
        db.create_complaint,
        parent_order_id=data.parent_order_id,
        student_name=data.student_name,
        student_phone=data.student_phone,
        shop_id=data.shop_id,
        shop_name=data.shop_name,
        subject=data.subject,
        message=data.message,
    )
    if not complaint:
        raise HTTPException(status_code=400, detail="Could not submit complaint.")
    return complaint


@router.patch("/complaints/{complaint_id}")
async def patch_complaint(complaint_id: str, data: LocalComplaintStatusUpdate):
    updated = await _db(db.update_complaint, complaint_id, data.status, data.admin_notes)
    if not updated:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return updated


# ─── Refunds (admin → student back) ───


@router.get("/refunds")
async def refunds(status: str | None = None):
    return await _db(db.list_refunds, status)


@router.post("/refunds")
async def add_refund(data: LocalRefundCreate):
    refund = await _db(
        db.create_refund,
        parent_order_id=data.parent_order_id,
        sub_order_id=data.sub_order_id,
        student_name=data.student_name,
        shop_name=data.shop_name,
        original_amount=data.original_amount,
        refund_amount=data.refund_amount,
        refund_type=data.refund_type,
    )
    if not refund:
        raise HTTPException(status_code=400, detail="Could not create refund.")
    return refund


@router.patch("/refunds/{refund_id}")
async def patch_refund(refund_id: str, data: LocalRefundUpdate):
    updated = await _db(db.update_refund, refund_id, data.status, data.refund_utr, data.admin_notes)
    if not updated:
        raise HTTPException(status_code=404, detail="Refund not found")
    return updated


class LocalRefundUpdate(BaseModel):
    status: str
    refund_utr: str = ""
    admin_notes: str = ""


# ─── Settlements (admin, 9:00 PM daily) ───


@router.get("/settlements")
async def settlements(status: str | None = None):
    return await _db(db.list_settlements, status)


@router.post("/settlements/run")
async def run_settlements():
    """Trigger today's settlement run (admin or nightly job)."""
    rows = await _db(db.run_daily_settlements)
    return {"message": f"Settlement computed for {len(rows)} shops.", "settlements": rows}


# ─── Menu change requests (shop → admin approval) ───


@router.get("/menu-change-requests")
async def menu_change_requests(status: str | None = None):
    return await _db(db.list_menu_change_requests, status)


@router.post("/menu-change-requests")
async def add_menu_change_request(data: LocalMenuChangeCreate):
    req = await _db(
        db.create_menu_change_request,
        shop_id=data.shop_id,
        product_id=data.product_id,
        change_type=data.change_type,
        old_value=data.old_value,
        new_value=data.new_value,
    )
    if not req:
        raise HTTPException(status_code=400, detail="Could not create menu change request.")
    return req


@router.patch("/menu-change-requests/{req_id}")
async def patch_menu_change_request(req_id: str, data: LocalMenuChangeApprove):
    req = await _db(db.update_menu_change_request, req_id, data.status, data.admin_notes)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    return req


class LocalMenuChangeApprove(BaseModel):
    status: str
    admin_notes: str = ""


# ─── Misc ───


@router.get("/audit-logs")
async def audit_logs(limit: int = 200):
    return await _db(db.list_audit_logs, limit)


@router.get("/whatsapp-logs")
async def whatsapp_logs(limit: int = 100):
    return await _db(db.list_whatsapp_logs, limit)
