"""Tests for universal command timeout (no pattern matching).

Verifies that all commands get the same generous safety-net timeout
and run non-blocking, relying on idle-output detection instead of
brittle pattern matching.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.execution.command_timeout import (
    _SAFETY_NET_TIMEOUT,
    CommandTimeoutMixin,
)


class _FakeMixin(CommandTimeoutMixin):
    """Concrete class wrapping the mixin for testing."""

    def __init__(self):
        self.sid = 'test-sid'
        self.config = MagicMock()
        self.config.runtime_config.timeout = 120
        self.process_manager = MagicMock()


class TestUniversalTimeout(unittest.TestCase):
    """All CmdRunAction commands get the same safety-net timeout."""

    def setUp(self):
        self.mixin = _FakeMixin()

    def _make_cmd_action(self, command, timeout=None):
        from backend.ledger.action import CmdRunAction

        action = MagicMock(spec=CmdRunAction)
        action.__class__ = CmdRunAction  # type: ignore[assignment]
        action.command = command
        action.timeout = timeout
        return action

    def test_npm_install_gets_safety_net(self):
        action = self._make_cmd_action('npm install')
        self.mixin._set_action_timeout(action)
        action.set_hard_timeout.assert_called_once_with(
            _SAFETY_NET_TIMEOUT, blocking=False
        )

    def test_npm_run_dev_gets_safety_net(self):
        """Servers previously got None; now they get the same safety-net."""
        action = self._make_cmd_action('npm run dev')
        self.mixin._set_action_timeout(action)
        action.set_hard_timeout.assert_called_once_with(
            _SAFETY_NET_TIMEOUT, blocking=False
        )

    def test_ls_gets_safety_net(self):
        action = self._make_cmd_action('ls -la')
        self.mixin._set_action_timeout(action)
        action.set_hard_timeout.assert_called_once_with(
            _SAFETY_NET_TIMEOUT, blocking=False
        )

    def test_prisma_generate_gets_safety_net(self):
        action = self._make_cmd_action('prisma generate')
        self.mixin._set_action_timeout(action)
        action.set_hard_timeout.assert_called_once_with(
            _SAFETY_NET_TIMEOUT, blocking=False
        )

    def test_cargo_build_gets_safety_net(self):
        action = self._make_cmd_action('cargo build --release')
        self.mixin._set_action_timeout(action)
        action.set_hard_timeout.assert_called_once_with(
            _SAFETY_NET_TIMEOUT, blocking=False
        )

    def test_uvicorn_gets_safety_net(self):
        action = self._make_cmd_action('uvicorn main:app')
        self.mixin._set_action_timeout(action)
        action.set_hard_timeout.assert_called_once_with(
            _SAFETY_NET_TIMEOUT, blocking=False
        )

    def test_explicit_timeout_not_overridden(self):
        action = self._make_cmd_action('npm install', timeout=60)
        self.mixin._set_action_timeout(action)
        action.set_hard_timeout.assert_not_called()

    def test_safety_net_is_600(self):
        self.assertEqual(_SAFETY_NET_TIMEOUT, 600)

    def test_no_pattern_lists_exported(self):
        """Pattern lists should no longer exist in the module."""
        import backend.execution.command_timeout as mod

        self.assertFalse(hasattr(mod, '_LONG_RUNNING_PATTERNS'))
        self.assertFalse(hasattr(mod, '_SLOW_COMMAND_PATTERNS'))

    def test_no_pattern_methods(self):
        """Pattern detection methods should no longer exist."""
        self.assertFalse(hasattr(self.mixin, '_is_long_running_command'))
        self.assertFalse(hasattr(self.mixin, '_is_slow_command'))

    def test_non_cmd_action_gets_config_timeout(self):
        """Non-CmdRunAction events still get config.runtime_config.timeout."""
        action = MagicMock()
        action.timeout = None
        self.mixin._set_action_timeout(action)
        action.set_hard_timeout.assert_called_once_with(120, blocking=False)


if __name__ == '__main__':
    unittest.main()
