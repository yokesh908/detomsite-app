"""
Admin Portal API — Admin login with username/password from DB,
approve/reject shops, view all statistics
"""
from fastapi import APIRouter, HTTPException, Depends, Header, Query, Body, Request
from pydantic import BaseModel, Field
from typing import Optional
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.status_values import PaymentStatus, SharePaymentStatus
from app.core.rate_limit import allow as rate_allow, reset as rate_reset, client_ip as rate_ip
from app.core.store import store as db
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token
from app.core import read_cache
from app.services import push_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Async wrapper for blocking DB calls ───
async def _db(fn, *args, **kwargs):
    """Run a blocking store call in a worker thread to avoid stalling the event loop."""
    return await asyncio.to_thread(fn, *args, **kwargs)


# Asia/Kolkata fixed offset (works even without the tzdata package)
_KOLKATA_TZ = timezone(timedelta(hours=5, minutes=30))


def _ist_date(value) -> str:
    """Normalize a DB timestamp (Supabase stores UTC) to an IST date string."""
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


# ─── Admin credentials (hardcoded or from env) ───
# These are used for initial admin login. Once logged in, admin gets a JWT.
# NOTE: no hardcoded fallback — an empty/dev default would silently weaken the
# admin gate. The prod config validator already refuses to boot without
# DEFAULT_SUPER_ADMIN_PASSWORD; dev setups must set it explicitly.
ADMIN_USERNAME = settings.DEFAULT_SUPER_ADMIN_EMAIL.split("@")[0] if settings.DEFAULT_SUPER_ADMIN_EMAIL else "admin"
ADMIN_PASSWORD = settings.DEFAULT_SUPER_ADMIN_PASSWORD


# ─── Schemas ───

class AdminLoginRequest(BaseModel):
    username: str
    password: str


class AdminResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


class VendorItem(BaseModel):
    id: str
    name: str
    category: str
    shopkeeper_name: str
    shopkeeper_email: str
    phone: str
    approval_status: str
    status: str
    orders_today: int
    revenue_today: int
    created_at: str = ""


class ApprovalAction(BaseModel):
    action: str = Field(..., pattern="^(approve|reject)$")
    reason: str = ""


class AdminShopAction(BaseModel):
    action: str = Field(..., pattern="^(suspend|remove|restore)$")
    reason: str = ""


class FeedbackStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(Open|In Review|Fixed|Won't Fix)$")


class AdminShopSettingsUpdate(BaseModel):
    upi_id: str | None = None
    upi_enabled: bool | None = None
    cod_enabled: bool | None = None
    phone: str | None = None


class AdminProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    price: int = Field(..., ge=1)
    category: str = Field(..., max_length=50)
    inventory: int = 0
    prep_time: int = 10
    available: bool = True
    # Combo: ONE price for MANY items — combo_items holds the item list text.
    is_combo: bool = False
    combo_items: str = ""


class AdminProductUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price: int | None = None
    category: str | None = None
    inventory: int | None = None
    prep_time: int | None = None
    available: bool | None = None
    is_combo: bool | None = None
    combo_items: str | None = None


# ─── Helper ───

async def verify_admin(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid authorization scheme")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    role = payload.get("role")
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    # Re-verify against the database (not just the token claim) so a removed or
    # downgraded admin loses access immediately instead of keeping it until the
    # token expires. The DEBUG-only dev fallback admin ("sub": "0") is exempt.
    if not settings.DEBUG:
        try:
            user_id = int(payload.get("sub"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=403, detail="Admin access required")
        user = await _db(db.get_user_by_id, user_id)
        if not user or user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")
    return payload


# ─── Endpoints ───

@router.post("/login")
async def login(data: AdminLoginRequest, request: Request):
    """Login as admin using username and password."""
    ip = rate_ip(request)
    if not rate_allow("admin_login", f"{data.username}:{ip}", max_attempts=6, window_sec=300):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts — please wait a few minutes and try again.")

    # Try DB first — the ONLY production path. The environment-credential
    # fallback below is dev-only (DEBUG=True) so a misconfigured production
    # deployment can never be silently administered by an anonymous virtual
    # account.
    user = await _db(db.get_user_by_username, data.username)

    # PENTEST FIX: identical message whether the admin username exists or
    # not — "incorrect password" vs "unknown user" would let an attacker
    # enumerate admin accounts on this dedicated endpoint. A dummy hash also
    # runs bcrypt for unknown usernames, so timing matches too.
    bad_admin = "Invalid admin username or password"
    if user and user["role"] == "admin":
        if not verify_password(data.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail=bad_admin)
    else:
        dummy = await asyncio.to_thread(hash_password, "x" * 16)
        await asyncio.to_thread(verify_password, data.password, dummy)
        if not settings.DEBUG:
            raise HTTPException(status_code=401, detail=bad_admin)
        # Dev-only fallback to environment-configured admin credentials.
        if data.username != ADMIN_USERNAME or data.password != ADMIN_PASSWORD:
            raise HTTPException(status_code=401, detail=bad_admin)
        rate_reset("admin_login", f"{data.username}:{ip}")
        # Return a virtual admin user
        token_data = {
            "sub": "0",
            "username": ADMIN_USERNAME,
            "name": "Administrator",
            "role": "admin",
        }
        return AdminResponse(
            access_token=create_access_token(token_data),
            refresh_token=create_refresh_token(token_data),
            user={
                "id": 0,
                "username": ADMIN_USERNAME,
                "name": "Administrator",
                "role": "admin",
            },
        )

    # DB admin login success
    rate_reset("admin_login", f"{data.username}:{ip}")
    token_data = {
        "sub": str(user["id"]),
        "username": user["username"],
        "name": user["name"],
        "role": user["role"],
    }
    return AdminResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
        user={
            "id": user["id"],
            "username": user["username"],
            "name": user["name"],
            "role": user["role"],
        },
    )


@router.get("/dashboard")
async def dashboard(admin: dict = Depends(verify_admin)):
    """Get admin dashboard statistics."""
    today_key = datetime.now(_KOLKATA_TZ).strftime("%Y-%m-%d")
    # Stats + recent orders run CONCURRENTLY — the old sequential awaits made
    # every dashboard poll pay the full DB latency twice over.
    stats, recent_orders = await asyncio.gather(
        _db(db.get_admin_dashboard_stats, today_key),
        _db(db.list_orders, limit=10),
    )

    total_revenue = stats.get("total_revenue", 0)
    total_service_fee = stats.get("total_orders", 0) * 10  # flat ₹10 per order
    today_revenue = stats.get("today_revenue", 0)

    return {
        "stats": {
            "total_shops": stats.get("total_shops", 0),
            "approved_shops": stats.get("approved_shops", 0),
            "pending_approvals": stats.get("pending_approvals", 0),
            "total_orders": stats.get("total_orders", 0),
            "active_orders": stats.get("active_orders", 0),
            "total_revenue": total_revenue,
            "total_service_fee": total_service_fee,
            "vendor_share": max(0, total_revenue - total_service_fee),
            "today_orders": stats.get("today_orders", 0),
            "today_revenue": today_revenue,
            "today_service_fee": stats.get("today_orders", 0) * 10,
            "pending_payments": stats.get("pending_payments", 0),
            "total_products": stats.get("total_products", 0),
        },
        "recent_orders": recent_orders,
    }


@router.get("/vendors")
async def list_vendors(admin: dict = Depends(verify_admin)):
    """List all vendors/shops with approval status."""
    shops = await _db(db.list_shops)

    result = []
    for shop in shops:
        result.append({
            "id": shop["id"],
            "name": shop["name"],
            "category": shop["category"],
            "shopkeeper_name": shop["shopkeeper_name"],
            "shopkeeper_email": shop["shopkeeper_email"],
            "phone": shop["phone"],
            "upi_id": shop.get("upi_id", "") or "",
            "upi_enabled": bool(shop.get("upi_enabled", 0)),
            "cod_enabled": bool(shop.get("cod_enabled", 0)),
            "approval_status": shop["approval_status"],
            "status": shop["status"],
            "present": shop["present"],
            "orders_today": shop["orders_today"],
            "revenue_today": shop["revenue_today"],
        })

    return result


@router.get("/vendors/pending")
async def list_pending_vendors(admin: dict = Depends(verify_admin)):
    """List only vendors pending approval."""
    shops = await _db(db.list_shops)
    pending = [s for s in shops if s["approval_status"] == "Pending Approval"]
    return pending


@router.post("/vendors/{shop_id}/approve")
async def approve_vendor(shop_id: str, admin: dict = Depends(verify_admin)):
    """Approve a vendor/shop."""
    shop = await _db(db.update_shop, shop_id, {"approval_status": "Approved"})
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    logger.info(f"Admin approved shop: {shop['name']} ({shop_id})")
    return {"message": f"Shop '{shop['name']}' approved", "shop": shop}


@router.post("/vendors/{shop_id}/reject")
async def reject_vendor(shop_id: str, data: ApprovalAction, admin: dict = Depends(verify_admin)):
    """Reject a vendor/shop."""
    shop = await _db(db.update_shop, shop_id, {"approval_status": "Rejected"})
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    logger.info(f"Admin rejected shop: {shop['name']} ({shop_id}). Reason: {data.reason}")
    return {"message": f"Shop '{shop['name']}' rejected", "shop": shop}


@router.post("/vendors/{shop_id}/admin-action")
async def admin_shop_action(shop_id: str, data: AdminShopAction, admin: dict = Depends(verify_admin)):
    """Suspend or remove a shop from the platform."""
    if data.action == "suspend":
        shop = await _db(db.suspend_shop, shop_id)
        message = "suspended"
    elif data.action == "remove":
        shop = await _db(db.remove_shop, shop_id)
        message = "removed"
    else:
        shop = await _db(db.update_shop, shop_id, {"approval_status": "Approved", "present": False, "status": "Closed", "is_removed": False})
        message = "restored"

    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    logger.info(f"Admin {message} shop: {shop['name']} ({shop_id}). Reason: {data.reason}")
    return {"message": f"Shop '{shop['name']}' {message}", "shop": shop}


class ShopPresentToggle(BaseModel):
    present: bool


@router.patch("/vendors/{shop_id}/present")
async def toggle_shop_present(shop_id: str, data: ShopPresentToggle, admin: dict = Depends(verify_admin)):
    """Toggle a shop's present/absent status."""
    shop = await _db(db.update_shop, shop_id, {"present": data.present})
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    logger.info(f"Admin set shop {shop['name']} ({shop_id}) present={data.present}")
    return {"message": f"Shop '{shop['name']}' is now {'present' if data.present else 'absent'}", "shop": shop}


@router.get("/vendors/{shop_id}/orders/today")
async def shop_today_orders(shop_id: str, admin: dict = Depends(verify_admin)):
    """Get today's orders for a specific shop."""
    shop = await _db(db.get_shop, shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    today_key = datetime.now(_KOLKATA_TZ).strftime("%Y-%m-%d")
    all_orders = await _db(db.list_orders, limit=5000)
    today_orders = []
    for o in all_orders:
        if o.get("shop_id") == shop_id:
            o_date = _ist_date(o.get("created_at"))
            if o_date == today_key:
                today_orders.append(o)
    for sub in (await _db(db.get_shop_sub_orders, shop_id)) or []:
        if _ist_date(sub.get("created_at")) == today_key:
            today_orders.append(_sub_order_shape(sub))
    today_orders.sort(key=lambda o: str(o.get("created_at") or ""), reverse=True)
    return {"shop": shop, "date": today_key, "orders": today_orders, "count": len(today_orders)}


@router.get("/orders")
async def list_all_orders(admin: dict = Depends(verify_admin)):
    """List orders across all shops, newest first — capped at 1500.
    Multi-shop sub-orders are merged in so they show in the admin centre too.

    Both sources are fetched CONCURRENTLY and the merged list is served from the
    shared read cache (memory → Redis → Postgres, 10 s), so the admin centre's
    polling is answered without re-running the queries. The old version fetched
    every shop and then called ``get_shop_sub_orders`` once per shop (3
    sequential queries per shop), which is what made the admin orders page feel
    slow."""
    return await read_cache.cached_read(10, "admin-orders", _load_admin_orders_capped)


async def _load_admin_orders_capped() -> list[dict]:
    """Newest 1500 orders — the admin centre never renders more than this."""
    merged = await _load_admin_orders()
    return merged[:1500]


async def _load_admin_orders() -> list[dict]:
    """Latest single orders + multi-shop sub-orders, fetched concurrently."""
    sub_fn = getattr(db, "list_all_sub_orders", None)

    async def _subs() -> list[dict]:
        if sub_fn is not None:
            # Supabase store: one batched query for every shop's sub-orders.
            return await _db(sub_fn, 300) or []
        # Fallback (throwaway test store): keep the per-shop loop.
        shops = await _db(db.list_shops) or []
        merged: list[dict] = []
        for shop in shops:
            merged.extend((await _db(db.get_shop_sub_orders, shop["id"])) or [])
        return merged

    orders, subs = await asyncio.gather(
        _db(db.list_orders, limit=1000),
        _subs(),
    )
    merged = list(orders or [])
    for sub in subs or []:
        merged.append(_sub_order_shape(sub))
    merged.sort(key=lambda o: str(o.get("created_at") or ""), reverse=True)
    return merged


def _sub_order_shape(sub: dict) -> dict:
    """Render a multi-shop sub-order as an order-shaped dict for admin views."""
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


async def _rebuild_wa_link(log: dict, sub_id: str) -> str:
    """Rebuild the ``wa.me`` deep-link for a persisted WhatsApp log when the
    store's table does not keep the url column (Supabase)."""
    from urllib.parse import quote
    number = str(log.get("phone") or "").strip()
    if not number:
        return ""
    digits = "".join(ch for ch in number if ch.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    text = str(log.get("message") or "").strip()
    if not text:
        order = await _db(db.get_order, sub_id) if sub_id else None
        if order:
            from app.services.sms_service import compose_order_wa
            text = compose_order_wa(order)
    if not text:
        return ""
    return f"https://wa.me/{digits}?text={quote(text)}"


@router.get("/whatsapp-pending")
async def whatsapp_pending(admin: dict = Depends(verify_admin)):
    """Pending WhatsApp notifications — orders whose ``wa.me`` message to the
    shop is generated and waiting for the admin to send from their number.

    Each item carries the pre-built link, the target number, and the message
    preview, so the admin centre can one-tap send (and bulk-send all).
    """
    logs = await _db(db.list_whatsapp_logs, limit=200)
    pending = [l for l in (logs or []) if str(l.get("status") or "").lower() != "sent"]
    enriched = []
    for log in pending:
        sub_id = log.get("order_id") or log.get("sub_order_id") or ""
        order = await _db(db.get_order, sub_id)
        if not order:
            order = await _db(db.get_sub_order, sub_id) if hasattr(db, "get_sub_order") else None
        shop = await _db(db.get_shop, (order or {}).get("shop_id") or "") if order else None
        doc = dict(log)
        doc["sub_order_id"] = sub_id
        # The Supabase table has no url column — rebuild the same wa.me link
        # that generated this log so the admin centre can one-tap send.
        if not (doc.get("url") or "").strip():
            doc["url"] = await _rebuild_wa_link(doc, sub_id)
        doc["order_token"] = (order or {}).get("token") or (order or {}).get("id")
        doc["student_name"] = (order or {}).get("student_name") or (order or {}).get("parent", {}).get("student_name")
        doc["total"] = (order or {}).get("total") or (order or {}).get("subtotal")
        doc["shop_name"] = (shop or {}).get("name") or (order or {}).get("shop_name")
        enriched.append(doc)
    return enriched


@router.post("/whatsapp/{whatsapp_id}/mark-sent")
async def whatsapp_mark_sent(whatsapp_id: str, admin: dict = Depends(verify_admin)):
    """Mark a WhatsApp notification as sent (after the admin tapped the link)."""
    doc = await _db(db.mark_whatsapp_sent, whatsapp_id)
    if not doc:
        raise HTTPException(status_code=404, detail="WhatsApp notification not found")
    return doc


@router.get("/orders/{order_id}/whatsapp-link")
async def order_whatsapp_link(order_id: str, admin: dict = Depends(verify_admin)):
    """Free WhatsApp notify: pre-filled ``wa.me`` chat to the shop.

    Opens WhatsApp on the admin's own phone with the order message ready to
    send to the shopkeeper's WhatsApp number — the shopkeeper sees the message
    coming FROM the admin's number. No gateway, no cost. Returns the wa.me URL
    plus the target number so the UI can show a small preview.
    """
    from urllib.parse import quote
    from app.services.sms_service import compose_order_wa

    order = await _db(db.get_order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    shop = await _db(db.get_shop, order.get("shop_id") or "")
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    number = str(shop.get("whatsapp_number") or "").strip() or str(shop.get("phone") or "").strip()
    if not number:
        raise HTTPException(status_code=400, detail="Shop has no phone / WhatsApp number on file")

    digits = "".join(ch for ch in number if ch.isdigit())
    if len(digits) == 10:
        digits = "91" + digits  # India default — admin number is Indian per the SMS flow.
    text = compose_order_wa(order)
    url = f"https://wa.me/{digits}?text={quote(text)}"
    return {"shop_id": shop["id"], "shop_name": shop["name"], "number": number,
            "message": text, "url": url}


@router.get("/orders/date")
async def list_orders_by_date(admin: dict = Depends(verify_admin), date: str = Query(..., description="YYYY-MM-DD")):
    """Get orders for a specific date."""
    return await _db(db.get_orders_by_date, date)


@router.get("/payments/date")
async def list_payments_by_date(admin: dict = Depends(verify_admin), date: str = Query(..., description="YYYY-MM-DD")):
    """Get payments for a specific date."""
    return await _db(db.get_payments_by_date, date)


@router.get("/users")
async def list_all_users(admin: dict = Depends(verify_admin)):
    """List all registered users."""
    return await _db(db.list_users)


@router.get("/users/students")
async def list_students(admin: dict = Depends(verify_admin)):
    """List all registered students."""
    return await _db(db.list_users_by_role, "student")


@router.get("/users/shopkeepers")
async def list_shopkeepers(admin: dict = Depends(verify_admin)):
    """List all registered shopkeepers."""
    return await _db(db.list_users_by_role, "shopkeeper")


@router.get("/registrations")
async def list_user_registrations(admin: dict = Depends(verify_admin)):
    """List all user registrations."""
    return await _db(db.list_registrations)


@router.get("/orders/daily")
async def daily_orders(admin: dict = Depends(verify_admin)):
    """Get orders grouped by date."""
    return await _db(db.get_orders_grouped_by_date)


@router.get("/stats")
async def stats(admin: dict = Depends(verify_admin)):
    """Get daily stats."""
    return await _db(db.get_daily_stats)


@router.get("/vendors/{shop_id}/products")
async def vendor_products(shop_id: str, admin: dict = Depends(verify_admin)):
    """Get products for a specific vendor shop."""
    return await _db(db.list_products, shop_id)


@router.patch("/vendors/{shop_id}/settings")
async def update_shop_settings(shop_id: str, data: AdminShopSettingsUpdate, admin: dict = Depends(verify_admin)):
    """Admin can update a shop's UPI ID, UPI enabled, and COD enabled settings."""
    shop = await _db(db.get_shop, shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No settings to update")
    updated = await _db(db.update_shop, shop_id, updates)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update shop")
    logger.info(f"Admin updated shop {shop['name']} ({shop_id}) settings: {updates}")
    return {"message": f"Shop '{shop['name']}' settings updated", "shop": updated}


@router.post("/vendors/{shop_id}/products")
async def admin_add_product(shop_id: str, data: AdminProductCreate, admin: dict = Depends(verify_admin)):
    """Admin can add a product to any shop."""
    shop = await _db(db.get_shop, shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    if shop["approval_status"] != "Approved":
        raise HTTPException(status_code=400, detail="Shop is not approved yet")
    try:
        product = await _db(db.create_product, {
            "shop_id": shop_id,
            "name": data.name,
            "description": data.description,
            "price": data.price,
            "category": "Combo" if data.is_combo else data.category,
            "inventory": data.inventory,
            "prep_time": data.prep_time,
            "available": data.available,
            "is_combo": data.is_combo,
            "combo_items": data.combo_items,
        })
    except Exception as e:
        logger.error(f"Admin product creation failed for shop {shop_id}: {e}")
        raise HTTPException(status_code=400, detail="Could not add product")
    if not product:
        raise HTTPException(status_code=400, detail="Could not add product")
    logger.info(f"Admin added product '{data.name}' to shop {shop['name']}")
    return product


@router.patch("/vendors/{shop_id}/products/{product_id}")
async def admin_update_product(shop_id: str, product_id: str, data: AdminProductUpdate, admin: dict = Depends(verify_admin)):
    """Admin can update a product in any shop."""
    product = await _db(db.get_product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product["shop_id"] != shop_id:
        raise HTTPException(status_code=400, detail="Product does not belong to this shop")
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    updated = await _db(db.update_product, product_id, updates)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update product")
    logger.info(f"Admin updated product '{product['name']}' in shop {shop_id}: {updates}")
    return updated


@router.delete("/vendors/{shop_id}/products/{product_id}")
async def admin_delete_product(shop_id: str, product_id: str, admin: dict = Depends(verify_admin)):
    """Admin can delete a product from any shop."""
    product = await _db(db.get_product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product["shop_id"] != shop_id:
        raise HTTPException(status_code=400, detail="Product does not belong to this shop")
    deleted = await _db(db.delete_product, product_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Could not delete product")
    logger.info(f"Admin deleted product '{product['name']}' from shop {shop_id}")
    return {"message": "Product deleted", "product": product}


@router.get("/vendors/{shop_id}/logs")
async def vendor_logs(shop_id: str, admin: dict = Depends(verify_admin)):
    """Get a vendor's daily earning logs."""
    shop = await _db(db.get_shop, shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    daily = await _db(db.get_vendor_daily_logs, shop_id)
    orders = await _db(db.get_vendor_orders, shop_id)
    return {
        "shop": shop,
        "daily": daily,
        "orders": orders,
        "summary": {
            "total_revenue": sum(o["total"] for o in orders),
            "total_orders": len(orders),
            "total_admin_fee": sum((d.get("count") or 0) * 10 for d in daily),
        },
    }


@router.get("/notifications")
async def admin_notifications(admin: dict = Depends(verify_admin)):
    """Get notifications targeted at admins."""
    return await read_cache.cached_read(
        10, "admin-notifications", db.list_notifications, role="admin"
    )


class BroadcastRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    message: str = Field(..., min_length=1, max_length=2000)


@router.post("/notifications/broadcast")
async def broadcast_notification(data: BroadcastRequest, admin: dict = Depends(verify_admin)):
    """Admin writes a notification that surfaces in every student's notification
    bar (the bell + customer dashboard). The notification is stored with
    ``target_role="student"`` so vendor/admin alerts never mix it up; students
    read it through ``/local/notifications``."""
    title = data.title.strip()
    message = data.message.strip()
    if not title or not message:
        raise HTTPException(status_code=400, detail="Title and message are required")
    try:
        notification = await _db(
            db.create_notification,
            title=title,
            message=message,
            order_id=None,
            status="Broadcast",
            target_role="student",
        )
    except Exception as e:
        logger.error(f"Admin broadcast failed: {e}")
        raise HTTPException(status_code=500, detail="Could not save the broadcast")
    if not notification:
        raise HTTPException(status_code=500, detail="Could not save the broadcast")
    # Invalidate every read-cache layer (memory + Redis + Postgres) so the
    # student bell refreshes at once on every instance.
    await read_cache.clear()
    logger.info(f"Admin broadcast: {title!r} to all students")
    return {"message": "Broadcast sent to all students", "notification": notification}


@router.get("/payments")
async def list_all_payments(admin: dict = Depends(verify_admin)):
    """List all payments — single orders from the payments table plus multi-shop
    parent orders (their ONE-bill payment lives on the parent_orders row)."""
    single = await _db(db.list_payments)
    parent = await _db(db.list_parent_payments)
    return single + parent


@router.get("/shares")
async def share_status(admin: dict = Depends(verify_admin)):
    """Live vendor-share monitoring — MONTHLY cycle.

    The share cycle runs per calendar month (Asia/Kolkata): every approved
    vendor's share is a flat ₹10 per order they earned THIS month through the
    app. The counters reset automatically on the 1st of each month because they
    are computed from order timestamps, never stored. Returns every vendor with
    this month's earnings, this month's share (orders × ₹10), and whether it has been
    paid, plus the full share-payment history (Pending / Received) so the
    admin can see exactly how much was expected, done, and pending this month."""
    shops = await _db(db.list_shops)
    orders = await _db(db.list_orders)
    try:
        share_payments = await _db(db.list_share_payments)
    except Exception as e:
        logger.warning(f"Could not list share payments: {e}")
        share_payments = []

    now = datetime.now(_KOLKATA_TZ)
    month_key = now.strftime("%Y-%m")
    month_label = now.strftime("%B %Y")

    def _month_of(value) -> str:
        """Which IST calendar month (YYYY-MM) a DB timestamp belongs to."""
        return _ist_date(value)[:7]

    vendors = []
    for shop in shops:
        if shop["approval_status"] != "Approved":
            continue
        shop_orders = [o for o in orders if o["shop_id"] == shop["id"] and o["status"] not in ("Cancelled", "Failed")]
        month_orders = [o for o in shop_orders if _month_of(o.get("created_at")) == month_key]
        month_revenue = sum(o["total"] for o in month_orders)
        month_fee = len(month_orders) * 10

        my_payments = [p for p in share_payments if p.get("shop_id") == shop["id"]]
        paid_month = any(
            p.get("status") == "Completed"
            and (_month_of(p.get("created_at")) == month_key or _month_of(p.get("paid_at")) == month_key)
            for p in my_payments
        )
        last_paid_at = ""
        for p in my_payments:
            if p.get("status") == "Completed":
                last_paid_at = str(p.get("paid_at", "") or p.get("created_at", ""))

        vendors.append({
            "shop_id": shop["id"],
            "shop_name": shop["name"],
            "shopkeeper_name": shop.get("shopkeeper_name", ""),
            "upi_id": shop.get("upi_id", ""),
            "month_orders": len(month_orders),
            "month_revenue": month_revenue,
            "month_fee": month_fee,
            "paid_month": paid_month,
            "last_paid_at": last_paid_at,
        })

    # This month's money: what was expected, what actually landed, what's left.
    collected_month = sum(
        p["amount"]
        for p in share_payments
        if p.get("status") == "Completed"
        and (_month_of(p.get("created_at")) == month_key or _month_of(p.get("paid_at")) == month_key)
    )
    expected_month = sum(v["month_fee"] for v in vendors)
    month_pending_payments = [p for p in share_payments if p.get("status") == "Pending" and _month_of(p.get("created_at")) == month_key]
    collected_total = sum(p["amount"] for p in share_payments if p.get("status") == "Completed")
    pending_total = sum(p["amount"] for p in share_payments if p.get("status") == "Pending")
    return {
        "vendors": vendors,
        "payments": share_payments,
        "month": month_key,
        "month_label": month_label,
        "summary": {
            "month": month_key,
            "month_label": month_label,
            "expected_month": expected_month,
            "collected_month": collected_month,
            "pending_month": max(0, expected_month - collected_month),
            "pending_month_count": len(month_pending_payments),
            "collected_total": collected_total,
            "pending_total": pending_total,
            "vendors_count": len(vendors),
            "paid_month_count": sum(1 for v in vendors if v["paid_month"]),
        },
    }


class SharePaymentStatusUpdate(BaseModel):
    """Body of PATCH /shares/{payment_id}.

    PENTEST FIX (finding 12): raw ``dict`` body whose ``status`` was written
    straight to the ₹10-per-order vendor ledger — an arbitrary value there
    silently breaks the "has the admin collected this month's share?" rollup
    (which counts only ``Completed``), and the unbounded string was a free
    DB-write primitive on an admin-authenticated path.
    """
    status: SharePaymentStatus = "Completed"


class PaymentVerifyRequest(BaseModel):
    """Body of PATCH /payments/{payment_id}/verify — see the note on
    ``SharePaymentStatusUpdate`` for why this is not a bare ``dict``."""
    status: PaymentStatus = "Success"


@router.patch("/shares/{payment_id}")
async def update_share_payment(payment_id: str, data: SharePaymentStatusUpdate, admin: dict = Depends(verify_admin)):
    """Mark a vendor share payment as received (Completed) or Rejected."""
    status = data.status
    payment = await _db(db.update_share_payment_status, payment_id, status)
    if not payment:
        raise HTTPException(status_code=404, detail="Share payment not found")
    return {"message": f"Share payment marked {status}", "payment": payment}


@router.patch("/payments/{payment_id}/verify")
async def verify_payment(payment_id: str, data: PaymentVerifyRequest, admin: dict = Depends(verify_admin)):
    """Verify or reject a manual payment.

    When approved, the payment is provably received, so the shopkeeper's
    WhatsApp notification is auto-generated exactly as with the bank-SMS/UTR
    path — the money has been verified either way.
    """
    status = data.status
    payment = await _db(db.get_payment_by_id, payment_id)
    if not payment:
        # Multi-shop parent order — its payment proof is on the parent_orders row.
        payment = await _db(db.verify_parent_payment, payment_id, status)
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")
        if str(status).lower() in ("success", "verified", "received"):
            try:
                parent = await _db(db.get_parent_order, payment_id)
                if parent and parent.get("sub_orders"):
                    for sub in parent["sub_orders"]:
                        shop = await _db(db.get_shop, sub.get("shop_id") or "")
                        wa_number = str((shop or {}).get("whatsapp_number") or "").strip() or str((shop or {}).get("phone") or "").strip()
                        if shop and wa_number:
                            await _notify_shop_whatsapp_verified(_sub_order_shape(sub), shop, wa_number)
            except Exception as e:
                logger.warning(f"Admin verify parent payment — WhatsApp notify error: {e}")
        return {"message": f"Payment {status.lower()}", "payment": payment}
    payment = await _db(db.update_payment_status, payment_id, status)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    if str(status).lower() in ("success", "verified", "received"):
        try:
            # Multi-shop orders pay on the PARENT order id (not in `orders`),
            # so notify each shop involved through its sub-order.
            parent = await _db(db.get_parent_order, payment.get("order_id") or "")
            if parent and parent.get("sub_orders"):
                for sub in parent["sub_orders"]:
                    shop = await _db(db.get_shop, sub.get("shop_id") or "")
                    wa_number = str((shop or {}).get("whatsapp_number") or "").strip() or str((shop or {}).get("phone") or "").strip()
                    if shop and wa_number:
                        await _notify_shop_whatsapp_verified(_sub_order_shape(sub), shop, wa_number)
            else:
                order = await _db(db.get_order, payment.get("order_id") or "")
                if order:
                    shop = await _db(db.get_shop, order.get("shop_id") or "")
                    wa_number = str((shop or {}).get("whatsapp_number") or "").strip() or str((shop or {}).get("phone") or "").strip()
                    if shop and wa_number:
                        await _notify_shop_whatsapp_verified(order, shop, wa_number)
        except Exception as e:
            logger.warning(f"Admin verify payment — WhatsApp notify error: {e}")
    return {"message": f"Payment {status.lower()}", "payment": payment}


async def _notify_shop_whatsapp_verified(order: dict, shop: dict, phone: str) -> None:
    """Fire-and-forget: build the wa.me link for a payment-verified order and
    log it as a Pending WhatsApp notification for the admin centre. Mirror of
    the bank-SMS UTR path in ``local.py``."""
    try:
        from urllib.parse import quote
        from app.services.sms_service import compose_order_wa
        digits = "".join(ch for ch in phone if ch.isdigit())
        if len(digits) == 10:
            digits = "91" + digits
        url = f"https://wa.me/{digits}?text={quote(compose_order_wa(order))}"
        await _db(
            db.log_whatsapp,
            sub_order_id=order["id"],
            phone=phone,
            message=compose_order_wa(order),
            url=url,
            status="Pending",
        )
    except Exception as e:
        logger.warning(f"Admin verify — WhatsApp build error for {order.get('id')}: {e}")


@router.get("/feedback")
async def list_feedback(
    source: Optional[str] = Query(None, pattern="^(User|ATS)?$"),
    admin: dict = Depends(verify_admin),
):
    """All student bug reports / improvement contributions."""
    return await read_cache.cached_read(
        10, "admin-feedback", db.list_site_feedback, source=source or None
    )


@router.patch("/feedback/{feedback_id}")
async def update_feedback(feedback_id: str, data: FeedbackStatusUpdate, admin: dict = Depends(verify_admin)):
    """Move a contribution along: Open → In Review → Fixed / Won't Fix."""
    feedback = await _db(db.update_site_feedback_status, feedback_id, data.status)
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")
    logger.info(f"Admin marked feedback {feedback_id} as {data.status}")
    return feedback


@router.delete("/feedback")
async def delete_feedback(
    source: Optional[str] = Query(None, pattern="^(User|ATS)?$"),
    admin: dict = Depends(verify_admin),
):
    """Permanently delete feedback rows."""
    deleted = await _db(db.delete_site_feedback, source=source or None)
    label = "automated-test entries" if source == "ATS" else "user reports" if source == "User" else "feedback entries"
    logger.info(f"Admin deleted {deleted} {label}")
    return {"message": f"Deleted {deleted} {label}.", "deleted": deleted}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, admin: dict = Depends(verify_admin)):
    """Permanently delete a user."""
    if not await _db(db.delete_user, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    logger.info(f"Admin deleted user {user_id}")
    return {"message": "User deleted — their username and email can now be used again."}


@router.get("/reviews")
async def list_all_reviews(admin: dict = Depends(verify_admin)):
    """All student reviews for shops."""
    return await _db(db.list_reviews)


# ─── Admin push notifications (ring the admin's phone) ───
# Mirror of the vendor app's web-push flow, but for the Admin Centre's own
# devices. Subscriptions are stored in the same push_subscriptions table with
# the sentinel shop_id="admin" — the admin channel is a single global bucket.


class PushSubscriptionKeys(BaseModel):
    p256dh: str = Field(..., min_length=1)
    auth: str = Field(..., min_length=1)


class PushSubscriptionCreate(BaseModel):
    endpoint: str = Field(..., min_length=10)
    keys: PushSubscriptionKeys


@router.get("/push/config")
async def admin_push_config(admin: dict = Depends(verify_admin)):
    """Tell the admin app whether web push is configured and hand it the
    public VAPID key needed to subscribe."""
    keys = push_service.get_vapid_keys()
    if keys:
        return {"enabled": True, "vapid_public_key": keys["public_key"], "reason": ""}
    return {
        "enabled": False,
        "vapid_public_key": "",
        "reason": "VAPID keys are not configured on the server yet.",
    }


@router.post("/push/subscribe")
async def admin_subscribe_push(data: PushSubscriptionCreate, admin: dict = Depends(verify_admin)):
    """Register this device's push subscription so the admin gets phone alerts."""
    endpoint = data.endpoint.strip()
    if not endpoint.startswith("https://"):
        raise HTTPException(status_code=400, detail="Invalid push endpoint")
    try:
        saved = await _db(
            db.save_push_subscription,
            # Sentinel bucket — the admin channel is not tied to any shop.
            "admin",
            endpoint,
            data.keys.p256dh.strip(),
            data.keys.auth.strip(),
        )
    except Exception as e:
        logger.error(f"Could not save admin push subscription: {e}")
        raise HTTPException(status_code=400, detail="Could not save the push subscription")
    if not saved:
        raise HTTPException(status_code=400, detail="Could not save the push subscription")
    return {"ok": True, "message": "Admin notifications enabled 🔔", "subscription": saved}


@router.delete("/push/subscribe")
async def admin_unsubscribe_push(
    admin: dict = Depends(verify_admin),
    endpoint: str = Query(..., min_length=10, description="The push subscription endpoint URL to remove"),
):
    """Remove this device's push subscription. The endpoint is passed as a
    query parameter — DELETE bodies are non-standard and may be stripped."""
    try:
        removed = await _db(db.remove_push_subscription, "admin", endpoint.strip())
    except Exception as e:
        logger.error(f"Could not remove admin push subscription: {e}")
        raise HTTPException(status_code=400, detail="Could not remove the push subscription")
    return {"ok": True, "removed": bool(removed)}


@router.post("/push/test")
async def admin_test_push(admin: dict = Depends(verify_admin)):
    """Send a test push to every subscribed admin device (test button)."""
    return await _db(push_service.send_admin_test_push)
