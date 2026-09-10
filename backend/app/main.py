"""
Main FastAPI application
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
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
KEEP_ALIVE_INTERVAL_SECONDS = 5 * 60


async def keep_alive_loop():
    """Background task: hit /health every 5 minutes like a cron job."""
    import httpx

    url = (os.environ.get("HEALTH_URL") or "").strip()
    if not url:
        base = (settings.BACKEND_URL or "").strip().rstrip("/")
        if base:
            url = f"{base}/health"
    if not url:
        logger.warning("keep-alive: no HEALTH_URL/BACKEND_URL configured — self-ping disabled")
        return

    logger.info(f"keep-alive: self-ping cron active every {KEEP_ALIVE_INTERVAL_SECONDS // 60} min → {url}")
    while True:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url)
            logger.info(f"keep-alive: pinged {url} → {response.status_code}")
        except Exception as exc:
            logger.warning(f"keep-alive: ping error -> {exc}")
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
_RATE_LIMIT_MAX = 10     # max requests per window per IP


async def rate_limit_middleware(request: Request, call_next):
    """Rate-limit sensitive endpoints (login, register, forgot-password)."""
    path = request.url.path
    sensitive_prefixes = ("/auth/login", "/auth/register", "/users/login",
                          "/users/register", "/vendor/login", "/vendor/register",
                          "/admin/login", "/users/forgot-password")
    if not any(path.endswith(p) for p in sensitive_prefixes):
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
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
    # Startup
    logger.info("Starting DETOMSITE application")
    # Keep-alive cron: self-ping /health every 5 minutes so the free-tier
    # backend never sleeps (works even without the external Render cron).
    keep_alive_task = asyncio.create_task(keep_alive_loop())
    auto_delivery_task = asyncio.create_task(auto_delivery_loop())
    if settings.USE_SUPABASE_DB:
        from app.core.store import init_store
        init_store()
        logger.info("Supabase Postgres store initialized")
    elif settings.USE_TURSO_DB:
        from app.core.store import init_store
        init_store()
        logger.info("Turso database initialized")
    elif settings.USE_LOCAL_DB:
        from app.core.store import init_store
        init_store()
        logger.info("Local SQLite database initialized")
    else:
        from app.core.database import connect_to_mongo
        await connect_to_mongo()

        # Initialize default super admin if none exists
        from app.services.auth_service import init_default_super_admin
        await init_default_super_admin()

        from app.core.local_mongo_db import init_local_mongo_db
        await init_local_mongo_db()
        logger.info("MongoDB local API collections initialized")
    
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
    if not settings.USE_LOCAL_DB and not settings.USE_TURSO_DB and not settings.USE_SUPABASE_DB:
        from app.core.database import close_mongo_connection
        await close_mongo_connection()


# ─── 30-minute auto-delivery background job ───
async def auto_delivery_loop():
    """Every 60 seconds, auto-complete sub-orders delivered more than 30 minutes
    ago (the student didn't report a problem) — see spec section 36. Uses the
    store facade so it works on SQLite, Turso AND Supabase."""
    while True:
        await asyncio.sleep(60)
        try:
            if not settings.USE_LOCAL_DB and not settings.USE_TURSO_DB and not settings.USE_SUPABASE_DB:
                continue
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

# Configure CORS — restrict methods and headers in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# Include routers
from app.api.v1 import local, users, vendor, local_admin
from app.middleware.error_handler import ErrorHandlingMiddleware, LoggingMiddleware

# Add middleware (order matters — last added = first executed)
app.add_middleware(ErrorHandlingMiddleware)
app.add_middleware(LoggingMiddleware)
app.add_middleware(BaseHTTPMiddleware, dispatch=rate_limit_middleware)

app.include_router(
    local.router,
    prefix="/api/v1/local",
    tags=["Local Runnable API"]
)

# Register the three portals (always available, even in local mode)
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

if not settings.USE_LOCAL_DB and not settings.USE_TURSO_DB and not settings.USE_SUPABASE_DB:
    from app.api.v1 import auth, users, campuses, shops, products, orders, payments, reviews, tickets, admin, admin_super

    app.include_router(
        auth.router,
        prefix="/api/v1/auth",
        tags=["Authentication"]
    )
    app.include_router(
        users.router,
        prefix="/api/v1/users",
        tags=["Users"]
    )
    app.include_router(
        campuses.router,
        prefix="/api/v1/campuses",
        tags=["Campuses"]
    )
    app.include_router(
        shops.router,
        prefix="/api/v1/shops",
        tags=["Shops"]
    )
    app.include_router(
        products.router,
        prefix="/api/v1/products",
        tags=["Products"]
    )
    app.include_router(
        orders.router,
        prefix="/api/v1/orders",
        tags=["Orders"]
    )
    app.include_router(
        payments.router,
        prefix="/api/v1/payments",
        tags=["Payments"]
    )
    app.include_router(
        reviews.router,
        prefix="/api/v1/reviews",
        tags=["Reviews"]
    )
    app.include_router(
        tickets.router,
        prefix="/api/v1/tickets",
        tags=["Tickets"]
    )
    app.include_router(
        admin.router,
        prefix="/api/v1/admin",
        tags=["Admin"]
    )
    app.include_router(
        admin_super.router,
        prefix="/api/v1/super-admin",
        tags=["Super Admin"]
    )


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
