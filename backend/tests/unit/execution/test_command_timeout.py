"""Tests for backend.execution.command_timeout."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.execution.command_timeout import _SAFETY_NET_TIMEOUT, CommandTimeoutMixin

# ── helper: concrete class that uses the mixin ───────────────────────


class _FakeRuntime(CommandTimeoutMixin):
    def __init__(self):
        self.sid = 'test-sid'
        self.config = SimpleNamespace(runtime_config=SimpleNamespace(timeout=120))
        self.process_manager = MagicMock()


# ── _set_action_timeout ──────────────────────────────────────────────


class TestSetActionTimeout:
    def test_explicit_timeout_not_overridden(self):
        from backend.ledger.action.commands import CmdRunAction

        rt = _FakeRuntime()
        action = CmdRunAction(command='npm start')
        action.set_hard_timeout(30, blocking=False)
        rt._set_action_timeout(action)
        # Should keep the explicit timeout
        assert action.timeout == 30

    def test_all_commands_get_safety_net_timeout(self):
        from backend.ledger.action.commands import CmdRunAction

        rt = _FakeRuntime()
        for cmd in [
            'npm install',
            'npm run dev',
            'ls -la',
            'prisma generate',
            'cargo build',
        ]:
            action = CmdRunAction(command=cmd)
            rt._set_action_timeout(action)
            assert action.timeout == _SAFETY_NET_TIMEOUT, (
                f"Expected {_SAFETY_NET_TIMEOUT} for '{cmd}', got {action.timeout}"
            )

    def test_commands_are_non_blocking(self):
        from backend.ledger.action.commands import CmdRunAction

        rt = _FakeRuntime()
        action = CmdRunAction(command='npm install')
        rt._set_action_timeout(action)
        assert not action.blocking


# ── safety net constant ──────────────────────────────────────────────


class TestSafetyNet:
    def test_safety_net_is_generous(self):
        assert _SAFETY_NET_TIMEOUT >= 300
