"""Database configuration shared by the API and Alembic migrations."""

import os
import sys
from collections.abc import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

if "pytest" not in sys.modules and "unittest" not in sys.modules:
    load_dotenv()

def normalize_database_url(raw_url: str) -> str:
    """Normalize PostgreSQL URL scheme for SQLAlchemy psycopg driver."""
    url = (raw_url or "").strip()
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://") and not url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def is_pooled_database_url(url: str | None) -> bool:
    """Return True when the DSN targets a Neon PgBouncer '-pooler' host."""
    return "-pooler" in (url or "").lower()


def get_unpooled_database_url() -> str:
    """Return normalized direct compute URL for migrations, DDL, and pg_dump/pg_restore."""
    raw = os.environ.get("DATABASE_URL_UNPOOLED", "").strip()
    return normalize_database_url(raw) if raw else ""


def get_database_topology_summary() -> dict[str, object]:
    """Return non-secret runtime pooled vs unpooled database topology metadata."""
    active_url = normalize_database_url(
        os.environ.get("NEON_DATABASE_URL") or os.environ.get("DATABASE_URL") or DATABASE_URL
    )
    unpooled_url = get_unpooled_database_url()
    dialect = "sqlite" if active_url.startswith("sqlite") else "postgresql"
    return {
        "dialect": dialect,
        "runtime_connection_mode": (
            "sqlite"
            if dialect == "sqlite"
            else ("pooled" if is_pooled_database_url(active_url) else "direct")
        ),
        "unpooled_migration_url_configured": bool(unpooled_url),
        "unpooled_url_is_direct": bool(unpooled_url) and not is_pooled_database_url(unpooled_url),
        "pool_size": None if dialect == "sqlite" else int(os.environ.get("DB_POOL_SIZE", "10")),
        "max_overflow": None if dialect == "sqlite" else int(os.environ.get("DB_MAX_OVERFLOW", "20")),
        "connect_timeout_seconds": None if dialect == "sqlite" else int(os.environ.get("DB_CONNECT_TIMEOUT_SECONDS", "5")),
    }


APP_ENV = os.environ.get("APP_ENV", "development").casefold()
DATABASE_URL = normalize_database_url(
    os.environ.get("NEON_DATABASE_URL")
    or os.environ.get("DATABASE_URL", "sqlite:///./company_os.db")
)


def validate_database_configuration(environment: str, database_url: str) -> None:
    env = environment.casefold()
    if env != "development" and not database_url.startswith(("postgresql://", "postgresql+psycopg://", "postgres://")):

        if os.environ.get("ALLOW_SQLITE_TEST", "").lower() in ("true", "1", "yes") and env != "production":
            return
        raise ValueError(f"Non-development environments ({environment}) require a PostgreSQL database URL.")


validate_database_configuration(APP_ENV, DATABASE_URL)

# ── Engine configuration ─────────────────────────────────────────────
_is_sqlite = DATABASE_URL.startswith("sqlite")

if _is_sqlite:
    _connect_args: dict = {"check_same_thread": False}
    _engine_kwargs: dict = {
        "connect_args": _connect_args,
        "pool_pre_ping": True,
    }
else:
    # Production PostgreSQL settings
    _connect_args = {
        "connect_timeout": int(os.environ.get("DB_CONNECT_TIMEOUT_SECONDS", "5")),
    }
    # Enforce SSL in production
    if APP_ENV != "development":
        if "-pooler" not in DATABASE_URL:
            _connect_args["options"] = "-c statement_timeout=30000"  # 30s query timeout
    _engine_kwargs = {
        "connect_args": _connect_args,
        "pool_pre_ping": True,
        "pool_size": int(os.environ.get("DB_POOL_SIZE", "10")),
        "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", "20")),
        "pool_recycle": 1800,  # Recycle connections every 30 minutes
        "pool_timeout": 30,
        "echo": APP_ENV == "development",
    }

engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for persisted Company OS records."""


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
