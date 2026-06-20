"""Tests for :mod:`backend.core.timeout_policy`."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.core.constants import (
    CMD_PENDING_ACTION_TIMEOUT_FLOOR,
    TOOL_BRIDGE_TIMEOUT_BUFFER,
)
from backend.core.timeouts.timeout_policy import (
    cmd_run_sync_bridge_timeout_seconds,
    cmd_run_timeout_candidates,
    effective_cmd_run_pending_timeout_seconds,
)


class TestCmdRunTimeoutCandidates:
    def test_includes_base_floor_and_explicit_timeout(self):
        action = MagicMock()
        action.timeout = 900.0
        c = cmd_run_timeout_candidates(120.0, action)
        assert max(c) == 900.0
        assert CMD_PENDING_ACTION_TIMEOUT_FLOOR in c

    def test_pending_matches_max_of_candidates(self):
        action = MagicMock()
        action.timeout = 42.0
        eff = effective_cmd_run_pending_timeout_seconds(120.0, action)
        assert eff == float(CMD_PENDING_ACTION_TIMEOUT_FLOOR)

        action.timeout = 900.0
        eff2 = effective_cmd_run_pending_timeout_seconds(120.0, action)
        assert eff2 == 900.0


class TestCmdRunSyncBridge:
    def test_default_matches_floor_plus_buffer(self):
        action = MagicMock()
        action.timeout = None
        assert cmd_run_sync_bridge_timeout_seconds(action) == pytest.approx(
            float(CMD_PENDING_ACTION_TIMEOUT_FLOOR) + float(TOOL_BRIDGE_TIMEOUT_BUFFER)
        )

    def test_uses_positive_action_timeout_plus_buffer(self):
        action = MagicMock()
        action.timeout = 300.0
        assert cmd_run_sync_bridge_timeout_seconds(action) == pytest.approx(310.0)
