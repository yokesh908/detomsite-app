"""
Backend application settings and configuration
"""
import secrets
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


def _generate_jwt_secret() -> str:
    """Generate a secure random JWT secret on first run. Persists to .env.auto
    so the same secret is reused across restarts (JWT tokens stay valid)."""
    from pathlib import Path
    auto_env = Path(__file__).resolve().parents[2] / ".env.auto"
    if auto_env.exists():
        try:
            for line in auto_env.read_text().splitlines():
                if line.startswith("SECRET_KEY=") and len(line.split("=", 1)[1]) > 10:
                    return line.split("=", 1)[1]
        except Exception:
            pass
    secret = secrets.token_urlsafe(48)
    try:
        auto_env.write_text(f"SECRET_KEY={secret}\n", encoding="utf-8")
    except Exception:
        pass
    return secret


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "DETOMSITE"
    APP_VERSION: str = "3.2.0"
    DEBUG: bool = False

    # Frontend / Supabase
    VITE_SUPABASE_URL: Optional[str] = None
    VITE_SUPABASE_ANON_KEY: Optional[str] = None
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # Database
    USE_LOCAL_DB: bool = True
    USE_TURSO_DB: bool = False
    USE_SUPABASE_DB: bool = False
    LOCAL_DB_PATH: str = "detomsite_local.db"
    TURSO_DATABASE_URL: str = ""
    TURSO_AUTH_TOKEN: str = ""
    # Supabase Postgres connection string, e.g.
    # postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
    SUPABASE_DATABASE_URL: str = ""
    SUPABASE_DB_HOST: str = ""
    SUPABASE_DB_PORT: int = 5432
    SUPABASE_DB_USER: str = "postgres"
    SUPABASE_DB_PASSWORD: str = ""
    SUPABASE_DB_NAME: str = "postgres"
    # Optional SECOND Supabase Postgres database (dual-read). When set, read-
    # only lookups fall back to this database whenever the primary returns
    # nothing, so the app can read historical data that lives in another
    # Supabase project while all writes/migrations stay on the primary.
    SUPABASE_SECONDARY_DATABASE_URL: str = ""
    SUPABASE_SECONDARY_DB_HOST: str = ""
    SUPABASE_SECONDARY_DB_PORT: int = 5432
    SUPABASE_SECONDARY_DB_USER: str = "postgres"
    SUPABASE_SECONDARY_DB_PASSWORD: str = ""
    SUPABASE_SECONDARY_DB_NAME: str = "postgres"
    MONGODB_URL: str = "mongodb://localhost:27017"
    DATABASE_NAME: str = "detomsite"
    SEED_DEMO_DATA: bool = False

    # SMS-forwarder agent auth. The Android app posts bank credit SMS to
    # ``/sms/incoming``; it must send ``X-Agent-Key: <SMS_FORWARD_KEY>`` so a
    # stranger can't feed fake "credits" and confirm orders they didn't pay.
    SMS_FORWARD_KEY: str = ""

    # WhatsApp automatic delivery. When a provider is configured, shopkeeper
    # WhatsApp messages (e.g. the paid-verified notification) are SENT
    # automatically instead of just queued as a Pending wa.me link for the
    # admin to tap. Supported providers: ``wassenger``, ``meta``, ``webhook``.
    WA_PROVIDER: str = ""
    WA_API_TOKEN: str = ""
    WA_API_URL: str = ""
    WA_META_TOKEN: str = ""
    WA_META_PHONE_ID: str = ""
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379"
    
    # JWT — auto-generated secure secret if not explicitly set via env var.
    JWT_SECRET: Optional[str] = None
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # Default Super Admin — NO hardcoded credentials. Set via env vars.
    DEFAULT_SUPER_ADMIN_EMAIL: str = ""
    DEFAULT_SUPER_ADMIN_PASSWORD: str = ""
    
    # Cloudinary
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""
    
    # Razorpay
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""
    
    # Web Push (VAPID) — order notifications for the installed vendor app.
    # Generate keys with:  python backend/scripts/gen_vapid.py
    # If these are empty, the backend auto-generates a local backend/vapid_keys.json
    # (git-ignored) so the feature works out of the box in development.
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    VAPID_SUBJECT: str = "mailto:admin@detomsite.local"

    # Student registration — restrict student accounts to college email domains.
    # Comma-separated list WITHOUT the @ sign, e.g. "campus.edu,college.edu".
    # Empty (default) = any valid email is accepted.
    STUDENT_EMAIL_DOMAINS: str = ""

    # SMTP — used to actually deliver the verification/reset OTP emails.
    # When SMTP_HOST is empty the email service falls back to logging the OTP
    # to the server log (and, in DEBUG mode, returns it in the API response).
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "DETOMSITE <no-reply@detomsite.local>"
    SMTP_USE_TLS: bool = True

    # Resend (https://resend.com) — preferred delivery path for the OTP / reset
    # emails. When RESEND_API_KEY is set, the email service sends via the Resend
    # HTTP API instead of SMTP (better deliverability, nothing to host).
    # RESEND_FROM must be an address on a domain you've verified with Resend —
    # the default "onboarding@resend.dev" only reaches the account owner's inbox
    # until you verify your own domain.
    RESEND_API_KEY: str = ""
    RESEND_FROM: str = "DETOMSITE <onboarding@resend.dev>"

    # Forgot-password OTP emails stay valid for this many minutes.
    RESET_OTP_EXPIRE_MINUTES: int = 15
    
    # Sentry
    SENTRY_DSN: Optional[str] = None
    
    # CORS
    FRONTEND_URL: str = "http://localhost:5173"
    BACKEND_URL: str = "http://localhost:8000"
    # Stored as a JSON string internally to avoid pydantic_settings JSON-decoding
    # before field_validators run. Use allowed_origins_list property to access as list.
    ALLOWED_ORIGINS: str = '["http://localhost:5173","http://localhost:5174","http://localhost:5175","http://localhost:3000"]'

    @property
    def allowed_origins_list(self) -> list:
        """Parse the ALLOWED_ORIGINS JSON string into a Python list."""
        import json
        try:
            parsed = json.loads(self.ALLOWED_ORIGINS)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        # Fallback: treat as comma-separated
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, value):
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "production", "prod", "false", "0", "no"}:
                return False
            if normalized in {"debug", "development", "dev", "true", "1", "yes"}:
                return True
        return value

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def normalize_allowed_origins(cls, value):
        """Normalize ALLOWED_ORIGINS to a JSON string."""
        import json
        if isinstance(value, list):
            return json.dumps(value)
        if isinstance(value, str):
            normalized = value.strip()
            # Already a valid JSON array? Keep it.
            if normalized.startswith("["):
                try:
                    json.loads(normalized)
                    return normalized
                except json.JSONDecodeError:
                    pass
            # Convert comma-separated string to JSON array
            items = [origin.strip() for origin in normalized.split(",") if origin.strip()]
            return json.dumps(items)
        return value

    @model_validator(mode="after")
    def validate_production_environment(self):
        if self.JWT_SECRET:
            self.SECRET_KEY = self.JWT_SECRET

        # Auto-generate a secure JWT secret if none was provided — prevents
        # the app from starting with a weak/empty secret in dev mode.
        if not self.SECRET_KEY or self.SECRET_KEY in {"", "your-secret-key-change-in-production"}:
            self.SECRET_KEY = _generate_jwt_secret()

        origins = self.allowed_origins_list
        for origin in [self.FRONTEND_URL, self.BACKEND_URL]:
            if origin and origin not in origins:
                origins.append(origin)
        # Store back as JSON string
        import json
        self.ALLOWED_ORIGINS = json.dumps(origins)

        if self.USE_LOCAL_DB and not self.USE_TURSO_DB and not self.USE_SUPABASE_DB:
            return self

        # In development (DEBUG=True) the app runs on localhost, so the strict
        # production-URL checks below don't apply. They kick in only when DEBUG
        # is off (i.e. real production deployments).
        is_dev = bool(self.DEBUG)

        missing = []
        if self.USE_TURSO_DB:
            if not self.TURSO_DATABASE_URL:
                missing.append("TURSO_DATABASE_URL")
            if not self.TURSO_AUTH_TOKEN:
                missing.append("TURSO_AUTH_TOKEN")
        elif self.USE_SUPABASE_DB:
            if not self.SUPABASE_DATABASE_URL and not self.SUPABASE_DB_PASSWORD:
                missing.append("SUPABASE_DATABASE_URL or SUPABASE_DB_PASSWORD")
        elif not self.MONGODB_URL or self.MONGODB_URL == "mongodb://localhost:27017":
            missing.append("MONGODB_URL")
        if not self.DATABASE_NAME:
            missing.append("DATABASE_NAME")
        if not is_dev:
            if not self.FRONTEND_URL or "localhost" in self.FRONTEND_URL:
                missing.append("FRONTEND_URL")
            if not self.BACKEND_URL or "localhost" in self.BACKEND_URL:
                missing.append("BACKEND_URL")
        if not self.DEFAULT_SUPER_ADMIN_EMAIL:
            if not is_dev:
                missing.append("DEFAULT_SUPER_ADMIN_EMAIL")
        if not self.DEFAULT_SUPER_ADMIN_PASSWORD:
            if not is_dev:
                missing.append("DEFAULT_SUPER_ADMIN_PASSWORD")

        if missing:
            raise ValueError(
                "Production environment is missing required values: "
                + ", ".join(sorted(set(missing)))
            )

        return self
    
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")


settings = Settings()
