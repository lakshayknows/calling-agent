"""Health & readiness endpoints.

`/health` is a cheap liveness probe (process is up). `/health/ready` actually
pings Postgres and Redis so Railway / load balancers only route traffic when
dependencies are reachable.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import text

from app.api.deps import DBSession, RedisDep, SettingsDep

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(settings: SettingsDep) -> dict[str, str]:
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
    }


@router.get("/health/ready")
async def readiness(request: Request, db: DBSession, redis: RedisDep) -> dict[str, object]:
    checks: dict[str, str] = {}

    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - report, don't crash the probe
        checks["database"] = f"error: {exc.__class__.__name__}"

    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {exc.__class__.__name__}"

    # Informational: whether the Pipecat voice stack is warmed (not part of the
    # healthy gate — the REST API is fine before voice finishes preloading).
    voice_ready = bool(getattr(request.app.state, "voice_ready", False))

    healthy = all(v == "ok" for v in checks.values())
    return {
        "status": "ready" if healthy else "degraded",
        "checks": checks,
        "voice": "ready" if voice_ready else "loading",
    }
