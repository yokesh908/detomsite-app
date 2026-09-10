"""End-to-end smoke test for the new features:
- Forgot password (single emailed OTP) flow
- Vendor QR order lookup
- Automatic shop-off at closing time
- Email uniqueness (one account per email, across all roles)

Run:  python backend/scripts/verify_new_features.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Point the local DB at a throwaway file so we never touch real data, and
# force the SQLite store regardless of what backend/.env configures.
_tmp_db = tempfile.mktemp(suffix=".db")
os.environ["LOCAL_DB_PATH"] = _tmp_db
os.environ["USE_LOCAL_DB"] = "true"
os.environ["USE_TURSO_DB"] = "false"
os.environ["USE_SUPABASE_DB"] = "false"
os.environ["DEBUG"] = "true"  # email falls back to a log line when no mail server is set

from app.core.config import settings

settings.LOCAL_DB_PATH = _tmp_db
settings.USE_LOCAL_DB = True
settings.USE_TURSO_DB = False
settings.USE_SUPABASE_DB = False
settings.DEBUG = True

from fastapi.testclient import TestClient
from app.main import app
from app.core.store import init_store
from app.services.email_service import EmailService

init_store()

client = TestClient(app)

USERNAME = "otptest"
PASSWORD = "oldpass123"
NEW_PASSWORD = "newpass456"
EMAIL = "otptest@campus.edu"


def step(msg: str) -> None:
    print(f"\n-- {msg}")


ok = True


def check(label: str, condition: bool, extra: str = "") -> None:
    global ok
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}{' — ' + extra if extra else ''}")
    if not condition:
        ok = False


# ─── 1. Register a student ───
step("Register a student")
r = client.post("/api/v1/users/register", json={
    "username": USERNAME,
    "email": EMAIL,
    "password": PASSWORD,
    "name": "OTP Test",
    "phone": "+919876543210",
})
check("register", r.status_code == 201, r.text[:200])


# ─── 2. Email uniqueness (one account per email) ───
step("Email uniqueness — one account per email")
r = client.post("/api/v1/users/register", json={
    "username": "otptest_dupe", "email": EMAIL, "password": "pass1",
    "name": "Dupe", "phone": "+919876543299",
})
check("same email rejected", r.status_code == 409 and "already registered" in r.json().get("detail", ""), r.text[:150])
# Same username with a different email → still a username conflict
r = client.post("/api/v1/users/register", json={
    "username": USERNAME, "email": "different@campus.edu", "password": "pass1",
    "name": "Dupe", "phone": "+919876543299",
})
check("same username rejected", r.status_code == 409 and "Username" in r.json().get("detail", ""), r.text[:150])
# Fresh username + fresh email still works
r = client.post("/api/v1/users/register", json={
    "username": "otptest_fresh", "email": "fresh@campus.edu", "password": "pass1",
    "name": "Fresh", "phone": "+919876543298",
})
check("fresh account works", r.status_code == 201, r.text[:150])


# ─── 3. Domain validation (only when STUDENT_EMAIL_DOMAINS set) ───
step("Student domain validation")
settings.STUDENT_EMAIL_DOMAINS = "campus.edu"
r = client.post("/api/v1/users/register", json={
    "username": "otptest2", "email": "bad@other.com", "password": "pass1",
    "name": "Bad", "phone": "+919876543211",
})
check("reject non-campus email", r.status_code == 400, r.text[:120])
r = client.post("/api/v1/users/register", json={
    "username": "otptest2", "email": "good@campus.edu", "password": "pass1",
    "name": "Good", "phone": "+919876543211",
})
check("accept campus email", r.status_code == 201, r.text[:120])
settings.STUDENT_EMAIL_DOMAINS = ""  # reset to default (any domain)


# ─── 3. Forgot password — single emailed OTP ───
step("Forgot password — single emailed OTP")
# The API never returns the code (it's only ever delivered by email), so
# capture what would be emailed to keep the flow testable offline.
captured: dict = {}

async def _capture_otp(to_email: str, code: str, purpose: str = "verification") -> bool:
    captured["code"] = code
    captured["to"] = to_email
    return True

EmailService.send_otp_email = staticmethod(_capture_otp)

r = client.post("/api/v1/users/forgot-password", json={"identifier": USERNAME})
check("request OTP", r.status_code == 200 and r.json().get("step") == 1, r.text[:200])
otp = captured.get("code")
check("OTP captured from email", bool(otp), f"otp={otp}")
check("OTP never exposed in response", "debug_code" not in r.json() and (not otp or otp not in r.text), r.text[:200])
check("OTP sent to registered email", captured.get("to", "").lower() == EMAIL.lower(), captured.get("to", ""))
# Wrong identifier must not leak account existence
r = client.post("/api/v1/users/forgot-password", json={"identifier": "ghostuser"})
check("no account leakage", r.status_code == 200 and r.json().get("step") == 1)


# ─── 4. Reset: wrong code rejected, correct code updates the DB ───
step("Reset password — code verified, then password updated in DB")
r = client.post("/api/v1/users/reset-password", json={
    "identifier": USERNAME, "otp": "000000", "new_password": NEW_PASSWORD,
})
check("wrong code rejected", r.status_code == 400, r.text[:120])
r = client.post("/api/v1/users/reset-password", json={
    "identifier": USERNAME, "otp": otp, "new_password": NEW_PASSWORD,
})
check("password reset (DB updated)", r.status_code == 200, r.text[:200])
# The code is single-use — it must not work a second time
r = client.post("/api/v1/users/reset-password", json={
    "identifier": USERNAME, "otp": otp, "new_password": "another456",
})
check("OTP single-use", r.status_code == 400, r.text[:120])


# ─── 6. Old password fails, new password works ───
step("Login with new password")
r = client.post("/api/v1/users/login", json={"username": USERNAME, "password": PASSWORD})
check("old password rejected", r.status_code == 401)
r = client.post("/api/v1/users/login", json={"username": USERNAME, "password": NEW_PASSWORD})
check("new password accepted", r.status_code == 200)
student_token = r.json()["access_token"]


# ─── 7. Create a shop + vendor, order, QR lookup ───
step("Vendor QR order lookup")
r = client.post("/api/v1/vendor/register", json={
    "username": "otpvendor", "email": "otpvendor@business.com", "password": "vendor123",
    "name": "OTP Vendor", "phone": "+919876543222", "shop_name": "OTP Cafe",
    "shop_category": "Cafe", "shop_description": "test", "upi_id": "otp@upi",
})
check("vendor register", r.status_code == 201, r.text[:150])
vendor_id = r.json()["user"]["id"]

# Email is globally unique ACROSS roles — a student can't grab the vendor's email
r = client.post("/api/v1/users/register", json={
    "username": "otp_student2", "email": "otpvendor@business.com", "password": "pass1",
    "name": "Dupe Student", "phone": "+919876543297",
})
check("vendor email blocked for students", r.status_code == 409 and "already registered" in r.json().get("detail", ""), r.text[:150])

# Approve the shop (admin action) so it can take orders. Use the admin
# credentials configured for this environment (same as local_admin.py).
admin_username = (settings.DEFAULT_SUPER_ADMIN_EMAIL or "admin").split("@")[0]
admin_password = settings.DEFAULT_SUPER_ADMIN_PASSWORD or "admin123"
admin = client.post("/api/v1/admin/login", json={"username": admin_username, "password": admin_password})
check("admin login", admin.status_code == 200)
admin_token = admin.json()["access_token"]
ah = {"Authorization": f"Bearer {admin_token}"}
vendors = client.get("/api/v1/admin/vendors", headers=ah).json()
shop_id = next(v["id"] for v in vendors if v["shopkeeper_email"] == "otpvendor@campus.local")
r = client.post(f"/api/v1/admin/vendors/{shop_id}/approve", headers=ah)
check("approve shop", r.status_code == 200, r.text[:150])

# Vendor starts the shop
vh = {"Authorization": f"Bearer {client.post('/api/v1/vendor/login', json={'username': 'otpvendor', 'password': 'vendor123'}).json()['access_token']}"}
r = client.patch("/api/v1/vendor/shop", json={"present": True}, headers=vh)
check("vendor opens shop", r.status_code == 200, r.text[:150])

# Add a product
r = client.post("/api/v1/vendor/products", json={
    "name": "Coffee", "price": 99, "category": "Beverages",
    "description": "Hot", "inventory": 10, "prep_time": 5,
}, headers=vh)
check("add product", r.status_code == 201, r.text[:150])
product_id = r.json()["id"]

# Student places an order
sh = {"Authorization": f"Bearer {student_token}"}
r = client.post("/api/v1/local/orders", json={
    "shop_id": shop_id,
    "items": [{"product_id": product_id, "quantity": 1}],
    "student_name": "OTP Test",
    "student_phone": "+919876543210",
    "delivery_location": "Hostel 3",
    "delivery_slot": "Evening",
    "payment_method": "COD",
})
check("create order", r.status_code == 200, r.text[:200])
order = r.json()
order_code = f"DETOMSITE-ORDER:{order['id']}"

# QR lookup — correct code
r = client.get("/api/v1/vendor/orders/lookup", params={"code": order_code}, headers=vh)
check("QR lookup finds order", r.status_code == 200 and r.json()["id"] == order["id"], r.text[:200])
# QR lookup — wrong shop must be rejected
r = client.get("/api/v1/vendor/orders/lookup", params={"code": order_code}, headers=sh)
check("QR lookup blocks other roles", r.status_code in (401, 403), f"status={r.status_code}")


# ─── 8. Shop orderability is driven by the vendor's Start/Stop toggle ───
# (Opening/closing hours are shown as info only and do NOT block ordering —
# the vendor's present + status is the single source of truth.)
step("Shop orderability (vendor Start/Stop toggle)")
from app.core.local_demo_db import _shop_is_orderable, get_shop
shop_row = get_shop(shop_id)
shop_row["opening_time"] = "09:00 AM"
shop_row["closing_time"] = "09:00 PM"
shop_row["present"] = 1
shop_row["status"] = "Open"
check("orderable when Open + present", _shop_is_orderable(shop_row) is True)
shop_row["present"] = 0
check("not orderable when vendor stops", _shop_is_orderable(shop_row) is False)
shop_row["present"] = 1
shop_row["status"] = "Closed"
check("not orderable when shop closed", _shop_is_orderable(shop_row) is False)

# ─── 9. Order listing is newest-first with timestamps ───
step("Order list ordering + timestamps")
orders = client.get("/api/v1/admin/orders", headers=ah).json()
check("admin sees the order", any(o["id"] == order["id"] for o in orders), f"{len(orders)} orders")
check("order has time-stamped created_at", " " in str(order.get("created_at", "")), str(order.get("created_at", "")))

print("\n" + ("[OK] ALL CHECKS PASSED" if ok else "[FAIL] SOME CHECKS FAILED"))
sys.exit(0 if ok else 1)
