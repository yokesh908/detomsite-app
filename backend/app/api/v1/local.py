"""
API routes backed by Supabase Postgres (the only database).
"""
from fastapi import APIRouter, HTTPException, Depends, Header, Request
from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import datetime
import asyncio
import re
import secrets

from app.core.config import settings
from app.core import read_cache
from app.core.rate_limit import allow as rate_allow, reset as rate_reset, client_ip as rate_ip
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
from app.services import sms_service
from typing import Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Highest number of units of a single dish a student may put on one order line.
# The cart UI caps itself well below this; the server-side bound exists so a
# hand-crafted request can't inflate a bill/stock row to an absurd value.
MAX_LINE_QUANTITY = 99

# Payment verification is UTR-ONLY: the student pastes the UPI transaction
# reference (a string stored in the database) and the shop's bank credit SMS
# carrying the same UTR auto-confirms the order. The old screenshot-upload
# system was removed — files written to a serverless /tmp directory vanished
# between invocations (which is why payments "didn't save"), and a UTR is the
# stronger proof anyway.



def _clean_payment_method(value: str, allowed: tuple[str, ...]) -> str:
    """Normalise a client-supplied payment method and reject unknown ones.

    The method decides the order's *initial status* (paid vs awaiting payment),
    so it must not be a free-form string: an unrecognised/forged value could
    otherwise steer the order into a status the caller didn't pay for.
    """
    method = (value or "").strip().upper()
    if method not in allowed:
        raise ValueError(f"payment_method must be one of {', '.join(allowed)}")
    return method


async def _db(fn, *args, **kwargs):
    """Run a blocking store call in a worker thread.

    The SQLite/Supabase stores are synchronous (psycopg2/sqlite3). Calling them
    directly inside an ``async def`` handler stalls FastAPI's event loop and
    serializes every concurrent request — which is exactly the latency users
    feel in production. Running the call in a thread keeps the loop free.
    """
    return await asyncio.to_thread(fn, *args, **kwargs)


def _push_admin(title: str, message: str, tag: str = "admin-alert") -> None:
    """Fire a web push to the admin's phone (fire-and-forget, never raises).

    Used at every spot that creates a `target_role="admin"` notification so
    the Admin Centre rings the admin's phone instead of only filling the bell.
    """
    try:
        push_service.notify_admin_async(title, message, {"url": "/admin-dashboard", "tag": tag})
    except Exception as e:
        logger.warning(f"Admin push '{title}' failed: {e}")


async def _cached_read(ttl: float, key: str, loader, *args, **kwargs):
    """Serve ``loader()`` from the layered read cache (memory → Redis → Postgres).

    Thin wrapper over :func:`app.core.read_cache.cached_read` so every endpoint
    in this module keeps the same call shape; ``key`` must vary per query params
    (that happens automatically — the arguments are folded into the cache key) so
    filtered results never cross wires. Every layer is invalidated after a write
    by the app-level middleware.
    """
    return await read_cache.cached_read(ttl, key, loader, *args, **kwargs)


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
    if time.monotonic() - _last_auto_confirm_run < 60:
        return
    _last_auto_confirm_run = time.monotonic()
    try:
        def _run():
            return db.auto_complete_expired_deliveries()
        asyncio.get_event_loop().run_in_executor(None, _run)
    except Exception:
        pass


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
    return {
        "connected": True,
        "mode": "supabase",
        "database": "Supabase Postgres",
        "persistent": True,
        "message": "Supabase Postgres is active. Business data is stored in a persistent cloud database.",
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
    whatsapp_number: str | None = None
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
    # Combo: ONE price for MANY items (Biryani + Fast Food + drink). When
    # is_combo is true the category is forced to "Combo" and combo_items holds
    # the item list text (one per line or comma-separated).
    is_combo: bool = False
    combo_items: str = ""


class LocalProductUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price: int | None = None
    pending_price: int | None = None
    category: str | None = None
    inventory: int | None = None
    prep_time: int | None = None
    available: bool | None = None
    is_combo: bool | None = None
    combo_items: str | None = None


def _require_vitap_location(value: str) -> str:
    """Delivery is VIT-AP campus only — reject anything outside it.

    The GPS "use my location" button and off-campus presets were removed from
    the UI, but a hand-crafted request could still send "Guntur" etc. This is
    the server-side guard: every order/payments path normalises through here.
    """
    loc = (value or "").strip()
    if not loc:
        raise ValueError("delivery_location is required")
    if not re.search(r"vit[\s-]*ap", loc, re.I):
        raise ValueError("Delivery is VIT-AP campus only — please choose a VIT-AP location.")
    return loc


class LocalOrderStatusUpdate(BaseModel):
    status: str


class LocalOrderItem(BaseModel):
    product_id: str
    # The cart UI lets a student pick a quantity per line; older clients omit it
    # (default 1). Declaring it here matters: Pydantic silently DROPS unknown
    # fields, so without this the server billed every line as a single unit no
    # matter how many the student actually chose.
    quantity: int = Field(1, ge=1, le=MAX_LINE_QUANTITY)


class LocalOrderCreate(BaseModel):
    shop_id: str
    items: list[LocalOrderItem]
    student_name: str = "Student"
    student_phone: str = ""
    delivery_location: str
    delivery_slot: str
    pending_payment: bool = False
    payment_method: str = "UPI"  # 'UPI' | 'COD' | 'Razorpay'

    @field_validator("delivery_location")
    @classmethod
    def _validate_location(cls, value: str) -> str:
        return _require_vitap_location(value)

    @field_validator("payment_method")
    @classmethod
    def _validate_payment_method(cls, value: str) -> str:
        return _clean_payment_method(value, ("UPI", "COD", "RAZORPAY"))



class LocalMultiShopOrder(BaseModel):
    """Multi-shop checkout payload: one list of shops, each with items."""
    shops: list[dict]
    student_name: str = "Student"
    student_phone: str = ""
    student_email: str = ""
    delivery_location: str
    delivery_slot: str = ""
    payment_method: str = "UTR"  # 'UTR' | 'COD'

    @field_validator("delivery_location")
    @classmethod
    def _validate_location(cls, value: str) -> str:
        return _require_vitap_location(value)

    @field_validator("payment_method")
    @classmethod
    def _validate_payment_method(cls, value: str) -> str:
        # Multi-shop has no per-shop gateway hook, so Razorpay is deliberately
        # not accepted here — a multi-shop bill is only settled by UPI/UTR proof
        # or cash on delivery.
        return _clean_payment_method(value, ("UTR", "COD", "UPI", "MANUAL UTR"))



class LocalSubOrderStatusUpdate(BaseModel):
    status: str
    notes: str = ""


class LocalComplaintCreate(BaseModel):
    parent_order_id: str
    student_name: str = ""
    student_phone: str = ""
    shop_id: str = ""
    shop_name: str = ""
    subject: str
    message: str
    proof_url: str = ""


class LocalRefundCreate(BaseModel):
    parent_order_id: str
    sub_order_id: str = ""
    student_name: str = ""
    shop_name: str = ""
    original_amount: int = 0
    refund_amount: int = 0
    refund_type: str = "Full"


class LocalAnnouncementCreate(BaseModel):
    shop_id: str
    message: str


class LocalAnnouncementToggle(BaseModel):
    is_active: int = 1


class LocalStudentNoticeUpdate(BaseModel):
    """Site-wide info block on the student home page (admin editor)."""

    enabled: bool | None = None
    text: str | None = Field(default=None, max_length=500)


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
    amount: int = Field(..., ge=1, le=1_000_000)
    method: str
    utr_number: str | None = None

    @field_validator("method")
    @classmethod
    def _validate_method(cls, value: str) -> str:
        # Keep the caller's spelling (views display it) but refuse anything
        # outside the methods the platform can actually settle.
        if (value or "").strip().lower() not in {"manual utr", "upi", "cod", "razorpay"}:
            raise ValueError("Unsupported payment method")
        return value


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


class LocalPhoneOnboarding(BaseModel):
    """Students joining from the student portal phone gate — name + mobile.
    A real account (and its JWT) is created behind the scenes so the rest of
    the order/payment flow works exactly like a password-login account."""
    name: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., min_length=7, max_length=20)
    campus: str = Field(default="", max_length=100)
    default_delivery_location: str = Field(default="", max_length=300)


class LocalAuthUser(BaseModel):
    id: int
    username: str
    name: str
    role: str
    email: str = ""
    phone: str = ""
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


async def _require_admin(authorization: Optional[str] = Header(None)) -> dict:
    """Require a valid token whose role is ``admin`` (mirrors local_admin.verify_admin)."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid authorization scheme")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    # A signed token is not proof of *current* privilege — re-check the account
    # in the database so a removed or downgraded admin cannot keep using an
    # unexpired token. The DEBUG-only dev fallback admin ("sub": "0") has no row
    # and is exempt, as is any non-numeric subject.
    if not settings.DEBUG:
        try:
            user_id = int(payload.get("sub"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=403, detail="Admin access required")
        user = await _db(db.get_user_by_id, user_id)
        if not user or user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")
    return payload


def _same_student(user: dict, order: dict) -> bool:
    """Only the server-assigned account ID proves ownership.

    Legacy names, contact phones and client-supplied student_id are not proof.
    Unassigned historical orders remain available to admins for review.
    """
    owner = str(order.get("owner_user_id") or "").strip()
    return bool(owner) and owner == str(user.get("id") or "")


def _require_agent_key(x_agent_key: Optional[str]) -> None:
    """Gate the bank-SMS endpoints on the Android agent's shared key.

    ``/sms/match`` and ``/sms/incoming`` can both move an order to **Confirmed**
    (i.e. mark it paid), so the check must fail CLOSED. Previously an unset
    ``SMS_FORWARD_KEY`` silently skipped the comparison, so on any deployment
    without the key one anonymous request carrying a plausible UTR + amount was
    enough to settle a pending UPI order. DEBUG deployments stay permissive so
    local flows and tests can drive the endpoints by hand.
    """
    configured = (settings.SMS_FORWARD_KEY or "").strip()
    if not configured:
        if settings.DEBUG:
            return
        raise HTTPException(
            status_code=503,
            detail="Bank-SMS ingest is not configured on this server (SMS_FORWARD_KEY is unset).",
        )
    if (x_agent_key or "") != configured:
        raise HTTPException(status_code=401, detail="Invalid agent key")


async def _resolve_owned_order(order_id: str, user: dict) -> tuple[dict, bool]:
    """Resolve an order id (single order OR multi-shop parent) and require that
    the caller owns it — admins may act on any order.

    Every money-moving endpoint must go through this: taking the ``order_id``
    from the request body without checking ownership lets one account attach a
    payment/verification to somebody else's order.
    """
    order = await _db(db.get_order, order_id)
    is_parent = False
    if not order:
        order = await _db(db.get_parent_order, order_id)
        is_parent = bool(order)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if user.get("role") != "admin" and not _same_student(user, order):
        raise HTTPException(status_code=403, detail="You can only pay for your own orders")
    return order, is_parent


# ─── Auth endpoints ───


@router.post("/auth/register", status_code=201)
async def local_register(data: LocalAuthRegister, request: Request):
    """Register a new user in the local database."""
    # A whole campus shares one public IP behind the college NAT, so a tight
    # per-IP cap would lock out every student after the first handful of
    # sign-ups. 40/hour still throttles mass bot registration while letting a
    # real onboarding rush through.
    if not rate_allow("register", rate_ip(request), max_attempts=40, window_sec=3600):
        raise HTTPException(status_code=429, detail="Too many sign-up attempts from this network — try again later.")

    # PENTEST FIX (critical): public registration must never mint an admin.
    # Previously role="admin" here created a real admin row + JWT, handing the
    # whole platform to anyone who could POST this endpoint. Admin accounts are
    # created server-side only (ensure_admin_user from env credentials).
    if data.role == "admin":
        raise HTTPException(status_code=403, detail="Admin accounts cannot be created through public registration.")

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
async def local_login(data: LocalAuthLogin, request: Request):
    """Authenticate user and return JWT tokens."""
    ip = rate_ip(request)
    if not rate_allow("login", f"{data.username}:{ip}", max_attempts=40, window_sec=300):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts — please wait a few minutes and try again.")

    user = await _db(db.get_user_by_username, data.username)
    # PENTEST FIX: identical message for "no such user" and "wrong password" —
    # distinct messages let an attacker enumerate which usernames exist. The
    # dummy hash runs bcrypt even for an unknown username, so both branches
    # take the same TIME as well as the same message.
    bad_credentials = "Invalid username or password."
    if not await asyncio.to_thread(
        verify_password, data.password,
        (user or {}).get("password_hash") or await asyncio.to_thread(hash_password, "x" * 16),
    ):
        raise HTTPException(status_code=401, detail=bad_credentials)
    if not user:
        raise HTTPException(status_code=401, detail=bad_credentials)

    rate_reset("login", f"{data.username}:{ip}")

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


@router.post("/auth/phone")
async def local_phone_onboarding(data: LocalPhoneOnboarding, request: Request):
    """Phone-first student onboarding (the student portal RoleGate).

    Creates or re-uses a ``student`` account keyed by phone and returns a real
    JWT, so payments/order APIs that need an authenticated user keep working —
    the student never has to remember a password.
    """
    ip = rate_ip(request)
    if not rate_allow("phone_onboard", f"{data.phone}:{ip}", max_attempts=30, window_sec=300):
        raise HTTPException(status_code=429, detail="Too many attempts from this device — please wait a few minutes.")

    phone = _normalize_phone(data.phone.strip())
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) < 10:
        raise HTTPException(status_code=400, detail="Please enter a valid 10-digit mobile number")

    username = f"stu_{digits[-10:]}"
    name = (data.name or "").strip() or "Student"

    user = await _db(db.get_user_by_username, username)
    if user:
        # Returning phone student — just re-issue a fresh token for them.
        pass
    else:
        pick_name = name or phone
        random_pw = secrets.token_urlsafe(16)
        password_hash_value = await asyncio.to_thread(hash_password, random_pw)
        new_user, conflict = await _db(
            db.register_user,
            username=username,
            password_hash=password_hash_value,
            name=pick_name,
            role="student",
            email="",
            phone=phone,
        )
        if conflict or not new_user:
            raise HTTPException(status_code=409, detail="Could not create your student account — please try again.")
        user = new_user
        logger.info(f"Phone-onboarding created student account {username}")

    token_data = {
        "sub": str(user["id"]),
        "username": user["username"],
        "name": user["name"],
        "role": "student",
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
            role="student",
            created_at=user["created_at"],
        ),
    )


@router.get("/auth/me")
async def local_me(current_user: dict = Depends(get_current_local_user)):
    """Get the current authenticated user's profile."""
    return current_user


class LocalProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    password: str | None = Field(default=None, min_length=4, max_length=128)


@router.patch("/auth/me")
async def local_update_me(data: LocalProfileUpdate, current_user: dict = Depends(get_current_local_user)):
    """Update the current student's profile — name, phone, email, and/or password.
    Auth is locked to the JWT subject, so a student can only ever edit their
    own row. Returns the updated profile and a fresh token so the client session
    reflects the new identity."""
    if current_user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id = current_user["id"]

    name = data.name.strip() if data.name is not None else None
    email = (data.email or "").strip() if data.email is not None else None
    phone = data.phone.strip() if data.phone is not None else None

    if name is not None and not name:
        raise HTTPException(status_code=422, detail="Name cannot be empty")

    # Email unique across the whole platform — one email = one account.
    if email is not None and email:
        existing = await _db(db.get_user_by_email, email)
        if existing and existing["id"] != user_id:
            raise HTTPException(status_code=409, detail="This email is already registered to another account")
    elif email is not None:
        email = ""

    if data.password:
        new_hash = await asyncio.to_thread(hash_password, data.password)
        # Update password via the dedicated helper (no password in the profile row).
        await _db(db.update_user_password, current_user["username"], new_hash)

    updated = await _db(db.update_user_profile, user_id, name=name, email=email, phone=phone)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")

    # Issue a fresh token so the name in the JWT/session matches immediately.
    token_data = {
        "sub": str(updated["id"]),
        "username": updated["username"],
        "name": updated["name"],
        "role": updated["role"],
    }
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return LocalAuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=LocalAuthUser(
            id=updated["id"],
            username=updated["username"],
            name=updated["name"],
            role=updated["role"],
            email=updated.get("email", "") or "",
            phone=updated.get("phone", "") or "",
            created_at=updated["created_at"],
        ),
    )


@router.get("/summary")
async def summary(_user: dict = Depends(get_current_local_user)):
    return await _cached_read(15, "summary", db.get_summary)


@router.post("/sessions")
async def create_session(data: LocalSessionCreate, _user: dict = Depends(get_current_local_user)):
    return await _db(persist_user_profile, data.email, data.name, data.role)


@router.get("/shops")
async def shops(public_only: bool = False):
    return await _cached_read(10, "shops", db.list_shops, public_only=public_only)


@router.post("/shops")
async def create_shop(data: LocalShopCreate, _admin: dict = Depends(_require_admin)):
    return await _db(db.create_shop, data.model_dump())


@router.patch("/shops/{shop_id}")
async def patch_shop(shop_id: str, data: LocalShopUpdate, _admin: dict = Depends(_require_admin)):
    shop = await _db(db.update_shop, shop_id, data.model_dump(exclude_unset=True))
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    return shop


@router.get("/shops/{shop_id}")
async def shop(shop_id: str):
    result = await _db(db.get_shop, shop_id)
    if not result:
        raise HTTPException(status_code=404, detail="Shop not found")
    return result


@router.get("/products")
async def products(shop_id: str | None = None):
    if shop_id:
        return await _cached_read(10, "products", db.list_products, shop_id)
    return await _cached_read(10, "products", db.list_products)


@router.post("/products")
async def add_product(data: LocalProductCreate, _admin: dict = Depends(_require_admin)):
    return await _db(db.create_product, data.model_dump())


@router.patch("/products/{product_id}")
async def patch_product(product_id: str, data: LocalProductUpdate, _admin: dict = Depends(_require_admin)):
    product = await _db(db.update_product, product_id, data.model_dump(exclude_unset=True))
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


async def _list_orders_sliced(current_user: dict) -> list[dict]:
    """Return orders for the current user. Admins get a bounded slice (latest 300)
    to keep the payload tiny; students get only their own orders. The bounded
    slice is safe because the admin dashboard and shopkeeper portal never need
    the full multi-day history on a poll — they only render recent activity."""
    limit = 300
    all_orders = await _db(db.list_orders, limit=limit)
    if current_user.get("role") == "admin":
        return all_orders
    return [o for o in all_orders if _same_student(current_user, o)]


@router.get("/orders")
async def orders(current_user: dict = Depends(get_current_local_user)):
    """List orders. Students only ever see their own orders (matched by name or
    phone); admins may list everything. A valid token is always required — the
    same-identity rule the student app already applies client-side is now also
    enforced server-side so an account holder can't enumerate other students'
    names, phones and delivery locations.

    Server-side TTL cache (10 s) so the admin dashboard's constant polling no
    longer re-hits the DB on every refresh — the client polls every 15 s, so a
    10 s cache is always warm and still fresh enough for status updates."""
    cache_key = "orders"
    return await _cached_read(10, cache_key, _list_orders_sliced, current_user)


@router.get("/orders/parent")
async def parent_orders_list(status: str | None = None, current_user: dict = Depends(get_current_local_user)):
    """List parent (multi-shop) orders. Logged-in students only ever receive
    THEIR OWN parent orders (name or phone match); admins may list everything.
    Declared before ``/orders/{order_id}`` so it can't be shadowed by the
    dynamic route (GET /orders/parent previously fell through to the dynamic
    segment with ``order_id="parent"`` and 404'd)."""
    all_orders = await _db(db.list_parent_orders, status=status)
    if current_user.get("role") == "admin":
        return all_orders
    return [o for o in all_orders if _same_student(current_user, o)]


@router.get("/orders/parent/{parent_order_id}")
async def parent_order_detail(parent_order_id: str, current_user: dict = Depends(get_current_local_user)):
    result = await _db(db.get_parent_order, parent_order_id)
    if not result:
        raise HTTPException(status_code=404, detail="Order not found")
    if current_user.get("role") != "admin" and not _same_student(current_user, result):
        raise HTTPException(status_code=403, detail="You can only view your own orders")
    return result


@router.get("/orders/{order_id}")
async def order(order_id: str, current_user: dict = Depends(get_current_local_user)):
    result = await _db(db.get_order, order_id)
    if not result:
        raise HTTPException(status_code=404, detail="Order not found")
    if current_user.get("role") != "admin" and not _same_student(current_user, result):
        raise HTTPException(status_code=403, detail="You can only view your own orders")
    return result


@router.post("/orders")
async def add_order(data: LocalOrderCreate, current_user: dict = Depends(get_current_local_user)):
    payload = data.model_dump()
    payload["owner_user_id"] = str(current_user["id"])
    # The student's mobile is always stored as E.164 (+91 + 10 digits) so the
    # shopkeeper/order views never see a bare 10-digit number.
    payload["student_phone"] = _normalize_phone(payload.get("student_phone", ""))
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
    order = await _db(db.create_order, payload)
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
            accepted = await _db(db.update_order_status, order["id"], "Accepted")
            if accepted:
                order = accepted
    except Exception as e:
        logger.warning(f"Could not auto-accept order {order.get('id')}: {e}")

    # Fire the vendor's phone notification without blocking the student's
    # response — the web push runs in a worker thread (fire-and-forget).
    try:
        asyncio.get_running_loop().create_task(
            push_service.notify_shop_new_order_async(order)
        )
    except Exception as e:
        logger.warning(f"Could not schedule order push notification: {e}")

    # SMS the shopkeeper (and a copy to the admin) + queue the shopkeeper's
    # WhatsApp. This MUST be awaited, not fired-and-forgotten: on the serverless
    # platform the request's background tasks are killed the moment the response
    # returns, so a create_task here would silently drop the order's WhatsApp
    # notification (which the phone bot then never receives). Awaiting keeps
    # the ordering latency at ~SMS-log cost and guarantees the notification.
    try:
        await _notify_order_via_sms(order)
    except Exception as e:
        logger.warning(f"Could not send order notifications: {e}")

    return order


@router.patch("/orders/{order_id}/status")
async def patch_order_status(order_id: str, data: LocalOrderStatusUpdate, _admin: dict = Depends(_require_admin)):
    order = await _db(db.update_order_status, order_id, data.status)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.patch("/orders/{order_id}/cancel")
@router.post("/orders/{order_id}/cancel")
async def cancel_own_order(order_id: str, current_user: dict = Depends(get_current_local_user)):
    """Let a student cancel their own order within its delivery window.

    Accepts both POST (native app) and PATCH (student portal) so old and new
    clients both work. Orders placed inside a delivery window (morning →
    12:30 PM, afternoon → 6:00 PM) are auto-accepted; the student can cancel
    them until the window closes. Once the window closes or the order is
    completed, cancellation is locked.
    """
    order = await _db(db.get_order, order_id)
    is_parent = False
    if not order:
        # Multi-shop parent order — cancel every still-open sub-order + parent.
        order = await _db(db.get_parent_order, order_id)
        is_parent = bool(order)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if not _same_student(current_user, order):
        raise HTTPException(status_code=403, detail="You can only cancel your own orders")

    # The day is split into two delivery windows (morning → 12:30 PM,
    # afternoon → 6:00 PM). Orders placed inside a window are auto-accepted;
    # the student can still cancel them until that window closes. Orders
    # outside the windows (after 6:00 PM) and terminal orders are locked.
    # "Pending" (fresh UTR/UPI order before payment is verified) is cancellable
    # too — most placed orders are in this state, not just Accepted.
    if order["status"] not in CANCELLABLE_STATUSES and order["status"] != "Pending":
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

    elif is_parent:
        updated = await _db(db.cancel_parent_order, order_id)
    else:
        updated = await _db(db.update_order_status, order_id, "Cancelled")

    # Close out any open payment intent (UPI orders create a 'Pending' payment
    # record at checkout) so the admin's payments table never shows a live
    # payment on a cancelled order. Status 'Cancelled' has no side effects on
    # the order itself (unlike 'Failed').
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


async def _notify_order_via_sms(order: dict) -> None:
    """Send the new-order SMS to the shopkeeper's phone and a copy to the admin.

    The message ends with "REPLY: YES <token> = CONFIRM | NO <token> = REJECT".
    A real gateway replaces the ``log_sms`` calls in ``send_sms_async``; the
    rest of the flow (webhook → Confirmed) is gateway-independent.

    WhatsApp for UPI orders is NOT fired here — it fires only after the
    payment amount is verified (see ``_confirm_order_via_utr``). COD orders
    have nothing to verify, so their WhatsApp notification goes out now.
    """
    try:
        if not order or not order.get("id"):
            return
        message = sms_service.compose_order_sms(order)
        shop = None
        shop = await _db(db.get_shop, order["shop_id"])
        shop_phone = str((shop or {}).get("phone") or "").strip()
        # Admin copy — the first registered admin's phone.
        admins = await _db(db.list_users_by_role, "admin")
        admin_phone = ""
        for a in admins or []:
            p = str((a or {}).get("phone") or "").strip()
            if p:
                admin_phone = p
                break
        if shop_phone:
            await sms_service.send_sms_async(
                shop_phone, message, _sms_log_fn, sub_order_id=order["id"]
            )
        if admin_phone:
            await sms_service.send_sms_async(
                admin_phone,
                f"DETOMSITE: {message.splitlines()[0]} — order is waiting for confirmation.",
                _sms_log_fn,
                sub_order_id=order["id"],
            )
        # WhatsApp the shopkeeper for EVERY new order. UPI is labelled
        # "awaiting payment" here (it flips to "paid ✓" via the bank-SMS /
        # UTR / screenshot verification paths — which dedupe against this row).
        if shop:
            whatsapp_phone = str((shop or {}).get("whatsapp_number") or "").strip() or str((shop or {}).get("phone") or "").strip()
            if whatsapp_phone:
                await _notify_shop_via_whatsapp(order, shop, whatsapp_phone, paid=False)
    except Exception as e:
        logger.warning(f"SMS notify error for order {order.get('id')}: {e}")


async def _whatsapp_link_for_order(order: dict, shop: dict, paid: bool | None = None) -> str:
    """Build the free ``wa.me`` deep-link that sends the order message from the
    admin's number to the shop's WhatsApp. No gateway, no cost — the admin taps
    it and WhatsApp opens with the order pre-filled."""
    from urllib.parse import quote
    from app.services.sms_service import compose_order_wa

    number = str(shop.get("whatsapp_number") or "").strip() or str(shop.get("phone") or "").strip()
    if not number:
        return ""
    digits = "".join(ch for ch in number if ch.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    text = compose_order_wa(order, paid=paid)
    return f"https://wa.me/{digits}?text={quote(text)}"


async def _notify_shop_via_whatsapp(order: dict, shop: dict, phone: str, paid: bool | None = None) -> None:
    """Notify the shopkeeper of an order on WhatsApp.

    EVERY order is notified at placement (UPI labelled "awaiting payment"). The
    payment-verification paths re-call this with ``paid=True``, which refreshes
    that same row to "paid ✓" — the shopkeeper sees one clean message and the
    money status is never stale.

    Delivery: when a WhatsApp provider is configured (``WA_PROVIDER``), the
    message is sent **automatically** right away — UPI immediately after the
    payment is verified, COD at placement — and the row flips to ``Sent``.
    With no provider it stays a ``Pending`` wa.me link for the admin to tap
    from their own number (zero-cost fallback). Either way the send path is
    best-effort and never raises.
    """
    try:
        from app.services.sms_service import compose_order_wa
        from app.services import whatsapp_service

        message = compose_order_wa(order, paid=paid)
        url = await _whatsapp_link_for_order(order, shop, paid=paid)
        if not url:
            return

        # UPI → auto-send once the payment is proven. COD → nothing to verify,
        # so auto-send at placement.
        auto = (paid is True) or str(order.get("payment_method") or order.get("pay_method") or "").upper() == "COD"
        row_id = None

        # Dedupe: if a Pending notification already exists for this order,
        # refresh its message (paid → "paid ✓") instead of stacking duplicates.
        existing = await _db(db.list_whatsapp_logs, 200)
        for row in existing or []:
            ref = str(row.get("sub_order_id") or row.get("order_id") or "")
            if ref == str(order["id"]) and str(row.get("status") or "") == "Pending":
                row_id = row.get("id")
                if paid is True:
                    await _db(db.update_whatsapp_message, row["id"], message, url)
                break

        if row_id is None:
            created = await _db(
                db.log_whatsapp,
                sub_order_id=order["id"],
                phone=phone,
                message=message,
                url=url,
                status="Pending",
            )
            row_id = (created or {}).get("id") or row_id

        # Automatic delivery when a gateway is configured.
        if auto and row_id and whatsapp_service.provider_configured():
            ok = await asyncio.to_thread(
                whatsapp_service.send_whatsapp, phone, message, None, order["id"]
            )
            if ok:
                await _db(db.mark_whatsapp_sent, row_id)
    except Exception as e:
        logger.warning(f"WhatsApp notify error for order {order.get('id')}: {e}")


def _sms_log_fn(sub_order_id: str, phone: str, message: str, status: str) -> dict | None:
    """Bounds to the active store's sync log_sms (runs in a worker thread)."""
    return db.log_sms(
        sub_order_id=sub_order_id,
        phone=phone,
        message=message,
        status=status,
        direction="out",
    )


async def _log_sms_inbound(order_id: str, phone: str, text: str, status: str) -> None:
    """Log an inbound SMS reply against the active store."""
    try:
        await _db(db.log_sms, order_id, phone, text, status=status, direction="in")
    except Exception as e:
        logger.warning(f"SMS inbound log error: {e}")


class LocalIncomingSms(BaseModel):
    """An SMS received on a phone — normally from the shopkeeper/admin replying
    ``YES <token>`` or ``NO <token>`` to confirm/reject an order."""
    phone: str = ""
    text: str = ""


def _extract_utr(text: str) -> str:
    """Pull a UPI transaction reference number out of a bank credit SMS.

    Returns the raw code (uppercased) or ``""`` when nothing is unambiguous —
    an ambiguous extraction must fall through to manual review, never guess.
    """
    from app.services import bank_sms_parser

    return bank_sms_parser.extract_utr(text)


def _extract_amount(text: str) -> float | None:
    """Parse the payment amount out of a bank credit SMS.

    Balance lines are ignored, and when more than one candidate amount is
    present (or none is) ``None`` is returned so the message is treated as
    needing manual review instead of being matched against the wrong order.
    """
    from app.services import bank_sms_parser

    return bank_sms_parser.extract_amount(text)


async def _get_payment_by_utr(utr: str):
    return await _db(db.get_payment_by_utr, utr)


async def _get_order(order_id: str):
    return await _db(db.get_order, order_id)


async def _bank_sms_seen(utr: str) -> bool:
    """Did a bank credit SMS containing this UTR already arrive? """
    return bool(await _db(db.bank_sms_seen, utr))


async def _confirm_order_via_utr(utr: str, phone: str = "", raw_text: str = "", bank_sms_arrived: bool = False) -> dict | None:
    """Legacy caller compatibility: a UTR-only historical log is not proof.

    Historical SMS logs omit the amount/account context. Do not use them to
    approve a student's claim; only a fresh, scoped proof can auto-confirm.
    """
    if not bank_sms_arrived or _extract_utr(raw_text) != utr:
        return None
    amount = _extract_amount(raw_text)
    if amount is None:
        return None
    try:
        # In-process call: bypass the HTTP agent gate (which requires the shared
        # key) and reuse the shared matching core directly.
        result = await _sms_match_core(LocalSmsMatch(phone=phone, utr=utr, amount=amount))
        return await _get_order(result["order_id"])
    except HTTPException:
        return None


class LocalPaymentUtr(BaseModel):
    order_id: str
    utr_number: str = Field(..., min_length=6, max_length=40)


@router.post("/payments/utr")
async def submit_payment_utr(data: LocalPaymentUtr, request: Request, current_user: dict = Depends(get_current_local_user)):
    """The student pastes the UPI transaction UTR after paying.

    It is stored against the order's payment record. When the shopkeeper's
    bank credit SMS (with the same UTR) arrives via ``/sms/incoming`` the two
    sides match and the order is auto-confirmed. If the bank SMS arrived first,
    an admin must review it; historical UTR-only logs cannot prove the amount.

    UTR is the ONLY proof the platform accepts now (the screenshot upload
    system was removed). If the checkout failed to create the payment row
    (the old "record didn't save" bug), this endpoint creates it on the spot
    from the SERVER-side order total — a UTR paste always saves.
    """
    # PENTEST FIX: bound UTR submissions per student+IP — every call writes to
    # (or probes) the payment record, so it must not be an unthrottled write
    # primitive. 12 per 5 minutes is far beyond any real retry pattern.
    if not rate_allow("utr", f"{current_user.get('id')}:{rate_ip(request)}", max_attempts=12, window_sec=300):
        raise HTTPException(status_code=429, detail="Too many UTR attempts — please wait a few minutes and try again.")

    # PENTEST FIX: a UTR is an alphanumeric reference (UPI UTRs are 12 digits).
    # Reject anything else BEFORE touching the order so junk/symbol-laden input
    # never reaches a query, and the student gets a message they can act on.
    utr = (data.utr_number or "").strip().upper()
    if not utr.isalnum() or not 6 <= len(utr) <= 40:
        raise HTTPException(
            status_code=422,
            detail="That doesn't look like a UTR — it is usually a 12-digit number with no spaces or symbols.",
        )

    # Resolve across single orders AND multi-shop parent orders — the multi
    # checkout pays one bill whose payment row lives on the parent, so the old
    # orders-only lookup made every parent UTR save 404 ("Order not found").
    order, is_parent = await _resolve_owned_order(data.order_id, current_user)

    server_total = int(round(float(order.get("total") or 0)))

    # One UTR = one payment: both databases enforce a unique index on
    # payments.utr_number. Pre-check so a re-used reference gets a FRIENDLY
    # 409 instead of the raw 500 crash students saw as "it didn't save".
    existing = await _db(db.get_payment_by_utr, utr)
    if existing and str(existing.get("order_id") or "") != str(data.order_id):
        raise HTTPException(
            status_code=409,
            detail="This UTR is already saved on another order — double-check the number, or contact support with your token.",
        )

    payment = await _db(db.set_payment_utr, data.order_id, utr)
    if not payment:
        if is_parent:
            payment = await _db(
                db.record_parent_payment, data.order_id, server_total, "Manual UTR", utr
            )
        else:
            payment = await _db(
                db.create_payment, data.order_id, server_total, "Manual UTR", utr
            )
    if not payment:
        raise HTTPException(status_code=400, detail="Could not save the UTR for this order — please try again.")

    # Multi-shop parents have no single bank-SMS hook yet — their UTR is
    # verified by the admin in the Admin Center. Single orders auto-match.
    if is_parent:
        return {
            "message": "UTR saved — the admin will verify your payment shortly.",
            "payment": payment,
            "order": None,
        }

    # Bank SMS may have arrived before the student typed the UTR.
    confirmed = await _confirm_order_via_utr(utr)
    if confirmed:
        return {"message": "UTR matched the bank SMS — your order is confirmed!", "payment": payment, "order": confirmed}
    return {
        "message": "UTR saved — waiting for a matching bank proof. If the SMS already arrived, ask the admin to review the payment.",
        "payment": payment,
        "order": None,
    }


@router.post("/sms/incoming")
async def sms_incoming(data: LocalIncomingSms, x_agent_key: Optional[str] = Header(None)):
    """Receive an inbound SMS reply and act on it.

    Two flows are supported:

    1. **Payment auto-confirm (bank SMS):** when the SMS contains a UTR that
       matches a student-entered UTR on a pending payment, the order is marked
       **Confirmed** automatically — the money is provably in the shop's bank.
    2. **Manual confirm/reject (plain phone):** ``YES <token>`` /
       ``NO <token>`` (case-insensitive) sets the order to **Confirmed** or
       **Cancelled**. Tokens are printed in the order SMS, so the shopkeeper
       can confirm from their plain phone — no app taps needed.
    """
    text = (data.text or "").strip()
    phone = (data.phone or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="No SMS text provided")

    # Agent auth: fail closed (see ``_require_agent_key``). With no key
    # configured the endpoint refuses to run instead of letting any anonymous
    # caller inject "YES <token>" / a fake bank UTR and confirm an order.
    _require_agent_key(x_agent_key)

    report = {"received": True, "phone": phone, "text": text, "order": None}

    # All bank proofs use the same strict UTR + shop + amount match.
    utr = _extract_utr(text)
    amount = _extract_amount(text)
    if utr and amount is not None:
        # Already past the agent gate above — go straight to the matching core
        # instead of re-entering the HTTP-level key check.
        result = await _sms_match_core(LocalSmsMatch(phone=phone, utr=utr, amount=amount))
        report["order"] = await _get_order(result["order_id"])
        report["matched"] = result
        return report
    # Bank text must not fall through to YES/NO commands (e.g. "Ref No").
    if not re.fullmatch(r"(?i)(?:yes|y|confirm|accept|ok|no|n|reject|decline|cancel)\s+#?\d+", text):
        raise HTTPException(status_code=400, detail="Unrecognised or ambiguous SMS; manual review required")

    # Flow 2 — "YES 123" / "NO 123" — token may carry a leading #.
    lowered = text.lower().replace("#", " ")
    words = lowered.split()
    action = None
    token = ""
    for i, w in enumerate(words):
        if w in ("yes", "y", "confirm", "accept", "ok"):
            action = "Confirmed"
            if i + 1 < len(words):
                token = words[i + 1]
            break
        if w in ("no", "n", "reject", "decline", "cancel"):
            action = "Cancelled"
            if i + 1 < len(words):
                token = words[i + 1]
            break
    if not action:
        await _log_sms_inbound("", phone, "", "Unknown")
        raise HTTPException(status_code=400, detail="Unrecognised SMS — send a UTR to auto-confirm, or reply YES <token> / NO <token>.")

    # Tokens repeat across shops: scope to one unambiguous sender/shop.
    shop = await _db(db.get_shop_by_phone, phone)
    orders = await _db(db.list_orders_by_shop, shop["id"]) if shop else []
    candidates = [o for o in orders if str(o.get("token")) == token
                  and o.get("status") in ("Pending", "Placed", "Pending Payment")]
    order = candidates[0] if len(candidates) == 1 else None
    if not order:
        await _log_sms_inbound("", phone, f"token:{token or '?'}", "No Match")
        raise HTTPException(status_code=404, detail=f"No order with token #{token} found.")

    if action == "Confirmed" and order.get("status") == "Pending Payment":
        raise HTTPException(status_code=409, detail="Payment must be verified before confirmation")
    if action == "Confirmed":
        updated = await _db(db.update_order_status, order["id"], "Confirmed")
        # The admin watches the pipeline too — bell them when a shop
        # confirms an order over SMS (shop + admin both have the app).
        try:
            await _db(
                db.create_notification,
                title="Order confirmed via SMS",
                message=f"Token #{token} confirmed — {order.get('shop_name', 'a shop')} accepted the order.",
                order_id=order["id"],
                status="Confirmed",
                target_role="admin",
            )
        except Exception as e:
            logger.warning(f"Admin SMS-confirm notification error: {e}")
        _push_admin(
            "Order confirmed via SMS",
            f"Token #{token} confirmed — {order.get('shop_name', 'a shop')} accepted the order.",
            tag="order-confirm",
        )
        if not updated:
            raise HTTPException(status_code=400, detail="Could not confirm the order.")
    else:
        updated = await _db(db.update_order_status, order["id"], "Cancelled")
        if not updated:
            raise HTTPException(status_code=400, detail="Could not cancel the order.")

    # Log the inbound reply and the confirmation SMS to the student.
    await _log_sms_inbound(order["id"], phone, f"{action} #{token}", "Processed")
    try:
        student_phone = str(order.get("student_phone") or "").strip()
        if student_phone and action == "Confirmed":
            await sms_service.send_sms_async(
                student_phone,
                sms_service.compose_confirmation_sms(order),
                _sms_log_fn,
                sub_order_id=order["id"],
            )
    except Exception as e:
        logger.warning(f"SMS confirmation log error: {e}")

    report["order"] = updated or order
    return report


class LocalSmsMatch(BaseModel):
    """Privacy-first payment proof: only the UTR + amount extracted on-device.

    The raw bank SMS text never touches this server. The Android agent reads the
    SMS on the shopkeeper's phone, pulls out the UTR and credited amount locally,
    and sends only these two fields plus the receiving phone number.
    """
    phone: str = ""
    utr: str = Field(..., min_length=8, max_length=30, pattern=r"^[A-Za-z0-9]+$")
    amount: float = Field(..., gt=0, allow_inf_nan=False)


@router.post("/sms/match")
async def sms_match(data: LocalSmsMatch, x_agent_key: Optional[str] = Header(None)):
    """Privacy-first auto-confirm: the shop's Android agent extracts the UTR
    and amount **on-device** and sends only the minimal proof here — the raw
    bank SMS text never leaves the phone.

    Requires one saved UTR claim at the shop identified by ``phone``, with
    both order and payment amounts equal to ``amount``. Marks it
    **Confirmed**, and fires the shopkeeper's WhatsApp notification.
    """
    # Agent auth: fail closed. Only the Android agent (which holds the shared
    # key) may submit bank SMS — an unset key must NOT mean "everyone is the
    # agent", because this endpoint can mark an order paid.
    _require_agent_key(x_agent_key)
    return await _sms_match_core(data)


async def _sms_match_core(data: LocalSmsMatch) -> dict:
    """Shared matching logic behind ``/sms/match``.

    Split out of the route so the in-process UTR confirmation path
    (``_confirm_order_via_utr``) can reuse it WITHOUT re-entering the HTTP agent
    gate: that gate fails closed when no ``SMS_FORWARD_KEY`` is configured, and
    the internal path must keep working (it already requires a freshly arrived
    bank SMS carrying the same UTR).
    """
    utr = (data.utr or "").strip().upper()
    if not utr:
        raise HTTPException(status_code=400, detail="UTR is required")
    amount = data.amount
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be > 0")

    try:
        shop = None
        shop = await _db(db.get_shop_by_phone, data.phone)
        if not shop:
            raise HTTPException(status_code=404, detail="No shop found matching this phone number")

        orders = await _db(db.list_orders_by_shop, shop["id"])
        # Amount alone is not an identity: require exactly one saved UTR claim.
        payments = await _db(db.list_payments)
        claims = [p for p in payments if str(p.get("utr_number") or "").strip().upper() == utr]
        if len(claims) != 1:
            raise HTTPException(status_code=409, detail="Payment needs review: no unique saved UTR match")
        payment = claims[0]
        order = next((o for o in orders if o["id"] == payment.get("order_id")), None)
        if (not order or order.get("status") != "Pending Payment"
                or str(order.get("payment_method") or "").upper() not in ("UPI", "MANUAL UTR")
                or payment.get("status") == "Success"
                or abs(float(order.get("total") or 0) - amount) >= 0.01
                or abs(float(payment.get("amount") or 0) - amount) >= 0.01):
            raise HTTPException(status_code=409, detail="Payment proof does not match this shop's pending UPI order")

        await _db(db.update_payment_status, payment["id"], "Success")

        await _db(db.update_order_status, order["id"], "Confirmed")

        await _log_sms_inbound(order["id"], data.phone, f"UTR:{utr} Amt:{int(order.get('total', 0))}", "Auto-Confirmed")

        # Student + admin notifications.
        try:
            await _db(
                db.create_notification,
                title="Auto-confirmed via bank UTR",
                message=f"UTR {utr} — ₹{order.get('total')} credit confirmed. Token #{order.get('token')}.",
                order_id=order["id"],
                status="Confirmed",
                target_role="student",
            )
            await _db(
                db.create_notification,
                title="Auto-confirmed via bank UTR",
                message=f"UTR {utr} — ₹{order.get('total')} credit confirmed. Token #{order.get('token')}.",
                order_id=order["id"],
                status="Confirmed",
                target_role="admin",
            )
        except Exception as e:
            logger.warning(f"sms/match notification error: {e}")
        _push_admin(
            "Order auto-confirmed via bank UTR",
            f"UTR {utr} — ₹{order.get('total')} credit confirmed. Token #{order.get('token')}.",
            tag="order-confirm",
        )

        # WhatsApp fire.
        try:
            wa_phone = str((shop.get("whatsapp_number") or "")).strip() or str((shop.get("phone") or "")).strip()
            if wa_phone:
                await _notify_shop_via_whatsapp(order, shop, wa_phone, paid=True)
        except Exception as e:
            logger.warning(f"sms/match WhatsApp error for {order.get('id')}: {e}")

        return {
            "matched": True,
            "utr": utr,
            "amount": int(amount),
            "shop": shop.get("id"),
            "order_id": order["id"],
            "order_status": "Confirmed",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"sms/match error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")


@router.get("/whatsapp/pending")
async def whatsapp_pending_agent(x_agent_key: Optional[str] = Header(None)):
    """Pending WhatsApp notifications for the on-phone auto-send bot (same
    ``X-Agent-Key`` as the SMS agent).

    Returns rows that are already **ready to deliver** — COD messages and
    paid-verified UPI messages. Drafts still labelled "awaiting payment" are
    skipped so the bot waits for the payment verification to refresh them to
    "paid ✓" and then sends exactly ONE clean message (never a stale
    "awaiting payment" followed by a final one).
    """
    # Agent auth: fail closed — this feed carries customer phone numbers and
    # order messages, so an anonymous caller must never be able to read it.
    _require_agent_key(x_agent_key)

    logs = await _db(db.list_whatsapp_logs, 100)
    pending = []
    for log in logs or []:
        if str(log.get("status") or "").lower() == "sent":
            continue
        message = str(log.get("message") or "").strip()
        if "awaiting payment" in message.lower():
            continue
        pending.append(
            {
                "id": log.get("id"),
                "sub_order_id": log.get("sub_order_id") or log.get("order_id") or "",
                "phone": str(log.get("phone") or "").strip(),
                "message": message,
            }
        )
    return pending


@router.post("/whatsapp/{whatsapp_id}/mark-sent")
async def whatsapp_mark_sent_agent(whatsapp_id: str, x_agent_key: Optional[str] = Header(None)):
    """Mark a WhatsApp notification as sent once the phone bot delivered it."""
    _require_agent_key(x_agent_key)
    doc = await _db(db.mark_whatsapp_sent, whatsapp_id)
    if not doc:
        raise HTTPException(status_code=404, detail="WhatsApp notification not found")
    return doc


@router.get("/sms-logs")
async def sms_logs(limit: int = 100, _admin: dict = Depends(_require_admin)):
    """Admin view of all SMS messages (out-bound orders + inbound replies)."""
    return await _db(db.list_sms_logs, limit)


@router.get("/payments")
async def payments(_admin: dict = Depends(_require_admin)):
    """Payment records (with bank UTRs) are admin-only — students never read them."""
    return await _cached_read(10, "payments", db.list_payments)


@router.post("/payments")
async def add_payment(data: LocalPaymentCreate, current_user: dict = Depends(get_current_local_user)):
    # Resolve the target across single orders AND multi-shop parent orders — a
    # multi order's id lives in `parent_orders`, not `orders`, so the old
    # orders-only lookup made every UPI/UTR payment for the student's multi
    # cart 404 ("Order not found").
    order, is_parent = await _resolve_owned_order(data.order_id, current_user)

    # ─── Server-authoritative amount ───
    # The amount is recorded from the STORED order total, never from the request
    # body: a student could otherwise declare ₹1 against a ₹500 order, and every
    # downstream "does the bank credit match?" check would compare against that
    # ₹1. A price change between add-to-cart and checkout only means the
    # recorded amount (and therefore the amount the bank SMS must match) follows
    # the real bill.
    server_total = int(round(float(order.get("total") or 0)))
    if server_total > 0 and int(data.amount) != server_total:
        logger.warning(
            "Payment amount override for order %s: client=%s server=%s (user=%s)",
            data.order_id, data.amount, server_total, current_user.get("id"),
        )
        data.amount = server_total
    # A student may only record payment for an order they own.
    if current_user.get("role") != "admin" and not _same_student(current_user, order):
        raise HTTPException(status_code=403, detail="You can only pay for your own orders")
    if data.method == "Manual UTR":
        if is_parent:
            # Multi-shop: the student pays ONE bill to the platform UPI id
            # (the one shown at checkout). No per-shop UTR token exists yet.
            payment_settings = await _db(db.get_payment_settings)
            if not payment_settings["manual_enabled"] or not payment_settings["upi_id"]:
                raise HTTPException(status_code=400, detail="No UPI payment configured for this order")
        else:
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

    # One UTR = one payment (unique index on payments.utr_number in both DBs).
    # A re-used reference must fail with a FRIENDLY 409 at checkout too — never
    # the raw 500 students saw as "it didn't save".
    utr_claim = (data.utr_number or "").strip().upper()
    if utr_claim:
        existing = await _db(db.get_payment_by_utr, utr_claim)
        if existing and str(existing.get("order_id") or "") != str(data.order_id):
            raise HTTPException(
                status_code=409,
                detail="This UTR is already saved on another order — double-check the number, or leave it empty and submit it on the order page.",
            )

    if not is_parent:
        payment = await _db(
            db.create_payment,
            data.order_id,
            data.amount,
            data.method,
            data.utr_number,
        )
    else:
        payment = await _db(
            db.record_parent_payment,
            data.order_id,
            data.amount,
            data.method,
            data.utr_number,
        )
    if not payment:
        raise HTTPException(status_code=400, detail="Unable to create payment")

    # UTR-first: the student's UTR is asked at checkout. The order is only
    # accepted once the bank credit SMS carrying this UTR arrives (security
    # anchor inside _confirm_order_via_utr) — if the SMS already landed before
    # the student paid, it is accepted right now.
    matched = None
    utr = (data.utr_number or "").strip().upper()
    # Multi-shop parents have no single bank-SMS hook yet — their UTR proof is
    # verified by the admin in the Admin Center instead.
    if not is_parent and data.method == "Manual UTR" and utr:
        matched = await _confirm_order_via_utr(utr, raw_text=f"UTR:{utr} Paid")
    if matched:
        return {**payment, "order": matched, "matched": {"utr": utr}}
    # A manual payment that did not auto-match the bank SMS needs the admin to
    # verify the proof — ring the admin's phone (web push, best-effort).
    if str(data.method or "").upper() != "COD":
        _push_admin(
            "New payment to verify",
            f"{current_user.get('name') or current_user.get('username')} submitted {'a multi-shop' if is_parent else 'a'} payment proof "
            f"(₹{data.amount}) — verify in Admin Center → Payments.",
            tag="payment-verify",
        )
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
async def create_razorpay_order(
    data: LocalRazorpayOrderCreate,
    current_user: dict = Depends(get_current_local_user),
):
    """Create a Razorpay order for payment.

    Authenticated AND amount-bound: the payable amount is derived from the
    STORED order total, never from the request body. Previously the caller's
    ``amount`` was forwarded to the gateway as-is and no token was required, so
    anyone could open a ₹1 gateway order against a ₹500 local order.
    """
    order, is_parent = await _resolve_owned_order(data.order_id, current_user)

    payment_settings = await _db(db.get_payment_settings)
    if not payment_settings.get("razorpay_enabled"):
        raise HTTPException(status_code=400, detail="Razorpay is not enabled by admin")

    key_id = settings.RAZORPAY_KEY_ID
    key_secret = settings.RAZORPAY_KEY_SECRET
    if not key_id or not key_secret:
        raise HTTPException(status_code=500, detail="Razorpay API keys not configured on server")

    if str(order.get("status") or "") != "Pending Payment":
        raise HTTPException(status_code=400, detail="This order is not awaiting an online payment.")

    expected_paise = int(round(float(order.get("total") or 0) * 100))
    if expected_paise <= 0:
        raise HTTPException(status_code=400, detail="This order has nothing left to pay.")
    if int(data.amount) != expected_paise:
        raise HTTPException(
            status_code=400,
            detail=f"Payment amount must be ₹{expected_paise // 100} for this order.",
        )

    try:
        import razorpay
        client = razorpay.Client(auth=(key_id, key_secret))

        # Create Razorpay order (network call — off the event loop)
        razorpay_order = await asyncio.to_thread(
            client.order.create,
            {
                "amount": expected_paise,
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
async def verify_razorpay_payment(
    data: LocalRazorpayVerify,
    current_user: dict = Depends(get_current_local_user),
):
    """Verify a Razorpay payment signature and mark the order paid.

    Three independent checks are enforced before the order is marked paid:
    the caller must own the order, the captured amount must equal the stored
    order total, and the gateway payment id must not already be recorded
    against another order (replay). Without them a single ₹1 payment could be
    presented as settling an arbitrary order.
    """
    order, is_parent = await _resolve_owned_order(data.order_id, current_user)

    if str(order.get("status") or "") != "Pending Payment":
        raise HTTPException(status_code=400, detail="This order is not awaiting an online payment.")

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

        # ─── Amount binding: the gateway amount must match the order total ───
        expected_rupees = float(order.get("total") or 0)
        if abs(amount_rupees - expected_rupees) >= 0.01:
            raise HTTPException(
                status_code=400,
                detail=f"The amount paid (₹{amount_rupees}) does not match this order's total (₹{int(expected_rupees)}).",
            )

        # ─── Replay guard: one gateway payment settles exactly one order ───
        existing_payments = await _db(db.list_payments)
        if any(
            str(p.get("utr_number") or "").strip() == data.razorpay_payment_id
            for p in existing_payments
        ):
            raise HTTPException(status_code=409, detail="This payment has already been applied to an order.")
        if any(
            str(p.get("order_id") or "") == data.order_id and str(p.get("status") or "") == "Success"
            for p in existing_payments
        ):
            raise HTTPException(status_code=409, detail="This order has already been paid.")

        # Create payment record in local DB
        if is_parent:
            payment = await _db(
                db.record_parent_payment,
                data.order_id,
                amount_rupees,
                "Razorpay",
                data.razorpay_payment_id,
                None,
            )
        else:
            payment = await _db(
                db.create_payment,
                order_id=data.order_id,
                amount=amount_rupees,
                method="Razorpay",
                utr_number=data.razorpay_payment_id,
            )
        if not payment:
            raise HTTPException(status_code=400, detail="Could not save payment record")

        # Payment verified → the order is now genuinely paid and can move on to
        # the shop's acceptance queue. Parent (multi-shop) orders keep their
        # status on parent_orders.
        if is_parent:
            await _db(db.update_parent_order_status, data.order_id, "Pending Acceptance")
        else:
            await _db(db.update_order_status, data.order_id, "Pending Acceptance")

        return {
            "message": "Payment verified successfully",
            "payment": payment,
        }
    except HTTPException:
        # Ownership/amount/replay rejections must reach the client as-is instead
        # of being flattened into the generic "verification failed" 400 below.
        raise
    except Exception as e:
        logger.error(f"Error verifying Razorpay payment: {e}")
        raise HTTPException(status_code=400, detail=f"Payment verification failed: {str(e)}")


@router.get("/payment-settings")
async def payment_settings():
    return await _cached_read(30, "payment-settings", db.get_payment_settings)


@router.patch("/payment-settings")
async def patch_payment_settings(data: LocalPaymentSettings, _admin: dict = Depends(_require_admin)):
    """Update payment settings. Only an authenticated admin may change them.

    PENTEST FIX: this used to decode the JWT and trust its ``role`` claim
    alone — unlike every other admin route — so a removed or downgraded admin
    kept write access to payment details until the token expired. It now goes
    through ``_require_admin``, which re-checks the account in the database.
    """
    return await _db(db.update_payment_settings, data.model_dump(exclude_unset=True))


@router.get("/student-notice")
async def student_notice():
    """Public info block shown at the top of the student home page.

    Returns ``{"enabled": bool, "text": str}`` — the student app only renders a
    green banner when ``enabled`` is true AND the text is non-empty, so the
    admin can switch it off (or clear the text) and students immediately stop
    seeing it. Cached 30 s; any admin write clears the read cache.
    """
    return await _cached_read(30, "student-notice", db.get_student_notice)


@router.patch("/student-notice")
async def patch_student_notice(data: LocalStudentNoticeUpdate, _admin: dict = Depends(_require_admin)):
    """Set the student info block text / on-off switch. Admin-only — the same
    DB-backed audit as every other admin write (``_require_admin`` re-checks the
    account instead of trusting the token's ``role`` claim)."""
    return await _db(db.update_student_notice, data.model_dump(exclude_unset=True))


@router.patch("/payments/{payment_id}/status")
async def patch_payment_status(payment_id: str, data: LocalPaymentStatusUpdate, _admin: dict = Depends(_require_admin)):
    payment = await _db(db.update_payment_status, payment_id, data.status)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


@router.get("/tickets")
async def tickets(current_user: dict = Depends(get_current_local_user)):
    """Support tickets — role-aware.

    Admins see every ticket. Students (and shopkeepers) only ever receive
    THEIR OWN tickets, matched by the authenticated account's email. Name-only
    matching is used solely for legacy phone-onboarded accounts that have no
    email address; it is never an OR fallback for email accounts (common names
    like "Student" would otherwise leak tickets across users)."""
    all_tickets = await _db(db.list_tickets)
    if current_user.get("role") == "admin":
        return all_tickets
    email = str(current_user.get("email") or "").strip().lower()
    if email:
        # Email accounts: strict email match only. Never fall back to name —
        # two different students can share the same display name.
        return [
            t for t in all_tickets
            if str(t.get("email") or "").strip().lower() == email
        ]
    name = str(current_user.get("name") or "").strip().lower()
    if not name:
        return []
    # No-email (phone-onboarded) legacy accounts: match on name AND phone so two
    # accounts sharing the generic "Student" display name never see each
    # other's tickets. (Email accounts never reach here — strict email match.)
    phone = "".join(ch for ch in str(current_user.get("phone") or "") if ch.isdigit())
    out = []
    for t in all_tickets:
        if str(t.get("name") or "").strip().lower() != name:
            continue
        if phone:
            t_phone = "".join(ch for ch in str(t.get("phone_number") or "") if ch.isdigit())
            # Compare last-10 digits so +91/0 formatting never hides own ticket.
            if t_phone[-10:] != phone[-10:]:
                continue
        out.append(t)
    return out


@router.post("/tickets")
async def add_ticket(data: LocalTicketCreate, current_user: dict = Depends(get_current_local_user)):
    # Stamp ownership from the authenticated JWT, not the client-supplied form
    # fields. Otherwise any student could file a ticket with someone else's
    # email/name (or omit them on purpose) and either impersonate them or make
    # their own ticket invisible to the role-aware GET above.
    payload = data.model_dump()
    if current_user.get("role") != "admin":
        server_email = str(current_user.get("email") or "").strip()
        server_name = str(current_user.get("name") or "").strip()
        server_phone = str(current_user.get("phone") or "").strip()
        if server_email:
            payload["email"] = server_email
        elif not payload.get("email"):
            # Phone-onboarded accounts have no email: keep the ticket readable
            # by stamping a stable per-account placeholder (username-based), so
            # the row still satisfies the NOT NULL email column.
            payload["email"] = f"{current_user.get('username', 'student')}@phone.local"
        if server_name:
            payload["name"] = server_name
        if server_phone:
            payload["phone_number"] = server_phone
    return await _db(db.create_ticket, payload)


@router.get("/notifications")
async def notifications(role: str | None = None, current_user: dict = Depends(get_current_local_user)):
    """Return only notifications the authenticated account may read."""
    if current_user.get("role") == "admin":
        return await _db(db.list_notifications, role=role)
    if current_user.get("role") != "student":
        return []
    rows = await _db(db.list_notifications, role="student")
    visible = []
    for row in rows:
        order_id = row.get("order_id")
        if not order_id:
            continue  # Unaddressed legacy events cannot safely identify a recipient.
        order = await _db(db.get_order, order_id)
        if not order:
            order = await _db(db.get_parent_order, order_id)
        if not order:
            sub = await _db(db.get_sub_order, order_id)
            if sub and sub.get("parent_order_id"):
                order = await _db(db.get_parent_order, sub["parent_order_id"])
        if order and _same_student(current_user, order):
            visible.append(row)
    return visible


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
    _push_admin(
        "New feedback",
        f"[{feedback.get('category') or 'Bug'}] {feedback.get('subject') or feedback.get('message', '')[:80]} — by {values.get('name') or values.get('username') or 'guest'}",
        tag="feedback",
    )
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


def _load_current_batch() -> dict:
    """Live batch window + token info.

    The 30-minute auto-confirm sweep rides along with this read (it is the most
    polled endpoint) — and only on a cache miss, exactly as before.
    """
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


@router.get("/batch")
async def current_batch():
    """Which delivery batch is accepting orders right now + stock info."""
    return await _cached_read(5, "batch", _load_current_batch)


def _load_products_with_stock() -> list[dict]:
    """Every product annotated with the remaining stock for the live batch.

    One worker-thread hop for all three store reads (they used to be awaited one
    after another on the event loop).
    """
    batch_type = db.get_current_batch()
    products = db.list_products()
    date_key = db._day_key()
    stocks = db.get_product_stocks(batch_type, date_key)
    for p in products:
        p["batch_type"] = batch_type
        p["stock_left"] = stocks.get(p["id"], 0)
    return products


@router.get("/products/stock")
async def products_with_stock(_user: dict = Depends(get_current_local_user)):
    """Every product with its per-batch remaining stock."""
    return await _cached_read(5, "products-stock", _load_products_with_stock)


@router.post("/orders/multi")
async def create_multi_shop_order(data: LocalMultiShopOrder, current_user: dict = Depends(get_current_local_user)):
    """Place a multi-shop order (combo). Creates one parent order + per-shop
    sub-orders sharing a single token. The student pays ONE bill."""
    if not data.shops:
        raise HTTPException(status_code=400, detail="No shops selected.")
    payload = data.model_dump()
    payload["student_phone"] = _normalize_phone(payload.get("student_phone", ""))

    # ``shops`` is a free-form list[dict] (the shape is validated deeper in the
    # store), so the per-line quantity must be bounded HERE: an unbounded value
    # would be multiplied straight into the bill and the stock decrement.
    for group in payload["shops"]:
        items = group.get("items") or []
        if not items:
            raise HTTPException(status_code=400, detail="One of the selected shops has no items in your cart.")
        for item in items:
            raw_quantity = item.get("quantity", 1)
            if raw_quantity is None or raw_quantity == "":
                raw_quantity = 1  # older clients omit the field entirely
            try:
                quantity = int(raw_quantity)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid item quantity.")
            if not 1 <= quantity <= MAX_LINE_QUANTITY:
                raise HTTPException(
                    status_code=400,
                    detail=f"You can order between 1 and {MAX_LINE_QUANTITY} of the same item.",
                )
            item["quantity"] = quantity

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
            student_id=str(current_user["id"]),
            owner_user_id=str(current_user["id"]),
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

    # COD multi-shop: money is on delivery, so each shopkeeper's WhatsApp
    # notification fires right away — exactly the COD rule from the single-shop
    # flow. (UPI/UTR parents stay Pending until proof arrives; multi-shop has no
    # per-shop gateway hook, so the verified trigger does not exist yet there.)
    if str(parent.get("payment_method") or "").upper() == "COD":
        for sub in parent.get("sub_orders", []):
            try:
                shop = await _db(db.get_shop, sub["shop_id"])
                wa_phone = str((shop or {}).get("whatsapp_number") or "").strip() or str((shop or {}).get("phone") or "").strip()
                if shop and wa_phone:
                    wa_order = {
                        "id": sub["id"],
                        "token": sub["token"],
                        "items": sub["items_summary"],
                        "student_name": parent.get("student_name", ""),
                        "student_phone": parent.get("student_phone", ""),
                        "delivery_location": parent.get("delivery_location", ""),
                        "total": sub["subtotal"],
                        "payment_method": "COD",
                    }
                    await _notify_shop_via_whatsapp(wa_order, shop, wa_phone)
            except Exception as e:
                logger.warning(f"Could not schedule sub-order WhatsApp for {sub.get('id')}: {e}")

    return parent


@router.get("/shop-orders/{shop_id}")
async def shop_sub_orders(shop_id: str, status: str | None = None, _admin: dict = Depends(_require_admin)):
    """A shop's own sub-orders (only THIS shop's items, never other shops')."""
    return await _db(db.get_shop_sub_orders, shop_id, status)


@router.patch("/shop-orders/{sub_order_id}/status")
async def patch_sub_order_status(sub_order_id: str, data: LocalSubOrderStatusUpdate, _admin: dict = Depends(_require_admin)):
    updated = await _db(db.update_sub_order_status, sub_order_id, data.status, data.notes)
    if not updated:
        raise HTTPException(status_code=404, detail="Sub-order not found")
    return updated


@router.get("/announcements")
async def announcements(shop_id: str | None = None, active_only: bool = True):
    """Shop announcement bar items shown to students on the shop page."""
    return await _db(db.list_shop_announcements, shop_id, active_only)


@router.post("/announcements")
async def add_announcement(data: LocalAnnouncementCreate, _admin: dict = Depends(_require_admin)):
    ann = await _db(db.create_shop_announcement, data.shop_id, data.message)
    if not ann:
        raise HTTPException(status_code=400, detail="Could not post announcement.")
    return ann


@router.patch("/announcements/{ann_id}")
async def patch_announcement(ann_id: str, data: LocalAnnouncementToggle, _admin: dict = Depends(_require_admin)):
    ann = await _db(db.toggle_shop_announcement, ann_id, bool(data.is_active))
    if not ann:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return ann


# ─── Complaints (student → admin review) ───


@router.get("/complaints")
async def complaints(status: str | None = None, _admin: dict = Depends(_require_admin)):
    if status:
        return await _cached_read(10, "complaints", db.list_complaints, status)
    return await _cached_read(10, "complaints", db.list_complaints)


@router.post("/complaints")
async def add_complaint(data: LocalComplaintCreate, current_user: dict = Depends(get_current_local_user)):
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
async def patch_complaint(complaint_id: str, data: LocalComplaintStatusUpdate, _admin: dict = Depends(_require_admin)):
    updated = await _db(db.update_complaint, complaint_id, data.status, data.admin_notes)
    if not updated:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return updated


# ─── Refunds (admin → student back) ───


@router.get("/refunds")
async def refunds(status: str | None = None, _admin: dict = Depends(_require_admin)):
    if status:
        return await _cached_read(10, "refunds", db.list_refunds, status)
    return await _cached_read(10, "refunds", db.list_refunds)


@router.post("/refunds")
async def add_refund(data: LocalRefundCreate, _admin: dict = Depends(_require_admin)):
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
async def patch_refund(refund_id: str, data: LocalRefundUpdate, _admin: dict = Depends(_require_admin)):
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
async def settlements(status: str | None = None, _admin: dict = Depends(_require_admin)):
    if status:
        return await _cached_read(10, "settlements", db.list_settlements, status)
    return await _cached_read(10, "settlements", db.list_settlements)


@router.post("/settlements/run")
async def run_settlements(_admin: dict = Depends(_require_admin)):
    """Trigger today's settlement run (admin or nightly job)."""
    rows = await _db(db.run_daily_settlements)
    return {"message": f"Settlement computed for {len(rows)} shops.", "settlements": rows}


# ─── Menu change requests (shop → admin approval) ───


@router.get("/menu-change-requests")
async def menu_change_requests(status: str | None = None, _admin: dict = Depends(_require_admin)):
    if status:
        return await _cached_read(10, "menu-change-requests", db.list_menu_change_requests, status)
    return await _cached_read(10, "menu-change-requests", db.list_menu_change_requests)


@router.post("/menu-change-requests")
async def add_menu_change_request(data: LocalMenuChangeCreate, current_user: dict = Depends(get_current_local_user)):
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
async def patch_menu_change_request(req_id: str, data: LocalMenuChangeApprove, _admin: dict = Depends(_require_admin)):
    req = await _db(db.update_menu_change_request, req_id, data.status, data.admin_notes)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    return req


class LocalMenuChangeApprove(BaseModel):
    status: str
    admin_notes: str = ""


# ─── Misc ───


@router.get("/audit-logs")
async def audit_logs(limit: int = 200, _admin: dict = Depends(_require_admin)):
    return await _db(db.list_audit_logs, limit)


@router.get("/whatsapp-logs")
async def whatsapp_logs(limit: int = 100, _admin: dict = Depends(_require_admin)):
    return await _db(db.list_whatsapp_logs, limit)
