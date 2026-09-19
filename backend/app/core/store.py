"""
Store facade — Supabase Postgres is the ONLY database.

The old SQLite / Turso / MongoDB switcher was removed: ``store`` is always
``supabase_db``. The ONLY exception is pytest, where tests/conftest.py swaps in
the throwaway local SQLite module (local_demo_db) so tests never touch the
live Supabase project (see store._use_test_store / conftest._init_test_db).
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Swapped to local_demo_db by tests/conftest.py during pytest only.
_test_store = None


def _use_test_store(module) -> None:
    """Point the ``store`` proxy at a test-only module (pytest only)."""
    global _test_store
    _test_store = module


class _StoreProxy:
    """Attribute proxy so ``from app.core.store import store`` keeps working
    while conftest can swap the backing module per test-session."""

    def _target(self):
        if _test_store is not None:
            return _test_store
        from app.core import supabase_db as _supabase_store

        return _supabase_store

    def __getattr__(self, name):
        return getattr(self._target(), name)


store = _StoreProxy()


def init_store() -> bool:
    """Initialize / verify the Supabase store. Returns True when ready."""
    from app.core import supabase_db as _supabase_store

    ok = _supabase_store.init_supabase_db()
    if not ok:
        logger.error(
            "Supabase store is not reachable. Check SUPABASE_DATABASE_URL in "
            "backend/.env and that backend/supabase/schema.sql has been run."
        )
        return ok
    # Seed the super admin as a real DB user (role='admin') so the admin
    # forgot-password OTP flow can find and update it.
    if hasattr(_supabase_store, "ensure_admin_user"):
        _supabase_store.ensure_admin_user()
    return True
