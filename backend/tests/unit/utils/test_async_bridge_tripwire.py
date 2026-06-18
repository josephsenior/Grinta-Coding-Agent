"""Tests for the on-loop bridge tripwire in ``call_async_from_sync``.

The tripwire turns the silent-hang failure mode — a synchronous bridge that
blocks the event-loop thread — into a loud, attributable log line (or a hard
error in strict mode), while leaving the correct off-loop offload pattern
untouched.
"""

from __future__ import annotations

import logging

import pytest

from backend.utils.async_helpers import async_utils as au


class _Cap(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def msg_types(self) -> set[str]:
        return {getattr(r, 'msg_type', '') for r in self.records}


@pytest.fixture
def cap():
    handler = _Cap()
    logger = au._logger
    prev = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    au._seen_on_loop_bridges.clear()
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev)


async def _quick() -> int:
    return 42


async def _quick2() -> int:
    return 7


def test_off_loop_call_is_silent(cap):
    # Plain sync context → no running loop on this thread → intended usage.
    result = au.call_async_from_sync(_quick, 5.0)
    assert result == 42
    assert 'BRIDGE_ON_LOOP' not in cap.msg_types()


async def test_on_loop_call_warns(cap):
    # Invoked from within the running test loop → blocks the loop → flagged.
    result = au.call_async_from_sync(_quick, 5.0)
    assert result == 42
    assert 'BRIDGE_ON_LOOP' in cap.msg_types()
    rec = next(r for r in cap.records if getattr(r, 'msg_type', '') == 'BRIDGE_ON_LOOP')
    assert getattr(rec, 'bridge', '') == '_quick'
    assert 'site' in rec.__dict__


async def test_on_loop_repeat_is_throttled(cap):
    # Both calls share one source line → one call site → throttled to a single
    # WARNING (the repeat is demoted to DEBUG).
    for _ in range(2):
        au.call_async_from_sync(_quick, 5.0)
    warnings = [
        r
        for r in cap.records
        if getattr(r, 'msg_type', '') == 'BRIDGE_ON_LOOP'
        and r.levelno == logging.WARNING
    ]
    assert len(warnings) == 1


async def test_strict_mode_raises(cap, monkeypatch):
    monkeypatch.setattr(au, '_STRICT_LOOP_BRIDGE', True)
    with pytest.raises(RuntimeError, match='blocks the loop thread'):
        au.call_async_from_sync(_quick, 5.0)


async def test_correct_offload_pattern_is_not_flagged(cap):
    # call_coro_in_bg_thread offloads the bridge onto a worker thread where no
    # loop is running, so it must NOT trip the wire.
    await au.call_coro_in_bg_thread(_quick2, 5.0)
    assert 'BRIDGE_ON_LOOP' not in cap.msg_types()
