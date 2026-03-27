"""Tests for backend.api.session.session_manager and manager singleton."""

from __future__ import annotations

from types import SimpleNamespace

from backend.api.session.manager import session_manager
from backend.api.session.session_manager import SessionManager


def test_manager_module_exports_session_manager_singleton() -> None:
    assert isinstance(session_manager, SessionManager)


def test_session_manager_add_get_list_remove() -> None:
    sm = SessionManager()
    s = SimpleNamespace(sid="sid-1", user_id="user-a")
    sm.add_session(s)
    assert sm.get_session("sid-1") is s
    assert sorted(sm.list_sessions()) == ["sid-1"]
    assert sm.get_session_count() == 1
    assert sm.get_active_sessions() == {"sid-1": s}
    sm.remove_session("sid-1")
    assert sm.get_session("sid-1") is None
    assert sm.list_sessions() == []
    assert sm.get_session_count() == 0


def test_remove_session_missing_is_noop() -> None:
    sm = SessionManager()
    sm.remove_session("nonexistent")
