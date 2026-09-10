"""
Static deployment readiness check for DETOMSITE.

Verifies the 3 independent portal apps (student, admin, shopkeeper) and the
backend are deployment-ready (Render for the backend, Vercel for the portals).
"""
from __future__ import annotations

import json
from pathlib import Path


# This script lives at backend/scripts/ — the repo root is 2 levels up.
ROOT = Path(__file__).resolve().parents[2]
# Portals live inside frontend/
PORTALS = ["student", "admin", "shopkeeper"]
PORTAL_DIR = "frontend"


def read(path: str) -> str:
    return (ROOT / path).read_text()


def has_all(text: str, names: list[str]) -> list[str]:
    return [name for name in names if name not in text]


def main() -> int:
    checks: list[tuple[str, bool, str]] = []

    # Backend env (Supabase mode)
    required_env = ["SUPABASE_DATABASE_URL", "JWT_SECRET", "FRONTEND_URL", "BACKEND_URL", "ALLOWED_ORIGINS"]
    backend_env = read("backend/.env.example")
    missing = has_all(backend_env, required_env)
    checks.append(("backend/.env.example has required variables", not missing, ", ".join(missing)))

    # Backend requirements
    requirements = read("backend/requirements.txt")
    checks.append(("backend requirements include psycopg2 (Supabase)", "psycopg2" in requirements, "psycopg2 missing"))
    checks.append(("Supabase store exists", (ROOT / "backend/app/core/supabase_db.py").exists(), "supabase_db.py missing"))
    checks.append(("Render config exists", (ROOT / "backend/render.yaml").exists(), "render.yaml missing"))
    checks.append(("Keep-alive script exists", (ROOT / "backend/scripts/keep_alive.py").exists(), "keep_alive.py missing"))

    # Each portal
    for portal in PORTALS:
        pkg = json.loads(read(f"{PORTAL_DIR}/{portal}/package.json"))
        has_build = "build" in pkg.get("scripts", {})
        vercel = json.loads(read(f"{PORTAL_DIR}/{portal}/vercel.json"))
        has_rewrites = bool(vercel.get("rewrites"))
        has_src = (ROOT / f"{PORTAL_DIR}/{portal}/src").is_dir()
        checks.append(
            (f"{PORTAL_DIR}/{portal}/package.json has build script", has_build, "build script missing"),
        )
        checks.append((f"{PORTAL_DIR}/{portal}/vercel.json has SPA rewrites", has_rewrites, "rewrites missing"))
        checks.append((f"{PORTAL_DIR}/{portal}/src exists", has_src, "src folder missing"))

    failed = False
    for label, ok, detail in checks:
        status = "OK" if ok else "FAIL"
        print(f"{status}: {label}")
        if not ok:
            failed = True
            if detail:
                print(f"  {detail}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
