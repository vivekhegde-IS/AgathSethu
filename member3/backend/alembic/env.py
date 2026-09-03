"""
Alembic environment configuration for AGHAT SETHU.
Reads DATABASE_URL from app settings (which loads from .env).
"""

from logging.config import fileConfig
import sys
import os

# Ensure backend/ is on the path so we can import app.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.core.database import Base

# Import all models so their metadata is registered
import app.models.models  # noqa: F401

# Alembic Config object — provides access to alembic.ini values
config = context.config

# Override sqlalchemy.url with value from settings (reads from .env)
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Set up loggers
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no live DB connection needed)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (with live DB connection)."""
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
