import importlib


def test_shop_toggle_and_admin_actions(monkeypatch, tmp_path):
    db_path = tmp_path / "detomsite_test.db"
    monkeypatch.setenv("LOCAL_DB_PATH", str(db_path))
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("FRONTEND_URL", "https://example.com")
    monkeypatch.setenv("BACKEND_URL", "https://api.example.com")

    import app.core.local_demo_db as local_demo_db

    importlib.reload(local_demo_db)

    local_demo_db.init_local_demo_db()

    shop = local_demo_db.create_shop({
        "name": "Test Shop",
        "category": "Food",
        "description": "Demo",
        "shopkeeper_email": "vendor@example.com",
        "shopkeeper_name": "Vendor",
        "phone": "1234567890",
    })

    updated = local_demo_db.update_shop(shop["id"], {"present": True})
    assert updated["present"] == 1
    assert updated["status"] == "Open"

    suspended = local_demo_db.suspend_shop(shop["id"])
    assert suspended["approval_status"] == "Suspended"
    assert suspended["present"] == 0
    assert suspended["status"] == "Closed"

    removed = local_demo_db.remove_shop(shop["id"])
    assert removed["approval_status"] == "Removed"
    assert removed["is_removed"] == 1
