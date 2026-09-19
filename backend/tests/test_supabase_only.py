"""Supabase-only routing and startup regression tests (no network access)."""
import pytest
from pydantic import ValidationError

from app.core import store as store_module, supabase_db
from app.core.config import Settings
from app.main import app, lifespan


def test_store_always_targets_supabase(monkeypatch):
    monkeypatch.setattr(store_module, "_test_store", None)
    monkeypatch.setenv("USE_LOCAL_DB", "True")
    monkeypatch.setenv("USE_TURSO_DB", "True")
    monkeypatch.setenv("USE_SUPABASE_DB", "False")
    assert store_module.store._target() is supabase_db


def test_missing_database_settings_rejected():
    with pytest.raises(ValidationError, match="SUPABASE_DATABASE_URL"):
        Settings(_env_file=None, DEBUG=True, JWT_SECRET="test-only",
                 SUPABASE_DATABASE_URL="", SUPABASE_DB_HOST="",
                 SUPABASE_DB_PASSWORD="")


def test_failed_initialization_does_not_seed_admin(monkeypatch):
    monkeypatch.setattr(supabase_db, "init_supabase_db", lambda: False)

    def unexpected_seed():
        pytest.fail("Must not seed an unavailable database")

    monkeypatch.setattr(supabase_db, "ensure_admin_user", unexpected_seed)
    assert store_module.init_store() is False


async def test_startup_rejects_unavailable_supabase(monkeypatch):
    monkeypatch.setattr(store_module, "init_store", lambda: False)
    with pytest.raises(RuntimeError, match="no fallback database"):
        async with lifespan(app):
            pytest.fail("Startup must fail before serving requests")


async def test_successful_lifespan_and_health(monkeypatch, client):
    monkeypatch.setattr(store_module, "init_store", lambda: True)
    # Disable external self-pings for this isolated startup check.
    import app.main as main

    async def no_background_work():
        return

    monkeypatch.setattr(main, "keep_alive_loop", no_background_work)
    monkeypatch.setattr(main, "auto_delivery_loop", no_background_work)
    async with lifespan(app):
        response = await client.get("/health")
        assert response.status_code == 200
