"""Alembic environment — async, config-driven.

Reads the database URL and SSL settings from app.core.config so migrations use
the exact same connection logic as the app. Imports app.models so that
`Base.metadata` is fully populated for autogenerate.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from app.core.database import create_engine
from app.models import Base  # noqa: F401 — populates Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
settings = get_settings()


def _run_sync_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine: AsyncEngine = create_engine(settings)
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
