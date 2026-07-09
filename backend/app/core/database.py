"""Async SQLAlchemy 2.0 engine, session factory, and FastAPI dependency.

Supabase requires TLS. asyncpg negotiates SSL automatically when the server
enforces it, but we pass an explicit SSL context for reliability across
networks. Business code should depend on `get_db` (see app.api.deps) rather
than importing the engine directly.
"""

from __future__ import annotations

import ssl
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


def _build_connect_args(settings: Settings) -> dict[str, object]:
    """SSL is required for Supabase; skip it for local/plain connections.

    By default we encrypt without verifying the certificate (equivalent to
    libpq `sslmode=require`), because Supabase's pooler cert fails full
    verification. Set `db_ssl_verify=true` to require a verifiable cert.
    """
    url = settings.database_url
    if "supabase" in url or settings.is_production:
        ctx = ssl.create_default_context()
        if not settings.db_ssl_verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return {"ssl": ctx}
    return {}


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        connect_args=_build_connect_args(settings),
    )


class Database:
    """Holds the engine + session factory for the app lifespan."""

    def __init__(self, settings: Settings) -> None:
        self.engine: AsyncEngine = create_engine(settings)
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            autoflush=False,
        )

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Yield a session, committing on success and rolling back on error."""
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
