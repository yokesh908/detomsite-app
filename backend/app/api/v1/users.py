"""
User Portal API — Student registration, login, and dashboard
"""
from fastapi import APIRouter, HTTPException, Depends, Header, Request
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import asyncio
import logging
import secrets

from app.core.config import settings
from app.core.store import store as db
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token
from app.services.email_service import EmailService
from app.core.rate_limit import allow as rate_allow, reset as rate_reset, client_ip as rate_ip

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Forgot-password OTP helpers ───


def _allowed_student_domains() -> list[str]:
    """Parse STUDENT_EMAIL_DOMAINS (comma-separated, no @) into lowercase domains."""
    return [d.strip().lower().lstrip("@") for d in settings.STUDENT_EMAIL_DOMAINS.split(",") if d.strip()]


def _validate_student_email(email: str) -> Optional[str]:
    """Return an error message when the student email is not allowed, else None.
    Empty domain list = any valid email accepted (the default)."""
    domains = _allowed_student_domains()
    if not domains:
        return None
    domain = (email or "").strip().lower().split("@")[-1] if "@" in (email or "") else ""
    if domain not in domains:
        return f"Only campus emails from {', '.join('@' + d for d in domains)} are allowed for student accounts."
    return None


def _generate_otp() -> str:
    """A 6-digit numeric code."""
    return f"{secrets.randbelow(1_000_000):06d}"


async def _find_user_for_reset(identifier: str) -> Optional[dict]:
    """Resolve a username OR email to a user record (email preferred when it
    looks like one, since usernames are case-insensitive too)."""
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    user = None
    if "@" in identifier:
        user = await asyncio.to_thread(db.get_user_by_email, identifier)
    if not user:
        user = await asyncio.to_thread(db.get_user_by_username, identifier)
    return user


async def _send_reset_otp(user: dict) -> None:
    """Generate + store a fresh OTP for this user and email it.
    The code is only ever delivered by email — never returned to the client.
    Admin accounts carry a placeholder DB email (admin@detomsite.local) because
    DEFAULT_SUPER_ADMIN_EMAIL is usually already claimed by another role's
    account, so admin reset codes go straight to DEFAULT_SUPER_ADMIN_EMAIL."""
    otp = _generate_otp()
    await asyncio.to_thread(db.create_password_reset, user["username"], otp, 1)
    admin_email = (settings.DEFAULT_SUPER_ADMIN_EMAIL or "").strip()
    to_email = (
        admin_email
        if user.get("role") == "admin" and admin_email
        else (user.get("email") or f"{user['username']}@campus.local")
    )
    await EmailService.send_otp_email(
        to_email,
        otp,
        purpose="password reset",
    )


# ─── Schemas ───

class UserRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., max_length=100)
    password: str = Field(..., min_length=4, max_length=128)
    name: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., max_length=15)
    campus: str = Field(default="", max_length=100)
    default_location: str = Field(default="", max_length=200)


class UserLoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    name: str
    email: str = ""
    phone: str = ""
    role: str
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class DashboardResponse(BaseModel):
    user: UserResponse
    shops: list
    orders: list
    stats: dict


class ReviewCreate(BaseModel):
    shop_id: str
    product_id: str = Field(default="", max_length=100)
    rating: int = Field(..., ge=1, le=5)
    comment: str = Field(default="", max_length=500)


# ─── Helper to get current user ───

async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
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
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="This endpoint is for students only")
    return user


# ─── Endpoints ───

@router.post("/register", status_code=201)
async def register(data: UserRegisterRequest):
    """Register a new student user."""
    # Student accounts may be restricted to college email domains (configurable).
    domain_error = _validate_student_email(data.email)
    if domain_error:
        raise HTTPException(status_code=400, detail=domain_error)

    password_hash = hash_password(data.password)
    user, conflict = db.register_user(
        username=data.username,
        password_hash=password_hash,
        name=data.name,
        email=data.email,
        phone=data.phone,
        role="student",
    )
    if conflict == "username":
        raise HTTPException(status_code=409, detail="Username already taken")
    if conflict == "email" or not user:
        # One email = one account across the whole platform, no matter the role.
        raise HTTPException(status_code=409, detail="This email is already registered. Try signing in instead.")
    # Record registration for admin notification
    try:
        db.record_registration(user)
    except Exception as e:
        logger.warning(f"Could not record registration: {e}")

    return {"message": "Student registered successfully", "user": user}


# ─── Forgot password — single emailed OTP ───
# Step 1: request a reset with your username/email → a 6-digit OTP is emailed.
# Step 2: enter that OTP + your new password → the code is verified and the
# password is updated in the DB.
# The code is sent ONCE and is never shown in the UI or API response.


class ForgotPasswordRequest(BaseModel):
    identifier: str = Field(..., min_length=2, max_length=120, description="Username or registered email")


class ResetPasswordRequest(BaseModel):
    identifier: str = Field(..., min_length=2, max_length=120)
    otp: str = Field(..., min_length=4, max_length=10)
    new_password: str = Field(..., min_length=4, max_length=128)


@router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordRequest):
    """Send the single 6-digit OTP to the account's registered email.
    The response never reveals whether an account exists (account enumeration
    protection) — the code is only ever delivered by email, never shown in
    the UI or returned in the API response."""
    user = await _find_user_for_reset(data.identifier)
    if not user:
        # Same response either way — don't leak which usernames exist.
        return {"message": "If that account exists, a verification code was sent to its email.", "step": 1}

    await _send_reset_otp(user)
    return {
        "message": "A 6-digit code was sent to your registered email. Enter it below to set a new password.",
        "step": 1,
        "expires_minutes": settings.RESET_OTP_EXPIRE_MINUTES,
    }


@router.post("/reset-password")
async def reset_password(data: ResetPasswordRequest):
    """Validate the emailed code and set the new password (updates the DB)."""
    user = await _find_user_for_reset(data.identifier)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid code. Please try again.")

    reset = await asyncio.to_thread(db.get_password_reset, user["username"], data.otp.strip(), 1)
    if not reset:
        # Count the wrong guess — after 5 the code locks out (brute-force guard).
        await asyncio.to_thread(db.bump_password_reset_attempts, user["username"])
        raise HTTPException(status_code=400, detail="Invalid or expired code. Please request a new one.")

    password_hash = hash_password(data.new_password)
    updated = await asyncio.to_thread(db.update_user_password, user["username"], password_hash)
    if not updated:
        raise HTTPException(status_code=500, detail="Could not update the password. Please try again.")

    await asyncio.to_thread(db.invalidate_password_resets, user["username"])
    logger.info(f"Password reset completed for user: {user['username']}")
    return {"message": "Password updated successfully! You can now sign in with your new password."}


# ─── Forgot username — emailed reminder ───
# Like forgot-password: the student/shopkeeper enters their registered email and
# the username is emailed to them. The response never reveals whether an
# account exists (account-enumeration protection).


class ForgotUsernameRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=120, description="The email the account was registered with")


@router.post("/forgot-username")
async def forgot_username(data: ForgotUsernameRequest):
    """Email the account's username to its registered address.

    Works for student AND shopkeeper accounts (one email = one account across
    the whole platform, so at most one username is sent). Admin accounts carry
    a placeholder DB email, so their reminder is routed to
    DEFAULT_SUPER_ADMIN_EMAIL like the password-reset flow."""
    email = (data.email or "").strip()
    user = await asyncio.to_thread(db.get_user_by_email, email) if email else None
    if user:
        admin_email = (settings.DEFAULT_SUPER_ADMIN_EMAIL or "").strip()
        to_email = (
            admin_email
            if user.get("role") == "admin" and admin_email
            else (user.get("email") or email)
        )
        try:
            await EmailService.send_username_reminder(to_email, user.get("username", ""), user.get("role", "student"))
            logger.info(f"Username reminder sent to {to_email}")
        except Exception as e:
            logger.warning(f"Username reminder email failed: {e}")
    # Same response either way — never leak which emails are registered.
    return {"message": "If that email is registered, your username has been sent to it."}


@router.post("/login")
async def login(data: UserLoginRequest, request: Request):
    """Login as a student."""
    # PENTEST FIX: this route had no rate limit at all — an unauthenticated
    # attacker could brute-force student passwords as fast as the network
    # allowed. Same budget as the local portal login.
    ip = rate_ip(request)
    if not rate_allow("login", f"{data.username}:{ip}", max_attempts=40, window_sec=300):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts — please wait a few minutes and try again.")

    user = db.get_user_by_username(data.username)
    # PENTEST FIX: identical message for "no such user" and "wrong password",
    # and the password is checked BEFORE the role hint — otherwise the distinct
    # 401/403 replies let an attacker enumerate which usernames exist.
    bad_credentials = "Invalid username or password."
    if not user or not verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail=bad_credentials)
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail=f"This account is a {user['role']} account — please sign in from the {user['role']} portal instead.")
    rate_reset("login", f"{data.username}:{ip}")

    token_data = {
        "sub": str(user["id"]),
        "username": user["username"],
        "name": user["name"],
        "role": user["role"],
    }
    return AuthResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
        user=UserResponse(
            id=user["id"],
            username=user["username"],
            name=user["name"],
            email=user.get("email", ""),
            phone=user.get("phone", ""),
            role=user["role"],
            created_at=user["created_at"],
        ),
    )


@router.get("/dashboard")
async def dashboard(current_user: dict = Depends(get_current_user)):
    """Get student dashboard with approved shops and orders."""
    shops = db.list_shops(public_only=True)
    all_orders = db.list_orders()
    # Filter orders belonging to this user (by name match for simplicity)
    my_orders = [o for o in all_orders if o.get("student_name", "").lower() == current_user["name"].lower()]
    active_orders = [o for o in my_orders if o["status"] not in ("Completed", "Cancelled")]
    total_spent = sum(o["total"] for o in my_orders)

    return {
        "user": current_user,
        "shops": shops,
        "orders": my_orders,
        "stats": {
            "total_orders": len(my_orders),
            "active_orders": len(active_orders),
            "total_spent": total_spent,
            "shops_open": len(shops),
        },
    }


@router.get("/shops")
async def list_shops():
    """List all approved shops visible to students."""
    shops = db.list_shops(public_only=True)
    return shops


@router.get("/orders")
async def student_orders(current_user: dict = Depends(get_current_user)):
    """Get student's orders."""
    all_orders = db.list_orders()
    my_orders = [o for o in all_orders if o.get("student_name", "").lower() == current_user["name"].lower()]
    return my_orders


@router.post("/reviews")
async def create_review(data: ReviewCreate, current_user: dict = Depends(get_current_user)):
    """Create a review for a shop — saved to the reviews table."""
    review = db.create_review({
        "user_id": current_user["id"],
        "username": current_user["username"],
        "student_name": current_user["name"],
        "shop_id": data.shop_id,
        "rating": data.rating,
        "comment": data.comment,
    })
    if not review:
        raise HTTPException(status_code=400, detail="Could not submit review")
    return {"message": "Review submitted!", "review": review}


@router.get("/reviews")
async def list_reviews(current_user: dict = Depends(get_current_user)):
    """Get reviews by this student."""
    return db.list_reviews_by_user(current_user["id"])


@router.get("/profile")
async def profile(current_user: dict = Depends(get_current_user)):
    """Get current student profile."""
    return current_user


@router.put("/profile")
async def update_profile(data: dict, current_user: dict = Depends(get_current_user)):
    """Update student profile."""
    return {"message": "Profile updated", "user": current_user}
