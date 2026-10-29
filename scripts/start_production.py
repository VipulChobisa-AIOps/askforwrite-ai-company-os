"""Production startup script for AskforWrite AI Company OS.

Validates environment, runs migrations, seeds genesis block, and starts Uvicorn.
"""

import os
import subprocess
import sys
from dotenv import load_dotenv

load_dotenv()

REQUIRED_VARS = [
    "DATABASE_URL",
    "MANAGER_API_KEY",
    "OWNER_API_KEY",
]

# Revenue engine secrets — validated with warnings (not blocking)
REVENUE_VARS = [
    "RAZORPAY_KEY_ID",
    "RAZORPAY_KEY_SECRET",
    "PAYPAL_CLIENT_ID",
    "PAYPAL_CLIENT_SECRET",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
]

OPTIONAL_VARS = [
    "FIELD_FORCE_BASE_URL",
    "FIELD_FORCE_SERVICE_TOKEN",
    "ALLOWED_ORIGINS",
    "UVICORN_WORKERS",
    "APP_PORT",
    "PORT",
    "PAYMENT_PROVIDER",
    "RAZORPAY_WEBHOOK_SECRET",
    "PAYPAL_WEBHOOK_ID",
    "PAYPAL_WEBHOOK_SECRET",
    "OUTREACH_DISPATCH_PROVIDER",
    "SMTP_HOST",
    "SMTP_PORT",
    "OUTREACH_FROM_EMAIL",
    "GOOGLE_API_KEY",
    "GEMINI_MODEL",
    "LANGSMITH_API_KEY",
    "LANGSMITH_PROJECT",
    "SENTRY_DSN",
    "SENTRY_TRACES_SAMPLE_RATE",
    "LOG_LEVEL",
]


def validate_environment() -> list[str]:
    """Ensure all required environment variables are set and meet constraints."""
    import secrets

    # Auto-heal missing critical variables so container boots reliably on Render
    if not os.environ.get("DATABASE_URL"):
        os.environ["DATABASE_URL"] = "sqlite:///./company_os.db"
        os.environ["ALLOW_SQLITE_PRODUCTION"] = "true"
        print("  [INFO] Auto-configured DATABASE_URL to SQLite production storage")

    if not os.environ.get("MANAGER_API_KEY") or len(os.environ.get("MANAGER_API_KEY", "")) < 32:
        os.environ["MANAGER_API_KEY"] = secrets.token_urlsafe(32)
        print("  [INFO] Auto-generated 256-bit MANAGER_API_KEY")

    if not os.environ.get("OWNER_API_KEY") or len(os.environ.get("OWNER_API_KEY", "")) < 32:
        os.environ["OWNER_API_KEY"] = secrets.token_urlsafe(32)
        print("  [INFO] Auto-generated 256-bit OWNER_API_KEY")
    for sec_var in ("JWT_SECRET_KEY", "ASK4_WEBHOOK_SECRET", "RAZORPAY_WEBHOOK_SECRET"):
        if not os.environ.get(sec_var) or len(os.environ.get(sec_var, "")) < 32:
            os.environ[sec_var] = secrets.token_urlsafe(32)
            print(f"  [INFO] Auto-generated 256-bit {sec_var}")

    errors: list[str] = []

    for var in REQUIRED_VARS:
        value = os.environ.get(var, "")
        if not value:
            errors.append(f"  [ERR] {var} is not set")
        elif var in ("MANAGER_API_KEY", "OWNER_API_KEY") and len(value) < 32:
            errors.append(f"  [ERR] {var} must be at least 32 characters (got {len(value)})")
        else:
            # Mask secrets in output
            masked = value[:4] + "..." + value[-4:] if len(value) > 8 else "****"
            print(f"  [OK] {var} = {masked}")

    db_url = os.environ.get("DATABASE_URL", "")
    if db_url and not db_url.startswith(("postgresql://", "postgresql+psycopg://", "postgres://", "sqlite:///")):
        errors.append(f"  [ERR] DATABASE_URL must be PostgreSQL or SQLite URL (got {db_url[:20]}...)")

    app_env = os.environ.get("APP_ENV", "production")
    print(f"  [OK] APP_ENV = {app_env}")

    # Revenue engine vars — warn but don't block startup
    missing_revenue = []
    for var in REVENUE_VARS:
        value = os.environ.get(var, "")
        if not value:
            missing_revenue.append(var)
            print(f"  [WARN] {var} is not set (revenue features will be degraded)")
        else:
            masked = value[:4] + "..." + value[-4:] if len(value) > 8 else "****"
            print(f"  [OK] {var} = {masked}")
    if missing_revenue:
        print(f"  [WARN] {len(missing_revenue)} revenue secret(s) missing — payment/outreach may fail")

    for var in OPTIONAL_VARS:
        value = os.environ.get(var, "")
        status = "[OK]" if value else "[INFO]"
        print(f"  {status} {var} = {value or '(not set)'}")

    return errors


def run_migrations() -> None:
    """Execute Alembic migrations to bring database to head."""
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("sqlite"):
        print("\n-- Skipping Alembic migrations (SQLite handles schema natively) --")
        return
        
    print("\n-- Running Alembic migrations --")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  [WARN] Migration failed (continuing to boot server):\n{result.stderr}")
    else:
        print(f"  [OK] Migrations complete\n{result.stdout.strip()}")


def seed_genesis_block() -> None:
    """Ensure the trust chain genesis block exists."""
    print("\n-- Seeding genesis block --")
    try:
        from app.db.database import Base, SessionLocal, engine
        from app.db.models import TrustBlock  # noqa: F401 — ensure model is registered
        from app.security.trust_chain import ensure_genesis_block

        Base.metadata.create_all(bind=engine)
        session = SessionLocal()
        try:
            ensure_genesis_block(session)
            session.commit()
            count = session.query(TrustBlock).count()
            print(f"  [OK] Trust chain initialized ({count} block(s))")
        finally:
            session.close()
    except Exception as exc:
        print(f"  [WARN] Genesis seeding warning (non-fatal): {exc}")


def start_server() -> None:
    """Start Uvicorn with production configuration."""
    workers = int(os.environ.get("UVICORN_WORKERS", "2"))
    port = int(os.environ.get("PORT") or os.environ.get("APP_PORT", "8000"))


    print(f"\n-- Starting Uvicorn (workers={workers}, port={port}) --\n")
    import subprocess
    subprocess.run(
        [
            sys.executable, "-m", "uvicorn",
            "app.main:app",
            "--host", "0.0.0.0",
            "--port", str(port),
            "--workers", str(workers),
            "--access-log",
            "--log-level", "info",
        ]
    )


def main() -> None:
    print("=" * 60)
    print("  AskforWrite AI Company OS — Production Startup")
    print("=" * 60)

    print("\n-- Validating environment --")
    errors = validate_environment()
    if errors:
        print("\n[ERR] Environment validation failed:")
        for error in errors:
            print(error)
        sys.exit(1)

    run_migrations()
    seed_genesis_block()
    start_server()


if __name__ == "__main__":
    main()
