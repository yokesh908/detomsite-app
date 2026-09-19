"""
Main FastAPI application
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.uploads import get_uploads_dir
import asyncio
import logging
import os
import time
from collections import defaultdict

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── In-app keep-alive cron ───
# Pings faster (every 2 min) and hits SEVERAL endpoints so Vercel keeps a few
# warm lambda instances instead of one — cold Python starts (≈10–20s) are the
# single biggest slowness users feel on the portals.
KEEP_ALIVE_INTERVAL_SECONDS = 2 * 60
KEEP_ALIVE_PATHS = ("/health", "/api/v1/local/batch", "/api/v1/local/status")


async def keep_alive_loop():
    """Background task: warm a few backend endpoints every 2 minutes so the
    portals rarely hit a cold start."""
    import httpx

    base = (os.environ.get("HEALTH_URL") or settings.BACKEND_URL or "").strip().rstrip("/")
    if not base:
        logger.warning("keep-alive: no HEALTH_URL/BACKEND_URL configured — self-ping disabled")
        return
    if not base.startswith("http"):
        base = f"https://{base}"

    logger.info(f"keep-alive: warm-up cron active every {KEEP_ALIVE_INTERVAL_SECONDS // 60} min → {base}")
    while True:
        for path in KEEP_ALIVE_PATHS:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.get(f"{base}{path}")
                logger.info(f"keep-alive: {path} → {response.status_code}")
            except Exception as exc:
                logger.warning(f"keep-alive: {path} error -> {exc}")
        await asyncio.sleep(KEEP_ALIVE_INTERVAL_SECONDS)

# Initialize Sentry if DSN is provided — sample 10% of traces (not 100%)
if sentry_sdk and settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        traces_sample_rate=0.1
    )


# ─── Simple in-memory rate limiter ───
# Protects auth endpoints from brute-force attacks. No external deps needed.
_rate_limit_store: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT_WINDOW = 60  # seconds
# Cap per real client IP (not per Vercel proxy IP), tuned for a campus behind
# a shared NAT: generous enough that a lunch-rush login flash is never blocked,
# tight enough to blunt naive flood attacks. Real brute-force defence happens
# per-account in the auth endpoints themselves.
_RATE_LIMIT_MAX = 60


async def rate_limit_middleware(request: Request, call_next):
    """Rate-limit sensitive endpoints (login, register, forgot-password)."""
    path = request.url.path
    sensitive_prefixes = ("/auth/login", "/auth/register", "/users/login",
                          "/users/register", "/vendor/login", "/vendor/register",
                          "/admin/login", "/users/forgot-password")
    if not any(path.endswith(p) for p in sensitive_prefixes):
        return await call_next(request)

    # Trust the first x-forwarded-for hop (set by Vercel) so every student gets
    # their OWN bucket; using request.client.host would lump the whole campus
    # behind the proxy's IP into a single 10/min quota.
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    client_ip = forwarded or (request.client.host if request.client else "unknown")
    now = time.time()
    key = f"{client_ip}:{path}"
    # Prune old entries
    _rate_limit_store[key] = [t for t in _rate_limit_store[key] if now - t < _RATE_LIMIT_WINDOW]
    if len(_rate_limit_store[key]) >= _RATE_LIMIT_MAX:
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please try again later."}
        )
    _rate_limit_store[key].append(now)
    return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events"""
    # Startup — Supabase Postgres is the ONLY database.
    logger.info("Starting DETOMSITE application")
    from app.core.store import init_store
    if not await asyncio.to_thread(init_store):
        raise RuntimeError("Supabase initialization failed; no fallback database is available.")
    logger.info("Supabase Postgres store initialized")
    keep_alive_task = asyncio.create_task(keep_alive_loop())
    auto_delivery_task = asyncio.create_task(auto_delivery_loop())
    
    yield

    # Shutdown — cancel background tasks so the process can exit cleanly.
    keep_alive_task.cancel()
    auto_delivery_task.cancel()
    try:
        await keep_alive_task
    except asyncio.CancelledError:
        pass
    try:
        await auto_delivery_task
    except asyncio.CancelledError:
        pass

    logger.info("Shutting down DETOMSITE application")


# ─── 30-minute auto-delivery background job ───
async def auto_delivery_loop():
    """Every 60 seconds, auto-complete sub-orders delivered more than 30 minutes
    ago (the student didn't report a problem) — see spec section 36. Uses the
    Supabase store."""
    while True:
        await asyncio.sleep(60)
        try:
            from app.core.store import store
            def _run():
                return store.auto_complete_expired_deliveries()
            count = await asyncio.to_thread(_run)
            if count:
                logger.info(f"auto_delivery_loop: auto-completed {count} sub-order(s)")
        except Exception as e:
            logger.warning(f"auto_delivery_loop error: {e}")


# Create FastAPI app instance
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Enterprise Campus Food Ordering Platform",
    lifespan=lifespan,
)

# ─── Uploaded files (payment screenshots) ───
# Served under /uploads so the student portal can show the screenshot back.
# Payment screenshots are served at /uploads/payments/<name>. The backing
# directory lives in the platform's writable temp dir (never the app tree —
# serverless filesystems are read-only there).
UPLOADS_DIR = get_uploads_dir()
os.makedirs(UPLOADS_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

# Configure CORS — restrict methods and headers in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Compress every JSON response ≥ 500 bytes — cuts transfer ~80% on the big
# lists (orders, products, notifications) that the portals poll all day.
app.add_middleware(GZipMiddleware, minimum_size=500)


# Drop the read TTL-cache after any successful write, so cached portals
# (admin/shopkeeper lists) never show stale rows once an action lands.
from app.core import ttl_cache, shared_cache


async def cache_invalidation_middleware(request: Request, call_next):
    response = await call_next(request)
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and response.status_code < 400:
        ttl_cache.clear()
        if shared_cache.enabled():
            await asyncio.to_thread(shared_cache.clear)
    return response


app.add_middleware(BaseHTTPMiddleware, dispatch=cache_invalidation_middleware)


# Include routers
from app.api.v1 import local, users, vendor, local_admin
from app.middleware.error_handler import ErrorHandlingMiddleware, LoggingMiddleware, SecurityHeadersMiddleware

# Add middleware (order matters — last added = first executed)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(ErrorHandlingMiddleware)
app.add_middleware(LoggingMiddleware)
app.add_middleware(BaseHTTPMiddleware, dispatch=rate_limit_middleware)

app.include_router(
    local.router,
    prefix="/api/v1/local",
    tags=["Local Runnable API"]
)

# Register the three portals (always available — all backed by Supabase).
app.include_router(
    users.router,
    prefix="/api/v1/users",
    tags=["User Portal"]
)
app.include_router(
    vendor.router,
    prefix="/api/v1/vendor",
    tags=["Vendor Portal"]
)
app.include_router(
    local_admin.router,
    prefix="/api/v1/admin",
    tags=["Admin Portal"]
)

# NOTE: the old Mongo-only routers (auth, campuses, shops, products, orders,
# payments, reviews, tickets, admin, super-admin) were removed with the MongoDB
# backend. Supabase is the only database; /api/v1/local + /users + /vendor +
# /admin above are the full API.


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": f"Welcome to {settings.APP_NAME}",
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "redoc": "/redoc",
        "openapi": "/openapi.json"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
