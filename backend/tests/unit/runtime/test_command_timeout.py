"""Tests for backend.runtime.command_timeout."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock


from backend.runtime.command_timeout import CommandTimeoutMixin, _LONG_RUNNING_PATTERNS


# ── helper: concrete class that uses the mixin ───────────────────────

class _FakeRuntime(CommandTimeoutMixin):
    def __init__(self):
        self.sid = "test-sid"
        self.config = SimpleNamespace(
            runtime_config=SimpleNamespace(timeout=120)
        )
        self.process_manager = MagicMock()


# ── _is_long_running_command ─────────────────────────────────────────

class TestIsLongRunning:
    def test_server_commands(self):
        rt = _FakeRuntime()
        assert rt._is_long_running_command("npm run dev")
        assert rt._is_long_running_command("uvicorn main:app")
        assert rt._is_long_running_command("python -m http.server 8000")
        assert rt._is_long_running_command("gunicorn app:main")
        assert rt._is_long_running_command("flask run --port 5000")

    def test_normal_commands(self):
        rt = _FakeRuntime()
        assert not rt._is_long_running_command("ls -la")
        assert not rt._is_long_running_command("echo hello")
        assert not rt._is_long_running_command("python test.py")
        assert not rt._is_long_running_command("cat file.txt")


# ── _set_action_timeout ──────────────────────────────────────────────

class TestSetActionTimeout:
    def test_explicit_timeout_not_overridden(self):
        from backend.events.action.commands import CmdRunAction

        rt = _FakeRuntime()
        action = CmdRunAction(command="npm start")
        action.set_hard_timeout(30, blocking=False)
        rt._set_action_timeout(action)
        # Should keep the explicit timeout
        assert action.timeout == 30

    def test_long_running_gets_none_timeout(self):
        from backend.events.action.commands import CmdRunAction

        rt = _FakeRuntime()
        action = CmdRunAction(command="npm start")
        # timeout defaults to None for new actions
        rt._set_action_timeout(action)
        assert action.timeout is None  # set to None for long-running

    def test_normal_command_gets_config_timeout(self):
        from backend.events.action.commands import CmdRunAction

        rt = _FakeRuntime()
        action = CmdRunAction(command="ls -la")
        # timeout defaults to None for new actions
        rt._set_action_timeout(action)
        assert action.timeout == 120


# ── patterns constant ────────────────────────────────────────────────

class TestPatterns:
    def test_has_common_patterns(self):
        assert "npm run dev" in _LONG_RUNNING_PATTERNS
        assert "uvicorn" in _LONG_RUNNING_PATTERNS
        assert "flask run" in _LONG_RUNNING_PATTERNS
