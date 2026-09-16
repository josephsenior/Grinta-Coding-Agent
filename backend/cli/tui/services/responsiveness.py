"""Low-frequency event-loop lag diagnostics, without recording user content."""

from __future__ import annotations

import asyncio
import time

from backend.cli.tui.constants import _tui_logger


async def monitor_responsiveness() -> None:
    """Report stalls over 100 ms; cancellation follows the screen's lifetime."""
    while True:
        started = time.monotonic()
        await asyncio.sleep(0.5)
        lag_ms = max(0.0, time.monotonic() - started - 0.5) * 1000
        if lag_ms >= 100:
            _tui_logger.debug('tui_loop_lag_ms=%.1f', lag_ms)
