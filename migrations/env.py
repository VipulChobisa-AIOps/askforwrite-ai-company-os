import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db import models  # noqa: F401
from app.db.database import DATABASE_URL, Base

config = context.config

# Prioritize unpooled direct database URL for migration operations and DDL execution
_raw_unpooled = (
    os.environ.get("DATABASE_URL_UNPOOLED")
    or config.get_main_option("DATABASE_URL_UNPOOLED")
)

if _raw_unpooled:
    _migration_url = _raw_unpooled
    if _migration_url.startswith("postgres://"):
        _migration_url = _migration_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif _migration_url.startswith("postgresql://") and not _migration_url.startswith("postgresql+psycopg://"):
        _migration_url = _migration_url.replace("postgresql://", "postgresql+psycopg://", 1)
else:
    _migration_url = DATABASE_URL

config.set_main_option("sqlalchemy.url", _migration_url.replace("%", "%%"))
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=_migration_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()