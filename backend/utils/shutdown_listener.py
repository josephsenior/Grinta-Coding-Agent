"""This module monitors the app for shutdown signals. This exists because the atexit module.

does not play nocely with stareltte / uvicorn shutdown signals.
"""

from __future__ import annotations

import asyncio
import signal
import threading
import time
from collections.abc import Callable
from types import FrameType
from typing import cast
from uuid import UUID, uuid4

from uvicorn.server import HANDLED_SIGNALS

from backend.core.logger import forge_logger as logger

_Handler = Callable[[int, FrameType | None], None]

_should_exit: bool | None = None
_shutdown_listeners: dict[UUID, Callable] = {}


def _register_signal_handler(sig: signal.Signals) -> None:
    """Register a signal handler for shutdown signals.

    Args:
        sig: The signal to register a handler for.

    """
    import sys as _sys

    _mod = _sys.modules[__name__]
    handler_candidate: object = _mod.signal.getsignal(sig)
    fallback_handler: _Handler | None = None
    if callable(handler_candidate):
        fallback_handler = cast(_Handler, handler_candidate)
    elif handler_candidate == signal.SIG_DFL:
        fallback_handler = signal.default_int_handler

    def handler(signum: int, frame: FrameType | None) -> None:
        """Signal handler that sets shutdown flag and invokes cleanup callback."""
        logger.debug("shutdown_signal:%s", sig)
        if not _should_exit:
            # Set global flag and invoke listeners once
            globals()["_should_exit"] = True
            listeners = list(_shutdown_listeners.values())
            for listener in listeners:
                try:
                    listener()
                except Exception:
                    logger.exception("Error calling shutdown listener")
        if fallback_handler is not None:
            fallback_handler(signum, frame)

    _mod.signal.signal(sig, handler)


def _register_signal_handlers() -> None:
    """Register all shutdown signal handlers."""
    # Only register once per process
    global _should_exit
    if _should_exit is not None:
        return
    _should_exit = False
    logger.debug("_register_signal_handlers")
    if threading.current_thread() is threading.main_thread():
        logger.debug("_register_signal_handlers:main_thread")
        for sig in HANDLED_SIGNALS:
            _register_signal_handler(sig)
    else:
        logger.debug("_register_signal_handlers:not_main_thread")


def should_exit() -> bool:
    """Check if the application should exit due to shutdown signals.

    Returns:
        bool: True if the application should exit, False otherwise.

    """
    _register_signal_handlers()
    return bool(_should_exit)


def should_continue() -> bool:
    """Check if the application should continue running.

    Returns:
        bool: True if the application should continue, False if it should exit.

    """
    _register_signal_handlers()
    return not _should_exit


def sleep_if_should_continue(delay: float) -> None:
    """Sleep for the specified delay, waking up early if shutdown is requested.

    Args:
        delay: The maximum time to sleep in seconds.

    """
    if delay <= 1:
        time.sleep(delay)
        return
    start_time = time.time()
    while time.time() - start_time < delay and should_continue():
        time.sleep(1)


async def async_sleep_if_should_continue(delay: float) -> None:
    """Asynchronously sleep for the specified delay, waking up early if shutdown is requested.

    Args:
        delay: The maximum time to sleep in seconds.

    """
    if delay <= 1:
        await asyncio.sleep(delay)
        return
    start_time = time.time()
    while time.time() - start_time < delay and should_continue():
        await asyncio.sleep(1)


def add_shutdown_listener(callable: Callable) -> UUID:
    """Add a shutdown listener function.

    Args:
        callable: Function to call when shutdown signals are received.

    Returns:
        UUID: Unique identifier for the listener.

    """
    id_ = uuid4()
    _shutdown_listeners[id_] = callable
    return id_


def remove_shutdown_listener(id_: UUID) -> bool:
    """Remove a shutdown listener by its ID.

    Args:
        id_: The UUID of the listener to remove.

    Returns:
        bool: True if the listener was found and removed, False otherwise.

    """
    return _shutdown_listeners.pop(id_, None) is not None
