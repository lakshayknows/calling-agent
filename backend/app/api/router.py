"""Top-level API router. Each feature registers its router here."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import api_keys, auth, health, organizations, users

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(users.router)
api_router.include_router(api_keys.router)
