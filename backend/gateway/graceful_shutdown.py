"""Graceful shutdown for the Forge API process.

Registered handlers run from FastAPI lifespan teardown (after Uvicorn receives
SIGINT/SIGTERM and begins shutdown). Signal handling is owned by the ASGI server.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from backend.core.logger import forge_logger as logger

_shutdown_handlers: list[Callable] = []
_shutdown_in_progress = False


def is_shutting_down() -> bool:
    """True while graceful shutdown is running or after it has started."""
    return _shutdown_in_progress


def register_shutdown_handler(handler: Callable) -> None:
    """Register a handler to be called during graceful shutdown."""
    _shutdown_handlers.append(handler)


async def graceful_shutdown() -> None:
    """Run all registered shutdown handlers (idempotent)."""
    global _shutdown_in_progress

    if _shutdown_in_progress:
        logger.warning("Shutdown already in progress, skipping")
        return

    from backend.utils.shutdown_listener import request_process_shutdown

    request_process_shutdown()

    _shutdown_in_progress = True
    logger.info("Starting graceful shutdown...")

    for handler in _shutdown_handlers:
        try:
            if asyncio.iscoroutinefunction(handler):
                await handler()
            else:
                handler()
            logger.debug("Shutdown handler %s completed", handler.__name__)
        except Exception as e:
            logger.error(
                "Error in shutdown handler %s: %s", handler.__name__, e, exc_info=True
            )

    logger.info("Graceful shutdown completed")
