from __future__ import annotations

from typing import Any

from app.core.store import store


def persist_user_profile(email: str, name: str, role: str) -> dict[str, Any]:
    return store.save_session(email=email, name=name, role=role)
