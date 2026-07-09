"""FastAPI application factory and entrypoint.

Startup wires the shared Database and Redis singletons onto `app.state`;
shutdown disposes them cleanly. Run locally with:

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.database import Database
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis, create_redis

log = get_logger(__name__)


async def _preload_voice(app: FastAPI) -> None:
    """Import Pipecat and warm the Silero VAD model in a worker thread."""
    def _warm() -> None:
        import app.voice.pipeline  # noqa: F401 - triggers the heavy Pipecat import
        from pipecat.audio.vad.silero import SileroVADAnalyzer

        SileroVADAnalyzer()  # load the onnx model once

    try:
        await asyncio.to_thread(_warm)
        app.state.voice_ready = True
        log.info("voice_preloaded")
    except Exception:
        log.error("voice_preload_failed", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(debug=settings.debug, json_logs=settings.is_production)

    if settings.run_migrations_on_startup:
        from app.core.migrations import run_migrations

        await asyncio.to_thread(run_migrations)
        log.info("migrations_applied")

    app.state.db = Database(settings)
    app.state.redis = create_redis(settings)

    # Warm the heavy Pipecat import + VAD model off the event loop so the first
    # call starts fast instead of paying ~30-40s of import latency mid-call.
    app.state.voice_ready = False
    if settings.preload_voice:
        app.state._preload_task = asyncio.create_task(_preload_voice(app))

    log.info("startup_complete", environment=settings.environment)

    try:
        yield
    finally:
        await close_redis(app.state.redis)
        await app.state.db.dispose()
        log.info("shutdown_complete")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/", tags=["root"])
    async def root() -> dict[str, str]:
        return {"service": settings.app_name, "docs": "/docs"}

    return app


app = create_app()
