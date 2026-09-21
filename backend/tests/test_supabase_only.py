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


def test_missing_database_settings_warn_but_boot():
    # A missing DB URL must NEVER crash the import/cold-start (that turns every
    # route into a 404/DEPLOYMENT_NOT_FOUND page on Vercel). Settings boot with
    # a warning and requests fail with a clear message instead. This test uses
    # DEBUG=True so no production-URL checks interfere.
    s = Settings(_env_file=None, DEBUG=True, JWT_SECRET="test-only",
                 SUPABASE_DATABASE_URL="", SUPABASE_DB_HOST="",
                 SUPABASE_DB_PASSWORD="")
    assert s.SUPABASE_DATABASE_URL == ""


def test_failed_initialization_does_not_seed_admin(monkeypatch):
    monkeypatch.setattr(supabase_db, "init_supabase_db", lambda: False)

    def unexpected_seed():
        pytest.fail("Must not seed an unavailable database")

    monkeypatch.setattr(supabase_db, "ensure_admin_user", unexpected_seed)
    assert store_module.init_store() is False


async def test_startup_serves_anyway_when_supabase_down(monkeypatch):
    # A cold Supabase pooler hiccup must NOT kill the whole serverless instance
    # (the old behaviour raised and every route became a 404 page). The app now
    # boots anyway; requests fail with a clear 503/513 message instead.
    monkeypatch.setattr(store_module, "init_store", lambda: False)
    import app.main as main

    async def no_background_work():
        return

    monkeypatch.setattr(main, "keep_alive_loop", no_background_work)
    monkeypatch.setattr(main, "auto_delivery_loop", no_background_work)
    async with lifespan(app):
        pass  # must not raise


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
