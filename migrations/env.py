"""Run migrations with application settings and registered model metadata."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import Settings
from app.db import models  # noqa: F401 -- registers all mapped tables
from app.db.base import Base
from app.db.session import get_database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Render SQL without connecting to PostgreSQL."""
    context.configure(
        url=get_database_url(Settings()),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations through a short-lived, unpooled connection."""
    engine = create_engine(
        get_database_url(Settings()),
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": 3},
    )
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                compare_server_default=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
