"""Structured logging setup.

JSON logs in production (machine-parseable for Railway/observability), pretty
console logs in development. Call `configure_logging()` once at startup, then
obtain loggers anywhere with `structlog.get_logger()`.
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(*, debug: bool, json_logs: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_logs:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging (uvicorn, sqlalchemy) through the same handler.
    handler = logging.StreamHandler(sys.stdout)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for noisy in ("uvicorn.access", "sqlalchemy.engine.Engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING if not debug else logging.INFO)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
