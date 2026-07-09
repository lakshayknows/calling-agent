"""Async Redis client wrapper.

Used for active-call state, queues, sessions, rate limiting, and temporary
memory. The client is created once at startup and shared (redis-py maintains an
internal connection pool). Depend on it via app.api.deps.get_redis.
"""

from __future__ import annotations

from redis.asyncio import Redis, from_url

from app.core.config import Settings


def create_redis(settings: Settings) -> Redis:
    # decode_responses=True → str in/out, which is what all our call-sites want.
    # rediss:// URLs enable TLS automatically (Upstash).
    return from_url(
        settings.redis_url,
        decode_responses=True,
        health_check_interval=30,
        socket_connect_timeout=5,
        retry_on_timeout=True,
    )


async def close_redis(client: Redis) -> None:
    await client.aclose()
