"""
Store facade — picks the active data store based on backend settings.

- ``USE_SUPABASE_DB=True`` → Supabase (Postgres) store
- ``USE_TURSO_DB=True``     → Turso/libSQL store (via local_demo_db)
- otherwise                → local SQLite store

The API layer imports ``store`` instead of ``local_demo_db`` directly, so no
other code changes are needed to switch databases.
"""
from __future__ import annotations

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

if settings.USE_SUPABASE_DB:
    from app.core import supabase_db as store  # type: ignore[no-redef]
elif settings.USE_TURSO_DB:
    from app.core import local_demo_db as store  # type: ignore[no-redef]
else:
    from app.core import local_demo_db as store  # type: ignore[no-redef]


def init_store() -> bool:
    """Initialize / verify the active store. Returns True when ready."""
    if settings.USE_SUPABASE_DB:
        ok = store.init_supabase_db()
        if not ok:
            logger.error(
                "Supabase store is not reachable. Check SUPABASE_DATABASE_URL in "
                "backend/.env and that backend/supabase/schema.sql has been run."
            )
            return ok
    else:
        store.init_local_demo_db()
    # Seed the super admin as a real DB user (role='admin') so the admin
    # forgot-password OTP flow can find and update it.
    if hasattr(store, "ensure_admin_user"):
        store.ensure_admin_user()
    return True
