"""Application configuration.

Loaded once at startup from environment variables / .env. Everything downstream
depends on a validated `Settings` instance obtained via `get_settings()`.

The raw `.env` shipped with this project has two quirks this module normalizes:
  * REDIS_URL may be a shell command (`redis-cli --tls -u redis://...`) — we
    extract the real URL and upgrade it to the TLS scheme (`rediss://`).
  * DATABASE_URL uses the sync `postgresql://` scheme — we rewrite it to the
    async `postgresql+asyncpg://` driver used by SQLAlchemy's async engine.
"""

from __future__ import annotations

import re
from functools import lru_cache

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- App -------------------------------------------------------------
    app_name: str = "Agentic Calling Platform"
    environment: str = Field(default="development")
    debug: bool = Field(default=False)
    api_v1_prefix: str = "/api/v1"

    # Comma-separated list of allowed CORS origins.
    cors_origins: str = Field(default="http://localhost:3000")

    # ---- Security (used from Feature 2) ---------------------------------
    jwt_secret: str = Field(default="CHANGE_ME_IN_PRODUCTION_use_a_long_random_string")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30

    # ---- Datastores ------------------------------------------------------
    database_url: str = Field(...)
    db_echo: bool = Field(default=False)
    db_pool_size: int = 10
    db_max_overflow: int = 20

    redis_url: str = Field(...)

    # ---- Providers -------------------------------------------------------
    sarvam_api_key: str = Field(default="")
    plivo_auth_id: str = Field(default="")
    plivo_auth_token: str = Field(default="")
    openrouter_api_key: str = Field(default="")

    # Cloudflare R2 (used from Feature 5 — recordings). Optional until then.
    r2_account_id: str = Field(default="")
    r2_access_key_id: str = Field(default="")
    r2_secret_access_key: str = Field(default="")
    r2_bucket: str = Field(default="")
    r2_public_base_url: str = Field(default="")

    # Public base URL of THIS backend, used to build Plivo webhook/answer URLs.
    public_base_url: str = Field(default="http://localhost:8000")

    # ------------------------------------------------------------------ #
    # Normalizers
    # ------------------------------------------------------------------ #
    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, v: str) -> str:
        v = v.strip()
        # Rewrite sync scheme -> async asyncpg driver.
        if v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql+asyncpg://", 1)
        return v

    @field_validator("redis_url")
    @classmethod
    def _normalize_redis_url(cls, v: str) -> str:
        v = v.strip()
        # The provided value may be a shell command like:
        #   redis-cli --tls -u redis://default:pwd@host:6379
        # Extract the embedded redis URL if present.
        match = re.search(r"rediss?://\S+", v)
        wants_tls = "--tls" in v or v.startswith("rediss://")
        if match:
            v = match.group(0)
        # Upgrade to TLS scheme when TLS was requested (Upstash requires it).
        if wants_tls and v.startswith("redis://"):
            v = v.replace("redis://", "rediss://", 1)
        return v

    # ------------------------------------------------------------------ #
    # Derived values
    # ------------------------------------------------------------------ #
    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    """Return a cached, validated Settings instance."""
    return Settings()  # type: ignore[call-arg]
