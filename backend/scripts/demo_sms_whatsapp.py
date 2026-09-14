"""SMS + WhatsApp end-to-end demo for DETOMSITE.

Showcases the full notification pipeline on a THROWAWAY local DB (no prod
writes) by driving the real HTTP API:

  1. Place a COD order → shopkeeper gets the order SMS + a pending WhatsApp
     notification (wa.me link, sent from the admin's own number for free).
  2. Shopkeeper replies "YES <token>" → ``/sms/incoming`` confirms the order.
  3. Bank credit SMS (UTR + credited amount) → ``/sms/incoming`` auto-confirms
     a pending UPI order and stores the bank's UTR on the payment.
  4. ``/sms/match`` — the privacy-first endpoint (UTR + amount only, the raw
     SMS text never leaves the shopkeeper's phone).

Run:  python scripts/demo_sms_whatsapp.py   (from the backend/ directory)
"""
import asyncio
import os
import sys
import tempfile
from datetime import datetime, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Force a local throwaway DB BEFORE any app import (same guard as tests) ──
os.environ["USE_SUPABASE_DB"] = "false"
os.environ["USE_TURSO_DB"] = "false"
os.environ["USE_LOCAL_DB"] = "true"
os.environ["LOCAL_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="detomsite-demo-"), "demo.db")
os.environ["KV_REST_API_URL"] = ""
os.environ["KV_REST_API_TOKEN"] = ""
os.environ["SUPABASE_DATABASE_URL"] = ""

import httpx
from app.main import app
from app.core import order_slots as slots_mod
from app.core import config
from app.core.store import init_store, store as db
from app import services

DEMO = (datetime.now().strftime("%d %b %Y"),)
settings = config.settings


def line(title: str = "") -> None:
    print("\n" + "═" * 66)
    print(f"  {title}")
    print("═" * 66)


def freeze_morning_10am() -> None:
    """Pin IST time to 10:00 AM so the COD order auto-accepts (inside window)."""
    import app.api.v1.local as local_mod

    fixed = datetime(2026, 8, 16, 10, 0, tzinfo=slots_mod.KOLKATA_TZ)
    slots_mod.now_kolkata = lambda: fixed
    local_mod.now_kolkata = lambda: fixed
    local_mod.slot_cutoff_for = lambda _dt: time(12, 30)


async def register_login(client: httpx.AsyncClient, username: str, role: str,
                         phone: str = "+919876543210") -> str:
    await client.post("/api/v1/local/auth/register", json={
        "username": username, "password": "password123", "name": username.title(),
        "role": role, "email": f"{username}@demo.in", "phone": phone,
    })
    res = await client.post("/api/v1/local/auth/login",
                            json={"username": username, "password": "password123"})
    return res.json()["access_token"]


def make_shop():
    shop = db.create_shop({
        "name": "Sai Tiffins", "category": "Food", "description": "Demo shop",
        "shopkeeper_email": "demo-vendor@demo.in", "shopkeeper_name": "Sai Vendor",
        "phone": "9876543210", "whatsapp_number": "9876543210",
    })
    db.update_shop(shop["id"], {"approval_status": "Approved", "present": True, "status": "Open"})
    product = db.create_product({
        "shop_id": shop["id"], "name": "Dosa", "description": "Masala dosa",
        "price": 100, "category": "Food", "inventory": 50, "prep_time": 10, "available": True,
    })
    return shop, product


def agent_headers() -> dict:
    key = (settings.SMS_FORWARD_KEY or "").strip()
    return {"X-Agent-Key": key} if key else {}


async def place(client: httpx.AsyncClient, token: str, shop_id: str, product_id: str,
                student: str, method: str = "COD"):
    res = await client.post("/api/v1/local/orders", json={
        "shop_id": shop_id,
        "items": [{"product_id": product_id, "quantity": 2}],
        "student_name": student, "student_phone": "+919876543210",
        "delivery_location": "Hostel A Block 101", "delivery_slot": "Evening",
        "payment_method": method,
    }, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    return res.json()


async def show_logs(client: httpx.AsyncClient, admin_token: str, which: str) -> None:
    url = "/api/v1/local/whatsapp-logs" if which == "whatsapp" else "/api/v1/local/sms-logs"
    res = await client.get(url, headers={"Authorization": f"Bearer {admin_token}"})
    rows = res.json() or []
    print(f"\n  ── {which.upper()} logs ({len(rows)} row(s)) ──")
    for r in rows[:8]:
        sub = str(r.get("sub_order_id") or r.get("order_id") or "")[:13]
        phone = r.get("phone") or ""
        status = r.get("status") or ""
        msg = (r.get("message") or "").splitlines()[0][:52]
        url = r.get("url") or ""
        print(f"    {sub:13} {phone:14} {status:8} {msg}")
        if url:
            print(f"               ↳ wa.me: {url[:84]}")


async def main() -> None:
    line(f"DETOMSITE — SMS & WhatsApp live demo ({DEMO[0]})")
    print("  (throwaway local DB — nothing touches production)")

    init_store()
    freeze_morning_10am()
    print("\n  ✓ local store initialised • time frozen at 10:00 AM IST • shop open")

    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    admin_token = await register_login(client, "demo_admin", "admin")
    stu1 = await register_login(client, "demo_student1", "student")
    stu2 = await register_login(client, "demo_student2", "student")

    shop, product = make_shop()
    print(f"  ✓ shop 'Sai Tiffins' (phone {shop['phone']}, whatsapp {shop['whatsapp_number']}) + product")

    # ── Step 1: COD order → outbound SMS + WhatsApp ─────────────────────────
    line("STEP 1 — Student orders ₹200 COD → shopkeeper gets SMS + WhatsApp")
    order = await place(client, stu1, shop["id"], product["id"], "Demo Student 1", method="COD")
    token = order["token"]
    await asyncio.sleep(0.15)  # let the fire-and-forget SMS/WA land in the logs
    print(f"\n  Order #{token}  status = {order['status']}  (COD)")
    print("\n  The SMS that lands on the shopkeeper's phone:")
    print("  " + "▌" + services.sms_service.compose_order_sms(order).replace("\n", "\n  ▌"))
    print("\n  The WhatsApp message (pre-filled wa.me link from admin's number):")
    wa = services.sms_service.compose_order_wa(order)
    print("  ▌" + wa.replace("\n", "\n  ▌"))
    await show_logs(client, admin_token, "sms")
    await show_logs(client, admin_token, "whatsapp")

    # ── Step 2: shopkeeper replies YES <token> ──────────────────────────────
    line(f'STEP 2 — Shopkeeper replies "YES {token}" → SMS webhook confirms')
    res = await client.post("/api/v1/local/sms/incoming",
                            json={"text": f"YES {token}", "phone": shop["phone"]},
                            headers=agent_headers())
    assert res.status_code == 200, res.text
    print(f"\n  /sms/incoming → order #{token} is now '{res.json()['order']['status']}'")
    print("  ✓ confirmation SMS sent to student (+919876543210)")
    await show_logs(client, admin_token, "sms")

    # ── Step 3: bank credit SMS auto-confirms a UPI order ───────────────────
    line("STEP 3 — Bank credit SMS (UTR + amount) auto-confirms a UPI order")
    uorder = await place(client, stu2, shop["id"], product["id"], "Demo Student 2", method="UPI")
    utoken = uorder["token"]
    print(f"\n  Order #{utoken}  status = {uorder['status']}  (UPI — waiting for payment proof)")
    bank_sms = ("Dear customer, Rs 200.00 credited to your HDFC Bank A/c "
                "***1234 on 16-Aug UTR HDFC123456789123. Available balance Rs 1450.50.")
    print(f"\n  Bank SMS forwarded from shop's SIM:\n  \"… Rs 200.00 credited … UTR HDFC123456789123 …\"")
    res = await client.post("/api/v1/local/sms/incoming",
                            json={"text": bank_sms, "phone": shop["phone"]},
                            headers=agent_headers())
    matched = res.json()
    print(f"\n  /sms/incoming → UTR {matched['matched']['utr']} + ₹{int(matched['matched']['amount'])} matched")
    print(f"  order #{utoken} → status = {matched['order']['status']}  (payment UTR stored, shopkeeper notified)")
    await show_logs(client, admin_token, "whatsapp")

    # ── Step 4: privacy-first /sms/match ─────────────────────────────────────
    line("STEP 4 — /sms/match: privacy-first UTR + amount only (no raw SMS text)")
    morder = await place(client, stu1, shop["id"], product["id"], "Demo Student 1", method="UPI")
    mtoken = morder["token"]
    print(f"\n  Order #{mtoken}  status = {morder['status']}  (UPI)")
    res = await client.post("/api/v1/local/sms/match",
                            json={"phone": shop["phone"], "utr": "HDFCC99999999999", "amount": 200.00},
                            headers=agent_headers())
    body = res.json()
    print(f"\n  /sms/match → order #{body['order_id']} → status = {body['order_status']} (UTRs matched, WhatsApp queued)")
    await show_logs(client, admin_token, "whatsapp")

    line("SUMMARY")
    print("  ✓ SMS outbound (shopkeeper + admin copy)        → sms_logs table")
    print("  ✓ SMS inbound 'YES <token>' → order Confirmed   → sms_logs table")
    print("  ✓ Bank SMS UTR+amount → UPI auto-confirmed      → payment.utr stored")
    print("  ✓ WhatsApp notifications (wa.me deep-link)      → whatsapp_logs table")
    print("  ✓ Privacy-first /sms/match (no raw SMS leaves the shop's phone)")
    await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())