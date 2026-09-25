"""
Combo products + the admin-written student info banner.

Two features are pinned here:

1. **Combo products** — ONE menu row, ONE price, MANY items (name + combo price
   + free-text item list). Whatever path creates or edits the row (vendor app,
   admin portal, raw store), a combo ALWAYS ends up in the "Combo" category with
   ``is_combo`` set, so the student menu groups and badges every combo the same
   way — and a plain product is never silently turned into a combo.

2. **Student info banner** — the green block on the student home page. It is
   written by an admin, readable by anyone (the home page paints before/without a
   login), and a blank message can never go live.
"""
import uuid

from app.core.security import hash_password
from app.core.store import store as db

_RUN = uuid.uuid4().hex[:6]


def _u(base: str) -> str:
    return f"{base}_{_RUN}"


def _blank_text() -> str:
    """Whitespace-only message — what an admin saves when they clear the box."""
    return "   \n  "


async def _admin_headers(client) -> dict:
    """Create a real admin row server-side (public registration refuses
    role=admin) and log in through the API."""
    username = _u("combo_admin")
    db.register_user(
        username=username,
        password_hash=hash_password("admin_pass_123"),
        name="Combo Admin",
        role="admin",
        email="",
        phone="",
    )
    res = await client.post("/api/v1/admin/login", json={"username": username, "password": "admin_pass_123"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _vendor_shop_and_headers(client):
    """Register a shopkeeper through the vendor API, approve + open the shop,
    then log in. Returns (shop, auth headers)."""
    username = _u("combovendor")
    res = await client.post("/api/v1/vendor/register", json={
        "username": username,
        "email": f"{username}@example.com",
        "password": "password123",
        "name": "Combo Vendor",
        "phone": "9700000001",
        "shop_name": f"{username}'s Kitchen",
        "shop_category": "Food",
        "shop_description": "Combo test shop",
        "upi_id": f"{username}@upi",
    })
    assert res.status_code == 201, res.text
    shop = db.get_shop_by_shopkeeper_email(f"{username}@example.com")
    assert shop, "vendor registration must auto-create the shop"
    db.update_shop(shop["id"], {"approval_status": "Approved", "present": True, "status": "Open"})
    login = await client.post("/api/v1/vendor/login", json={"username": username, "password": "password123"})
    assert login.status_code == 200, login.text
    return shop, {"Authorization": f"Bearer {login.json()['access_token']}"}


def _shop(name: str, phone: str):
    return db.create_shop({
        "name": f"{name} {_RUN}",
        "category": "Food",
        "description": "combo test shop",
        "shopkeeper_email": f"{name.lower().replace(' ', '_')}_{_RUN}@example.com",
        "shopkeeper_name": name,
        "phone": phone,
    })


# ─── Combo products ───


def test_store_forces_combo_category_and_keeps_the_item_list():
    """Raw store path: one price, many items, always under "Combo"."""
    shop = _shop("Combo Store", "9700000002")
    product = db.create_product({
        "shop_id": shop["id"],
        "name": "Full Meal Combo",
        "description": "Biryani + burger + drink",
        "price": 199,
        "category": "Food",      # must be overridden
        "inventory": 10,
        "prep_time": 10,
        "available": True,
        "is_combo": True,
        "combo_items": "Chicken Biryani\n1 Burger\n1 Soft Drink",
    })
    assert product["category"] == "Combo"
    assert bool(product["is_combo"]) is True
    assert "Chicken Biryani" in product["combo_items"]
    # The combo carries exactly ONE price — never a per-item breakdown.
    assert product["price"] == 199


def test_store_keeps_a_plain_product_plain():
    shop = _shop("Plain Store", "9700000003")
    product = db.create_product({
        "shop_id": shop["id"], "name": "Dosa", "description": "", "price": 60,
        "category": "Food", "inventory": 5, "prep_time": 10, "available": True,
    })
    assert product["category"] == "Food"
    assert not bool(product["is_combo"])
    assert (product["combo_items"] or "") == ""


def test_updating_a_product_into_a_combo_moves_it_to_the_combo_category():
    shop = _shop("Toggle Store", "9700000004")
    product = db.create_product({
        "shop_id": shop["id"], "name": "Meal", "description": "", "price": 120,
        "category": "Food", "inventory": 5, "prep_time": 10, "available": True,
    })
    updated = db.update_product(product["id"], {"is_combo": True, "combo_items": "Biryani, Coke"})
    assert updated["category"] == "Combo"
    assert bool(updated["is_combo"]) is True
    assert updated["combo_items"] == "Biryani, Coke"

    # Turning the combo back off with an explicit category returns it to the
    # normal menu instead of stranding it under "Combo".
    back = db.update_product(product["id"], {"is_combo": False, "category": "Food", "combo_items": ""})
    assert back["category"] == "Food"
    assert not bool(back["is_combo"])


async def test_vendor_can_add_a_combo_and_students_see_it_flagged(client):
    shop, headers = await _vendor_shop_and_headers(client)

    res = await client.post("/api/v1/vendor/products", headers=headers, json={
        "name": "Vendor Combo",
        "description": "Biryani + fast food",
        "price": 149,
        "category": "Beverages",   # ignored: combos are always category "Combo"
        "inventory": 10,
        "prep_time": 10,
        "available": True,
        "is_combo": True,
        "combo_items": "Chicken Biryani\n1 Fast Food item\n1 Soft Drink",
    })
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["category"] == "Combo"
    assert bool(body["is_combo"]) is True
    assert "Chicken Biryani" in body["combo_items"]

    # The student-facing product feed carries the flag + item list, which is
    # what the student app uses to render the badge and the bullets.
    feed = await client.get("/api/v1/local/products", params={"shop_id": shop["id"]})
    assert feed.status_code == 200, feed.text
    row = next(p for p in feed.json() if p["id"] == body["id"])
    assert row["category"] == "Combo"
    assert bool(row["is_combo"]) is True
    assert row["combo_items"].splitlines()[0] == "Chicken Biryani"


async def test_admin_can_add_a_combo_through_the_local_products_endpoint(client):
    headers = await _admin_headers(client)
    shop = _shop("Admin Combo Shop", "9700000005")
    res = await client.post("/api/v1/local/products", headers=headers, json={
        "shop_id": shop["id"],
        "name": "Admin Combo",
        "description": "",
        "price": 249,
        "category": "Food",       # must be overridden to Combo server-side
        "inventory": 10,
        "prep_time": 10,
        "available": True,
        "is_combo": True,
        "combo_items": "Biryani\nKebab\nCoke",
    })
    assert res.status_code == 200, res.text
    assert res.json()["category"] == "Combo"
    assert bool(res.json()["is_combo"]) is True


# ─── Student info banner ───


async def test_student_notice_is_off_and_empty_by_default(client):
    res = await client.get("/api/v1/local/student-notice")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["enabled"] is False
    assert body["text"] == ""


async def test_only_an_admin_can_write_the_student_notice(client):
    text = f"Food court closes at 9 PM ({_RUN})"

    # Anonymous caller → rejected.
    anon = await client.patch("/api/v1/local/student-notice", json={"enabled": True, "text": text})
    assert anon.status_code == 401

    # A signed-in STUDENT is still not an admin → forbidden, and nothing saved.
    student_username = _u("notice_student")
    reg = await client.post("/api/v1/local/auth/register", json={
        "username": student_username, "password": "password123",
        "name": "Notice Student", "role": "student",
        "email": f"{student_username}@example.com", "phone": "+919876543210",
    })
    assert reg.status_code in (200, 201), reg.text
    login = await client.post("/api/v1/local/auth/login", json={
        "username": student_username, "password": "password123",
    })
    assert login.status_code == 200, login.text
    student_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    denied = await client.patch("/api/v1/local/student-notice", headers=student_headers,
                                json={"enabled": True, "text": text})
    assert denied.status_code == 403
    assert (await client.get("/api/v1/local/student-notice")).json()["enabled"] is False


async def test_admin_can_publish_and_hide_the_student_notice(client):
    headers = await _admin_headers(client)
    text = f"Pre-order before 8:30 PM — the counter closes early ({_RUN})"

    published = await client.patch("/api/v1/local/student-notice", headers=headers,
                                   json={"enabled": True, "text": text})
    assert published.status_code == 200, published.text
    assert published.json() == {"enabled": True, "text": text}

    public = await client.get("/api/v1/local/student-notice")
    assert public.status_code == 200
    assert public.json() == {"enabled": True, "text": text}

    hidden = await client.patch("/api/v1/local/student-notice", headers=headers, json={"enabled": False})
    assert hidden.status_code == 200, hidden.text
    # The text survives a hide — the admin can flip it back on without retyping.
    assert hidden.json() == {"enabled": False, "text": text}


async def test_blank_student_notice_can_never_go_live(client):
    """An empty message would leave a green box with nothing in it on every
    student's home page — the server refuses to report it as enabled."""
    headers = await _admin_headers(client)
    saved = await client.patch("/api/v1/local/student-notice", headers=headers,
                               json={"enabled": True, "text": _blank_text()})
    assert saved.status_code == 200, saved.text
    assert saved.json()["enabled"] is False
    assert saved.json()["text"] == ""
    assert (await client.get("/api/v1/local/student-notice")).json()["enabled"] is False


async def test_student_notice_rejects_an_essay(client):
    """Bound the message so one admin paste can't blow up every student's app."""
    headers = await _admin_headers(client)
    too_long = await client.patch("/api/v1/local/student-notice", headers=headers,
                                  json={"enabled": True, "text": "x" * 501})
    assert too_long.status_code == 422

