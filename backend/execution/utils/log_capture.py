"""Context manager utilities for capturing runtime log output."""

import io
import logging
from contextlib import asynccontextmanager


@asynccontextmanager
async def capture_logs(logger_name, level=logging.ERROR):
    """Capture log output for a specific logger.

    Temporarily replaces logger handlers to capture log messages to a StringIO buffer.
    Restores original handlers and level on exit.

    Args:
        logger_name: Name of logger to capture
        level: Minimum log level to capture

    Yields:
        StringIO buffer containing captured log messages

    """
    logger = logging.getLogger(logger_name)
    original_handlers = logger.handlers[:]
    original_level = logger.level
    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(level)
    logger.handlers = [handler]
    logger.setLevel(level)
    try:
        yield log_capture
    finally:
        logger.handlers = original_handlers
        logger.setLevel(original_level)
