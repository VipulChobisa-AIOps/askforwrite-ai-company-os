"""Database configuration shared by the API and Alembic migrations."""

import os
from collections.abc import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

load_dotenv()

APP_ENV = os.environ.get("APP_ENV", "development").casefold()
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./company_os.db")
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://",
        "postgresql+psycopg://",
        1,
    )


def validate_database_configuration(environment: str, database_url: str) -> None:
    env = environment.casefold()
    if env != "development" and not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        if os.environ.get("ALLOW_SQLITE_PRODUCTION", "").lower() in ("true", "1", "yes"):
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
    _connect_args = {}
    # Enforce SSL in production
    if APP_ENV != "development":
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