"""Graceful shutdown handler for Forge server.

Ensures proper cleanup of resources on shutdown:
- Stop accepting new requests
- Wait for in-flight requests to complete
- Close Socket.IO connections gracefully
- Clean up runtime resources
- Close database connections
- Flush logs
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable

from backend.core.logger import FORGE_logger as logger

_shutdown_handlers: list[Callable] = []
_shutdown_in_progress = False
_shutdown_timeout = 30  # seconds


def register_shutdown_handler(handler: Callable) -> None:
    """Register a handler to be called during graceful shutdown.

    Args:
        handler: Async or sync function to call during shutdown
    """
    _shutdown_handlers.append(handler)


async def graceful_shutdown() -> None:
    """Perform graceful shutdown of all registered resources."""
    global _shutdown_in_progress

    if _shutdown_in_progress:
        logger.warning("Shutdown already in progress, skipping")
        return

    _shutdown_in_progress = True
    logger.info("Starting graceful shutdown...")

    # Execute all shutdown handlers
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


def setup_signal_handlers() -> None:
    """Setup signal handlers for graceful shutdown."""
    import signal as signal_module

    def signal_handler(signum, frame):
        """Handle shutdown signals."""
        logger.info("Received signal %s, initiating graceful shutdown...", signum)
        # Run graceful shutdown in event loop
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Create task and let event loop handle it - don't exit immediately
            task = asyncio.create_task(graceful_shutdown())
            # Wait for shutdown to complete
            loop.run_until_complete(task)
        else:
            # Run shutdown directly if loop is not running
            loop.run_until_complete(graceful_shutdown())
        sys.exit(0)

    # Register handlers for common shutdown signals
    signal_module.signal(signal_module.SIGTERM, signal_handler)
    signal_module.signal(signal_module.SIGINT, signal_handler)


# Auto-register signal handlers on import
try:
    setup_signal_handlers()
except ValueError:
    # signal() only works in main thread — skip in test/worker threads
    pass
