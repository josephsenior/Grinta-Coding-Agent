"""Extended tests for backend.controller.autonomy — AutonomyController & AutonomyLevel."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.controller.autonomy import AutonomyController, AutonomyLevel
from backend.events.action import CmdRunAction, FileEditAction, FileWriteAction


# ---------------------------------------------------------------------------
# AutonomyLevel enum
# ---------------------------------------------------------------------------
class TestAutonomyLevel:
    def test_values(self):
        assert AutonomyLevel.SUPERVISED == "supervised"
        assert AutonomyLevel.BALANCED == "balanced"
        assert AutonomyLevel.FULL == "full"

    def test_from_string(self):
        assert AutonomyLevel("supervised") is AutonomyLevel.SUPERVISED
        assert AutonomyLevel("full") is AutonomyLevel.FULL


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------
class TestAutonomyControllerInit:
    def test_defaults_from_config(self):
        cfg = MagicMock(
            autonomy_level="balanced",
            auto_retry_on_error=True,
            max_autonomous_iterations=50,
            stuck_detection_enabled=True,
            stuck_threshold_iterations=10,
        )
        ctrl = AutonomyController(cfg)
        assert ctrl.autonomy_level == "balanced"
        assert ctrl.auto_retry is True
        assert ctrl.max_iterations == 50
        assert ctrl.stuck_detection is True
        assert ctrl.stuck_threshold == 10

    def test_missing_config_attrs_use_defaults(self):
        """Config with no autonomy attrs → getattr fallback."""
        cfg = MagicMock(spec=[])
        ctrl = AutonomyController(cfg)
        assert ctrl.autonomy_level == AutonomyLevel.BALANCED.value
        assert ctrl.auto_retry is False
        assert ctrl.max_iterations == 0


# ---------------------------------------------------------------------------
# should_request_confirmation
# ---------------------------------------------------------------------------
class TestShouldRequestConfirmation:
    def _make(self, level: str) -> AutonomyController:
        cfg = MagicMock(autonomy_level=level, spec=[])
        cfg.autonomy_level = level
        return AutonomyController(cfg)

    def test_full_always_false(self):
        ctrl = self._make("full")
        action = CmdRunAction(command="echo hi")
        assert ctrl.should_request_confirmation(action) is False

    def test_supervised_always_true(self):
        ctrl = self._make("supervised")
        action = CmdRunAction(command="echo hi")
        assert ctrl.should_request_confirmation(action) is True

    def test_balanced_safe_command(self):
        ctrl = self._make("balanced")
        action = CmdRunAction(command="echo hello")
        assert ctrl.should_request_confirmation(action) is False

    def test_balanced_destructive_rm_rf(self):
        ctrl = self._make("balanced")
        action = CmdRunAction(command="rm -rf /")
        assert ctrl.should_request_confirmation(action) is True

    def test_balanced_destructive_dd(self):
        ctrl = self._make("balanced")
        action = CmdRunAction(command="dd if=/dev/zero of=/dev/sda")
        assert ctrl.should_request_confirmation(action) is True

    def test_balanced_system_reboot(self):
        ctrl = self._make("balanced")
        action = CmdRunAction(command="reboot")
        assert ctrl.should_request_confirmation(action) is True

    def test_balanced_system_shutdown(self):
        ctrl = self._make("balanced")
        action = CmdRunAction(command="shutdown -h now")
        assert ctrl.should_request_confirmation(action) is True

    def test_balanced_file_edit_not_high_risk(self):
        ctrl = self._make("balanced")
        action = FileEditAction(path="/tmp/test.py", content="pass")
        assert ctrl.should_request_confirmation(action) is False

    def test_balanced_file_write_not_high_risk(self):
        ctrl = self._make("balanced")
        action = FileWriteAction(path="/tmp/test.py", content="pass")
        assert ctrl.should_request_confirmation(action) is False


# ---------------------------------------------------------------------------
# _is_high_risk_action — more patterns
# ---------------------------------------------------------------------------
class TestIsHighRiskAction:
    def _ctrl(self):
        cfg = MagicMock(autonomy_level="balanced", spec=[])
        cfg.autonomy_level = "balanced"
        return AutonomyController(cfg)

    @pytest.mark.parametrize(
        "cmd",
        [
            "rm -rf /home",
            "dd if=/dev/urandom",
            "mkfs.ext4 /dev/sda1",
            "chmod -r 777 /",
            "chown -r root:root /",
            ":(){:|:&};:",
            "echo foo > /dev/sda",
        ],
    )
    def test_destructive_commands(self, cmd):
        ctrl = self._ctrl()
        action = CmdRunAction(command=cmd)
        assert ctrl._is_high_risk_action(action) is True

    @pytest.mark.parametrize(
        "cmd",
        [
            "ls -la",
            "cat /etc/hostname",
            "pip install requests",
            "python test.py",
            "git status",
        ],
    )
    def test_safe_commands(self, cmd):
        ctrl = self._ctrl()
        action = CmdRunAction(command=cmd)
        assert ctrl._is_high_risk_action(action) is False

    def test_systemctl_detected(self):
        ctrl = self._ctrl()
        action = CmdRunAction(command="systemctl restart nginx")
        assert ctrl._is_high_risk_action(action) is True

    def test_non_cmd_action(self):
        ctrl = self._ctrl()
        action = MagicMock(spec=[])
        assert ctrl._is_high_risk_action(action) is False


# ---------------------------------------------------------------------------
# should_retry_on_error
# ---------------------------------------------------------------------------
class TestShouldRetryOnError:
    def _ctrl(self, auto_retry: bool = True):
        cfg = MagicMock(
            autonomy_level="balanced",
            auto_retry_on_error=auto_retry,
            spec=[],
        )
        cfg.autonomy_level = "balanced"
        cfg.auto_retry_on_error = auto_retry
        return AutonomyController(cfg)

    def test_disabled_never_retries(self):
        ctrl = self._ctrl(auto_retry=False)
        assert ctrl.should_retry_on_error(ImportError("no mod"), 0) is False

    def test_import_error_first_attempt(self):
        ctrl = self._ctrl(auto_retry=True)
        assert ctrl.should_retry_on_error(ImportError("no mod"), 0) is True

    def test_import_error_second_attempt_blocked(self):
        ctrl = self._ctrl(auto_retry=True)
        assert ctrl.should_retry_on_error(ImportError("no mod"), 1) is False

    def test_module_not_found_first_attempt(self):
        ctrl = self._ctrl(auto_retry=True)
        assert ctrl.should_retry_on_error(ModuleNotFoundError("no mod"), 0) is True

    def test_runtime_error_not_retried(self):
        ctrl = self._ctrl(auto_retry=True)
        assert ctrl.should_retry_on_error(RuntimeError("boom"), 0) is False

    def test_value_error_not_retried(self):
        ctrl = self._ctrl(auto_retry=True)
        assert ctrl.should_retry_on_error(ValueError("bad"), 0) is False
