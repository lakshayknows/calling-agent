"""Programmatic Alembic upgrade, for platforms without a shell/pre-deploy hook.

Render's free tier has no Shell or Pre-Deploy Command, and the Supabase DB is
only reachable from inside Render — so migrations can't be run manually. Instead
the app applies them on startup (see app.main.lifespan). `alembic upgrade head`
is idempotent: a no-op once the DB is already at head.

Must run in a worker thread (via asyncio.to_thread): Alembic's env.py calls
asyncio.run(), which cannot execute inside the app's already-running event loop.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

# app/core/migrations.py -> parents[2] == backend root (holds alembic.ini + alembic/)
BACKEND_ROOT = Path(__file__).resolve().parents[2]


def run_migrations() -> None:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.upgrade(cfg, "head")
