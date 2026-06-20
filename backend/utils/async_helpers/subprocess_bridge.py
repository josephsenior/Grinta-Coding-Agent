"""Bounded subprocess helpers with explicit sync/async entry points.

Sync tools and runtime worker threads use :func:`run_bounded_subprocess_sync`
(off the event loop).  Async middleware and services should ``await``
:func:`run_bounded_subprocess`` directly — never ``call_async_from_sync`` on
the loop thread.
"""

from __future__ import annotations

from backend.execution.utils.files.bounded_io import (
    BoundedResult,
    async_bounded_subprocess_exec,
)
from backend.utils.async_helpers.async_utils import call_async_from_sync

__all__ = ['run_bounded_subprocess', 'run_bounded_subprocess_sync']


async def run_bounded_subprocess(
    args: list[str],
    *,
    cwd: str | None = None,
    process_timeout: float = 30.0,
    max_bytes_per_stream: int = 2 * 1024 * 1024,
    stdin_data: bytes | str | None = None,
) -> BoundedResult:
    """Await a bounded subprocess without blocking the event loop."""
    return await async_bounded_subprocess_exec(
        args,
        cwd=cwd,
        process_timeout=process_timeout,
        max_bytes_per_stream=max_bytes_per_stream,
        stdin_data=stdin_data,
    )


def run_bounded_subprocess_sync(
    args: list[str],
    *,
    cwd: str | None = None,
    process_timeout: float = 30.0,
    max_bytes_per_stream: int = 2 * 1024 * 1024,
    stdin_data: bytes | str | None = None,
) -> BoundedResult:
    """Run a bounded subprocess from a sync/off-loop context."""
    bridge_timeout = process_timeout + 5.0
    return call_async_from_sync(
        async_bounded_subprocess_exec,
        bridge_timeout,
        args,
        cwd=cwd,
        process_timeout=process_timeout,
        max_bytes_per_stream=max_bytes_per_stream,
        stdin_data=stdin_data,
    )
