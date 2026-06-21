"""Unit tests for live retry countdown in the HUD."""

from __future__ import annotations

import time

from backend.cli.display.hud import HUDBar
from backend.cli.tui.screen.state import ScreenStateMixin


class _CountdownHost(ScreenStateMixin):
    def __init__(self) -> None:
        self._hud = HUDBar()
        self._is_unmounted = False
        self._retry_countdown_deadline = None
        self._retry_countdown_attempt = 1
        self._retry_countdown_max_attempts = 1
        self._retry_countdown_reason = ''
        self._retry_countdown_source = ''
        self._retry_summary = 'No retry activity'
        self._retry_meta = 'Idle'
        self._retry_active = False

    def query_one(self, *_args, **_kwargs):  # pragma: no cover - not used here
        raise NotImplementedError


def test_retry_countdown_ticks_down_each_second() -> None:
    host = _CountdownHost()
    host.arm_retry_countdown(
        attempt=1,
        max_attempts=5,
        delay_seconds=3.0,
        reason='RateLimitError',
    )
    host._tick_retry_countdown()
    assert host._hud.state.agent_state_label == 'Backoff 1/5 (retrying in 3s)'

    host._retry_countdown_deadline = time.monotonic() + 1.4
    host._tick_retry_countdown()
    assert host._hud.state.agent_state_label == 'Backoff 1/5 (retrying in 2s)'

    host._retry_countdown_deadline = time.monotonic() - 0.01
    host._tick_retry_countdown()
    assert host._hud.state.agent_state_label == 'Backoff 1/5 (retrying now)'
