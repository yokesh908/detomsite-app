"""Temporary smoke test — vendor product add + COD Accept/Complete flow.

Runs against the LOCAL SQLite store (what localhost uses). Verifies:
  1. Vendor register + login
  2. Add product (after shop approval) -> previously failed with 500 in prod
  3. COD order: Pending Acceptance -> Accepted -> Completed
"""
import os
import sys
import tempfile

# Fresh temp DB so we never touch real data
_tmp = tempfile.mkdtemp()
os.environ["LOCAL_DB_PATH"] = os.path.join(_tmp, "smoke.db")
os.environ["USE_LOCAL_DB"] = "True"
os.environ["USE_TURSO_DB"] = "False"
os.environ["USE_SUPABASE_DB"] = "False"
os.environ["JWT_SECRET"] = "smoke-test-secret"
os.environ["SECRET_KEY"] = "smoke-test-secret"
os.environ["DEBUG"] = "True"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond), extra))
    # Keep the console ASCII-safe (Windows cp1252 chokes on emoji in responses)
    safe = str(extra).encode("ascii", "replace").decode("ascii")
    print(("PASS" if cond else "FAIL"), "-", name, safe)


with TestClient(app) as client:
    # 1. Register vendor
    r = client.post("/api/v1/vendor/register", json={
        "username": "smokevendor", "email": "v@x.com", "password": "pass1234",
        "name": "Smoke Vendor", "phone": "9876543210",
        "shop_name": "Smoke Shop", "shop_category": "Fast Food",
        "shop_description": "smoke", "upi_id": "smoke@okaxis",
    })
    check("register vendor", r.status_code == 201, str(r.status_code))
    shop = (r.json().get("shop") or {})
    shop_id = shop.get("id", "")

    # 2. Approve + open the shop directly (admin step)
    from app.core.store import store as db
    db.update_shop(shop_id, {"approval_status": "Approved", "present": True, "status": "Open"})

    # 3. Login
    r = client.post("/api/v1/vendor/login", json={"username": "smokevendor", "password": "pass1234"})
    check("vendor login", r.status_code == 200, str(r.status_code))
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3b. Web push notification endpoints
    r = client.get("/api/v1/vendor/push/config", headers=headers)
    check("push config", r.status_code == 200 and "enabled" in r.json(), f"{r.status_code} {r.text[:120]}")
    r = client.post("/api/v1/vendor/push/subscribe", json={
        "endpoint": "https://push.example.invalid/fake-endpoint-1",
        "keys": {"p256dh": "dGVzdA", "auth": "dGVzdA"},
    }, headers=headers)
    check("push subscribe", r.status_code == 200 and r.json().get("ok") is True, f"{r.status_code} {r.text[:120]}")
    # Test-push endpoint returns a real result (fake endpoint -> reported error)
    r = client.post("/api/v1/vendor/push/test", headers=headers)
    check("push test endpoint", r.status_code == 200 and "detail" in r.json(), f"{r.status_code} {r.text[:160]}")

    # 4. Add product (the endpoint that failed in production)
    r = client.post("/api/v1/vendor/products", json={
        "name": "Burger", "price": 99, "category": "Food", "description": "yum", "inventory": 5,
    }, headers=headers)
    check("add product", r.status_code == 201, f"{r.status_code} {r.text[:200]}")
    product = r.json() if r.status_code == 201 else {}
    pid = product.get("id", "")

    # 5. List products
    r = client.get("/api/v1/vendor/products", headers=headers)
    check("list products", r.status_code == 200 and any(p.get("id") == pid for p in r.json()), r.text[:200])

    # 6. Duplicate-safety: add a second product (id should not collide after no deletes)
    r = client.post("/api/v1/vendor/products", json={"name": "Pizza", "price": 199, "category": "Food"}, headers=headers)
    check("add second product", r.status_code == 201, f"{r.status_code} {r.text[:200]}")

    # 7. Delete the first product, then add another — old COUNT+1 logic would collide here
    if pid:
        client.delete(f"/api/v1/vendor/products/{pid}", headers=headers)
    r = client.post("/api/v1/vendor/products", json={"name": "Fries", "price": 49, "category": "Starters"}, headers=headers)
    check("add product after delete (no id collision)", r.status_code == 201, f"{r.status_code} {r.text[:200]}")

    # 8. COD order flow (student app always sends quantity)
    products = client.get("/api/v1/vendor/products", headers=headers).json()
    r = client.post("/api/v1/local/orders", json={
        "shop_id": shop_id,
        "items": [{"product_id": products[0]["id"], "quantity": 1}],
        "student_name": "Smoke Student", "student_phone": "1111111111",
        "delivery_location": "Hostel", "delivery_slot": "Evening",
        "payment_method": "COD",
    })
    check("COD order created", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    order_id = (r.json() or {}).get("id", "")

    # 9. Accept the COD order
    r = client.patch(f"/api/v1/vendor/orders/{order_id}/status", json={"status": "Accepted"}, headers=headers)
    check("COD accept -> Accepted", r.status_code == 200 and (r.json() or {}).get("status") == "Accepted", f"{r.status_code} {r.text[:200]}")

    # 10. Complete after cash collected
    r = client.patch(f"/api/v1/vendor/orders/{order_id}/status", json={"status": "Completed"}, headers=headers)
    check("COD complete -> Completed", r.status_code == 200 and (r.json() or {}).get("status") == "Completed", f"{r.status_code} {r.text[:200]}")

    # 10b. Placing the order attempted a push — a dead endpoint is ignored and
    # the subscription must still be registered.
    subs = db.list_push_subscriptions(shop_id)
    check("push subscription survives order", any(s.get("endpoint", "").endswith("fake-endpoint-1") for s in subs), str(subs))

    # 11. Dashboard returns accepted/completed counts
    r = client.get("/api/v1/vendor/dashboard", headers=headers)
    stats = (r.json() or {}).get("stats", {})
    check("dashboard ok", r.status_code == 200, str(r.status_code))
    check("dashboard completed_orders >= 1", stats.get("completed_orders", 0) >= 1, str(stats))

    # 11b. History with server-resolved IST range works (matches dashboard day)
    r = client.get("/api/v1/vendor/history", params={"range": "today"}, headers=headers)
    check("history range=today", r.status_code == 200 and "orders" in r.json() and "count" in r.json(), f"{r.status_code} {r.text[:160]}")
    today_counts_match = (r.json().get("count", 0) == stats.get("today_orders", -1)) if r.status_code == 200 else False
    check("history today count == dashboard today count", today_counts_match, f"history={r.json().get('count')} dashboard={stats.get('today_orders')}")

    # 12. Student-facing local endpoints (threadpool fix) still work
    r = client.post("/api/v1/local/auth/register", json={"username": "smokestudent", "password": "pass1234", "name": "Smoke Student", "role": "student"})
    check("student register", r.status_code == 201, f"{r.status_code} {r.text[:120]}")
    r = client.post("/api/v1/local/auth/login", json={"username": "smokestudent", "password": "pass1234"})
    check("student login", r.status_code == 200, str(r.status_code))
    s_token = r.json()["access_token"]
    s_headers = {"Authorization": f"Bearer {s_token}"}
    r = client.get("/api/v1/local/shops", params={"public_only": "true"})
    check("student shops", r.status_code == 200 and len(r.json()) >= 1, f"{r.status_code} {len(r.json())}")
    r = client.get("/api/v1/local/products")
    check("student products", r.status_code == 200 and len(r.json()) >= 1, f"{r.status_code} {len(r.json())}")
    r = client.get(f"/api/v1/local/orders/{order_id}")
    check("student order detail", r.status_code == 200 and (r.json() or {}).get("status") == "Completed", f"{r.status_code} {r.text[:120]}")
    r = client.get("/api/v1/local/payment-settings")
    check("payment settings", r.status_code == 200, str(r.status_code))
    r = client.get("/api/v1/local/notifications", params={"role": "student"})
    check("notifications", r.status_code == 200, str(r.status_code))
    r = client.get("/api/v1/local/auth/me", headers=s_headers)
    check("student me", r.status_code == 200 and (r.json() or {}).get("role") == "student", f"{r.status_code} {r.text[:120]}")
    r = client.patch(f"/api/v1/local/orders/{order_id}/status", json={"status": "Completed"})
    check("local order status patch", r.status_code == 200, f"{r.status_code} {r.text[:120]}")

    # 13. Unsubscribe from push (endpoint passed as a query param)
    r = client.delete("/api/v1/vendor/push/subscribe", params={"endpoint": "https://push.example.invalid/fake-endpoint-1"}, headers=headers)
    check("push unsubscribe", r.status_code == 200 and r.json().get("ok") is True, f"{r.status_code} {r.text[:120]}")
    # 13b. Non-https subscribe endpoint must be rejected
    r = client.post("/api/v1/vendor/push/subscribe", json={
        "endpoint": "http://insecure.example.com/push",
        "keys": {"p256dh": "dGVzdA", "auth": "dGVzdA"},
    }, headers=headers)
    check("push subscribe rejects non-https", r.status_code == 400, f"{r.status_code} {r.text[:120]}")
    subs = db.list_push_subscriptions(shop_id)
    check("push subscription removed", all(not s.get("endpoint", "").endswith("fake-endpoint-1") for s in subs), str(subs))

print()
failed = [n for n, ok, _ in results if not ok]
print("TOTAL:", len(results), "PASSED:", len(results) - len(failed), "FAILED:", len(failed))
if failed:
    print("FAILED TESTS:", failed)
    sys.exit(1)
