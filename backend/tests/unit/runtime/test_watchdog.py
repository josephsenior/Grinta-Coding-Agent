"""Unit tests for backend.runtime.watchdog — RuntimeWatchdog."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch


from backend.runtime.watchdog import (
    RuntimeWatchdog,
    WatchedRuntime,
    _env_float,
)


# ── helpers ──────────────────────────────────────────────────────────


def _make_runtime(sid: str = "rt-1") -> MagicMock:
    rt = MagicMock()
    rt.sid = sid
    rt.event_stream = MagicMock()
    rt.event_stream.add_activity_listener = MagicMock(return_value="handle-1")
    rt.event_stream.remove_activity_listener = MagicMock()
    return rt


# ── _env_float ───────────────────────────────────────────────────────


class TestEnvFloat:
    def test_default(self):
        assert _env_float("___NONEXISTENT_VAR___", 42.0) == 42.0

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("__TEST_FLOAT__", "3.14")
        assert _env_float("__TEST_FLOAT__", 0.0) == 3.14

    def test_bad_value_returns_default(self, monkeypatch):
        monkeypatch.setenv("__TEST_BAD__", "not_a_number")
        assert _env_float("__TEST_BAD__", 99.0) == 99.0


# ── WatchedRuntime dataclass ─────────────────────────────────────────


class TestWatchedRuntime:
    def test_fields(self):
        rt = MagicMock()
        wr = WatchedRuntime(
            runtime=rt,
            key="warm",
            session_id="s1",
            acquired_at=1.0,
            last_activity=2.0,
            event_stream=MagicMock(),
            listener_handle="h1",
        )
        assert wr.key == "warm"
        assert wr.session_id == "s1"
        assert wr.acquired_at == 1.0
        assert wr.last_activity == 2.0
        assert wr.listener_handle == "h1"


# ── RuntimeWatchdog — core behaviour ─────────────────────────────────


@patch("backend.runtime.watchdog.call_async_disconnect")
class TestRuntimeWatchdogWatch:
    def test_watch_and_stats(self, mock_disc):
        wd = RuntimeWatchdog(max_active_seconds=9999, poll_interval=9999)
        try:
            rt = _make_runtime("rt-1")
            wd.watch_runtime(rt, key="warm", session_id="s1")

            assert wd.stats() == {"warm": 1}
        finally:
            wd._stop_event.set()
            wd._tick.set()
            wd._thread.join(timeout=2)

    def test_unwatch_removes(self, mock_disc):
        wd = RuntimeWatchdog(max_active_seconds=9999, poll_interval=9999)
        try:
            rt = _make_runtime("rt-1")
            wd.watch_runtime(rt, key="warm", session_id="s1")
            assert wd.stats() == {"warm": 1}

            wd.unwatch_runtime(rt)
            assert wd.stats() == {}
        finally:
            wd._stop_event.set()
            wd._tick.set()
            wd._thread.join(timeout=2)

    def test_watch_same_sid_updates(self, mock_disc):
        wd = RuntimeWatchdog(max_active_seconds=9999, poll_interval=9999)
        try:
            rt = _make_runtime("rt-1")
            wd.watch_runtime(rt, key="warm", session_id="s1")
            wd.watch_runtime(rt, key="warm2", session_id="s2")

            # Only one entry; key should be updated
            assert len(wd._watched) == 1
            assert wd._watched["rt-1"].key == "warm2"
        finally:
            wd._stop_event.set()
            wd._tick.set()
            wd._thread.join(timeout=2)

    def test_watch_disabled_when_max_zero(self, mock_disc):
        wd = RuntimeWatchdog(max_active_seconds=0, poll_interval=9999)
        try:
            rt = _make_runtime("rt-1")
            wd.watch_runtime(rt, key="warm", session_id="s1")
            assert wd.stats() == {}
        finally:
            wd._stop_event.set()
            wd._tick.set()
            wd._thread.join(timeout=2)

    def test_watch_no_event_stream(self, mock_disc):
        wd = RuntimeWatchdog(max_active_seconds=9999, poll_interval=9999)
        try:
            rt = MagicMock()
            rt.sid = "rt-1"
            rt.event_stream = None
            wd.watch_runtime(rt, key="warm", session_id="s1")
            assert wd.stats() == {}
        finally:
            wd._stop_event.set()
            wd._tick.set()
            wd._thread.join(timeout=2)


@patch("backend.runtime.watchdog.call_async_disconnect")
class TestRuntimeWatchdogHeartbeat:
    def test_heartbeat_updates_activity(self, mock_disc):
        wd = RuntimeWatchdog(max_active_seconds=9999, poll_interval=9999)
        try:
            rt = _make_runtime("rt-1")
            wd.watch_runtime(rt, key="warm", session_id="s1")
            old_activity = wd._watched["rt-1"].last_activity

            time.sleep(0.01)
            wd.heartbeat("rt-1")
            assert wd._watched["rt-1"].last_activity > old_activity
        finally:
            wd._stop_event.set()
            wd._tick.set()
            wd._thread.join(timeout=2)

    def test_heartbeat_noop_for_unknown(self, mock_disc):
        wd = RuntimeWatchdog(max_active_seconds=9999, poll_interval=9999)
        try:
            wd.heartbeat("nonexistent")  # should not raise
        finally:
            wd._stop_event.set()
            wd._tick.set()
            wd._thread.join(timeout=2)

    def test_heartbeat_disabled_when_max_zero(self, mock_disc):
        wd = RuntimeWatchdog(max_active_seconds=0, poll_interval=9999)
        try:
            wd.heartbeat("whatever")  # should return immediately
        finally:
            wd._stop_event.set()
            wd._tick.set()
            wd._thread.join(timeout=2)


@patch("backend.runtime.watchdog.call_async_disconnect")
class TestRuntimeWatchdogConfigure:
    def test_configure_updates(self, mock_disc):
        wd = RuntimeWatchdog(max_active_seconds=100, poll_interval=10)
        try:
            wd.configure(max_active_seconds=200, poll_interval=5)
            assert wd._max_active_seconds == 200
            assert wd._poll_interval == 5
        finally:
            wd._stop_event.set()
            wd._tick.set()
            wd._thread.join(timeout=2)

    def test_configure_partial(self, mock_disc):
        wd = RuntimeWatchdog(max_active_seconds=100, poll_interval=10)
        try:
            wd.configure(max_active_seconds=300)
            assert wd._max_active_seconds == 300
            assert wd._poll_interval == 10  # unchanged
        finally:
            wd._stop_event.set()
            wd._tick.set()
            wd._thread.join(timeout=2)


@patch("backend.runtime.watchdog.call_async_disconnect")
class TestRuntimeWatchdogSetIdleCleanup:
    def test_set_pool_with_cleanup(self, mock_disc):
        wd = RuntimeWatchdog(max_active_seconds=9999, poll_interval=9999)
        try:
            pool = MagicMock()
            pool.cleanup_expired = MagicMock(return_value=0)
            wd.set_idle_cleanup(pool)
            assert wd._cleanup_hook is pool.cleanup_expired
        finally:
            wd._stop_event.set()
            wd._tick.set()
            wd._thread.join(timeout=2)

    def test_set_none_clears(self, mock_disc):
        wd = RuntimeWatchdog(max_active_seconds=9999, poll_interval=9999)
        try:
            wd._cleanup_hook = lambda: 0
            wd.set_idle_cleanup(None)
            assert wd._cleanup_hook is None
        finally:
            wd._stop_event.set()
            wd._tick.set()
            wd._thread.join(timeout=2)

    def test_pool_without_cleanup_attr(self, mock_disc):
        wd = RuntimeWatchdog(max_active_seconds=9999, poll_interval=9999)
        try:
            pool = MagicMock(spec=[])  # no cleanup_expired
            wd.set_idle_cleanup(pool)
            assert wd._cleanup_hook is None
        finally:
            wd._stop_event.set()
            wd._tick.set()
            wd._thread.join(timeout=2)


@patch("backend.runtime.watchdog.call_async_disconnect")
class TestRuntimeWatchdogEnforceDeadlines:
    def test_terminates_overdue_runtime(self, mock_disc):
        wd = RuntimeWatchdog(max_active_seconds=0.001, poll_interval=9999)
        try:
            rt = _make_runtime("rt-1")
            wd.watch_runtime(rt, key="warm", session_id="s1")

            # Artificially age the last_activity
            wd._watched["rt-1"].last_activity = time.time() - 10

            wd._enforce_deadlines()

            assert wd.stats() == {}
            mock_disc.assert_called_once_with(rt)
        finally:
            wd._stop_event.set()
            wd._tick.set()
            wd._thread.join(timeout=2)

    def test_no_termination_when_fresh(self, mock_disc):
        wd = RuntimeWatchdog(max_active_seconds=9999, poll_interval=9999)
        try:
            rt = _make_runtime("rt-1")
            wd.watch_runtime(rt, key="warm", session_id="s1")
            wd._enforce_deadlines()

            assert wd.stats() == {"warm": 1}
            mock_disc.assert_not_called()
        finally:
            wd._stop_event.set()
            wd._tick.set()
            wd._thread.join(timeout=2)

    def test_enforce_disabled_when_max_zero(self, mock_disc):
        wd = RuntimeWatchdog(max_active_seconds=0, poll_interval=9999)
        try:
            wd._enforce_deadlines()  # should be a no-op
            mock_disc.assert_not_called()
        finally:
            wd._stop_event.set()
            wd._tick.set()
            wd._thread.join(timeout=2)
