"""Tests for AppState diagnostics snapshots without constructing full AppState()."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from backend.gateway.app_state import (
    AppState,
    _close_and_clear,
    _get_socketio_cors_origins,
)


def _bare_app_state() -> AppState:
    state = object.__new__(AppState)
    state._lock = threading.Lock()
    state._state_restore_records = {}
    state._startup_snapshot = None
    return state


def test_record_state_restore_orders_recent_first_in_snapshot() -> None:
    st = _bare_app_state()
    with patch("backend.gateway.app_state.time.time", side_effect=[10.0, 20.0, 30.0]):
        st.record_state_restore("a", source="s1", path="/p1")
        st.record_state_restore("b", source="s2", path="/p2")
        st.record_state_restore("c", source="s3", path="/p3")

    snap = st.get_state_restore_snapshot(limit=10)
    assert snap["count"] == 3
    assert [r["sid"] for r in snap["recent"]] == ["c", "b", "a"]


def test_get_state_restore_snapshot_respects_limit_and_zero_limit() -> None:
    st = _bare_app_state()
    with patch("backend.gateway.app_state.time.time", side_effect=[1.0, 2.0]):
        st.record_state_restore("x", source="s", path="/p")
        st.record_state_restore("y", source="s", path="/p")

    snap1 = st.get_state_restore_snapshot(limit=100)
    assert snap1["count"] == 2
    snap2 = st.get_state_restore_snapshot(limit=1)
    assert len(snap2["recent"]) == 1
    assert snap2["recent"][0]["sid"] == "y"

    snap3 = st.get_state_restore_snapshot(limit=-3)
    assert snap3["recent"] == []


def test_record_state_restore_trims_past_fifty_entries() -> None:
    st = _bare_app_state()
    times = [float(i) for i in range(60)]
    with patch("backend.gateway.app_state.time.time", side_effect=times):
        for i in range(55):
            st.record_state_restore(f"id-{i}", source="src", path="/p")

    assert len(st._state_restore_records) == 50


def test_startup_snapshot_round_trip_and_defensive_copy() -> None:
    st = _bare_app_state()
    st.record_startup_snapshot({"host": "127.0.0.1", "resolved_port": 3000})

    out = st.get_startup_snapshot()
    assert out["host"] == "127.0.0.1"
    assert out["resolved_port"] == 3000
    assert "recorded_at" in out

    out["mutated"] = True
    out2 = st.get_startup_snapshot()
    assert "mutated" not in out2


def test_close_and_clear_invokes_close_when_present() -> None:
    obj = MagicMock()

    _close_and_clear(obj, "test")

    obj.close.assert_called_once_with()


def test_close_and_clear_noop_for_none() -> None:
    _close_and_clear(None, "none")  # no exception


def test_close_and_clear_swallows_close_errors() -> None:

    class Bad:
        def close(self) -> None:
            raise OSError("no")

    _close_and_clear(Bad(), "bad")  # errors logged at debug, must not raise


def test_get_socketio_cors_origins_defaults_to_wildcard(monkeypatch) -> None:
    monkeypatch.delenv("APP_CORS_ORIGINS", raising=False)

    assert _get_socketio_cors_origins() == "*"


def test_get_socketio_cors_origins_reads_app_env(monkeypatch) -> None:
    monkeypatch.setenv(
        "APP_CORS_ORIGINS",
        "https://example.com, https://app.example.com",
    )

    assert _get_socketio_cors_origins() == [
        "https://example.com",
        "https://app.example.com",
    ]
