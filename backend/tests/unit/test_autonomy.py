"""Unit tests for backend.controller.autonomy — Autonomy level control."""

from unittest.mock import Mock

import pytest

from backend.controller.autonomy import AutonomyController, AutonomyLevel
from backend.events.action import (
    AgentThinkAction,
    CmdRunAction,
    FileEditAction,
    FileWriteAction,
    MessageAction,
)


# ---------------------------------------------------------------------------
# Helper to create mock config
# ---------------------------------------------------------------------------


def _mock_config(**overrides):
    """Create a mock AgentConfig with specified overrides."""
    defaults = {
        "autonomy_level": AutonomyLevel.BALANCED.value,
        "auto_retry_on_error": False,
        "max_autonomous_iterations": 100,
        "stuck_detection_enabled": True,
        "stuck_threshold_iterations": 3,
    }
    defaults.update(overrides)
    config = Mock()
    for key, value in defaults.items():
        setattr(config, key, value)
    return config


# ---------------------------------------------------------------------------
# Autonomy level: FULL
# ---------------------------------------------------------------------------


class TestAutonomyLevelFull:
    def test_never_requests_confirmation(self):
        config = _mock_config(autonomy_level=AutonomyLevel.FULL.value)
        controller = AutonomyController(config)

        # Test various action types
        assert not controller.should_request_confirmation(
            CmdRunAction(command="ls -la")
        )
        assert not controller.should_request_confirmation(
            CmdRunAction(command="rm -rf /tmp/test")
        )
        assert not controller.should_request_confirmation(
            FileWriteAction(path="test.py", content="print('hello')")
        )
        assert not controller.should_request_confirmation(
            AgentThinkAction(thought="Analyzing...")
        )


# ---------------------------------------------------------------------------
# Autonomy level: SUPERVISED
# ---------------------------------------------------------------------------


class TestAutonomyLevelSupervised:
    def test_always_requests_confirmation(self):
        config = _mock_config(autonomy_level=AutonomyLevel.SUPERVISED.value)
        controller = AutonomyController(config)

        # Test various action types - all should request confirmation
        assert controller.should_request_confirmation(CmdRunAction(command="ls -la"))
        assert controller.should_request_confirmation(
            CmdRunAction(command="echo 'safe'")
        )
        assert controller.should_request_confirmation(
            FileWriteAction(path="test.py", content="print('hello')")
        )
        assert controller.should_request_confirmation(
            FileEditAction(path="config.toml")
        )
        assert controller.should_request_confirmation(
            AgentThinkAction(thought="Thinking...")
        )


# ---------------------------------------------------------------------------
# Autonomy level: BALANCED (high-risk detection)
# ---------------------------------------------------------------------------


class TestAutonomyLevelBalanced:
    def test_safe_actions_no_confirmation(self):
        config = _mock_config(autonomy_level=AutonomyLevel.BALANCED.value)
        controller = AutonomyController(config)

        # Safe commands
        assert (
            not controller.should_request_confirmation(CmdRunAction(command="ls -la"))
        )
        assert not controller.should_request_confirmation(
            CmdRunAction(command="cat file.txt")
        )
        assert not controller.should_request_confirmation(
            CmdRunAction(command="git status")
        )
        assert not controller.should_request_confirmation(
            CmdRunAction(command="echo 'hello'")
        )

        # Safe file operations
        assert not controller.should_request_confirmation(
            FileWriteAction(path="test.py", content="code")
        )
        assert not controller.should_request_confirmation(
            FileEditAction(path="app.py")
        )

        # Non-command actions
        assert not controller.should_request_confirmation(
            AgentThinkAction(thought="Thinking...")
        )
        assert not controller.should_request_confirmation(
            MessageAction(content="Status update")
        )

    @pytest.mark.parametrize(
        "dangerous_cmd",
        [
            "rm -rf /important",
            "dd if=/dev/zero of=/dev/sda",
            "mkfs.ext4 /dev/sda1",
            "fdisk /dev/sda",
            ":(){:|:&};:",  # fork bomb
            "echo 'test' > /dev/sda",
            "chmod -r 777 /etc",
            "chown -r nobody:nobody /",
        ],
    )
    def test_destructive_commands_require_confirmation(self, dangerous_cmd):
        config = _mock_config(autonomy_level=AutonomyLevel.BALANCED.value)
        controller = AutonomyController(config)

        assert controller.should_request_confirmation(CmdRunAction(command=dangerous_cmd))

    @pytest.mark.parametrize(
        "system_cmd",
        [
            "reboot",
            "shutdown -h now",
            "init 6",
            "systemctl restart networking",
        ],
    )
    def test_system_commands_require_confirmation(self, system_cmd):
        config = _mock_config(autonomy_level=AutonomyLevel.BALANCED.value)
        controller = AutonomyController(config)

        assert controller.should_request_confirmation(CmdRunAction(command=system_cmd))

    def test_case_insensitive_detection(self):
        """High-risk detection should be case-insensitive."""
        config = _mock_config(autonomy_level=AutonomyLevel.BALANCED.value)
        controller = AutonomyController(config)

        assert controller.should_request_confirmation(
            CmdRunAction(command="RM -RF /tmp")
        )
        assert controller.should_request_confirmation(
            CmdRunAction(command="REBOOT")
        )


# ---------------------------------------------------------------------------
# Auto-retry on error logic
# ---------------------------------------------------------------------------


class TestAutoRetryOnError:
    def test_auto_retry_disabled(self):
        config = _mock_config(auto_retry_on_error=False)
        controller = AutonomyController(config)

        error = ImportError("No module named 'test'")
        assert not controller.should_retry_on_error(error, attempts=0)

    def test_import_error_retry_once(self):
        config = _mock_config(auto_retry_on_error=True)
        controller = AutonomyController(config)

        error = ImportError("No module named 'requests'")

        # First attempt should allow retry
        assert controller.should_retry_on_error(error, attempts=0)

        # Second attempt should NOT retry (max 1 retry)
        assert not controller.should_retry_on_error(error, attempts=1)

    def test_module_not_found_retry_once(self):
        config = _mock_config(auto_retry_on_error=True)
        controller = AutonomyController(config)

        error = ModuleNotFoundError("No module named 'pandas'")
        assert controller.should_retry_on_error(error, attempts=0)
        assert not controller.should_retry_on_error(error, attempts=1)

    def test_non_import_error_no_retry(self):
        """Only ImportError should trigger auto-retry."""
        config = _mock_config(auto_retry_on_error=True)
        controller = AutonomyController(config)

        # These should NOT trigger retry even with auto_retry=True
        assert not controller.should_retry_on_error(ValueError("test"), attempts=0)
        assert not controller.should_retry_on_error(RuntimeError("test"), attempts=0)
        assert not controller.should_retry_on_error(TimeoutError("test"), attempts=0)


# ---------------------------------------------------------------------------
# Configuration initialization
# ---------------------------------------------------------------------------


class TestControllerInitialization:
    def test_default_configuration(self):
        config = _mock_config()
        controller = AutonomyController(config)

        assert controller.autonomy_level == AutonomyLevel.BALANCED.value
        assert controller.auto_retry is False
        assert controller.max_iterations == 100
        assert controller.stuck_detection is True
        assert controller.stuck_threshold == 3

    def test_custom_configuration(self):
        config = _mock_config(
            autonomy_level=AutonomyLevel.FULL.value,
            auto_retry_on_error=True,
            max_autonomous_iterations=50,
            stuck_detection_enabled=False,
            stuck_threshold_iterations=5,
        )
        controller = AutonomyController(config)

        assert controller.autonomy_level == AutonomyLevel.FULL.value
        assert controller.auto_retry is True
        assert controller.max_iterations == 50
        assert controller.stuck_detection is False
        assert controller.stuck_threshold == 5

    def test_missing_config_attributes_use_defaults(self):
        """Controller should handle missing config attributes gracefully."""
        config = Mock(spec=[])  # Empty mock with no attributes

        # Should use getattr defaults without crashing
        controller = AutonomyController(config)

        # Verify defaults were applied
        assert hasattr(controller, "autonomy_level")
        assert hasattr(controller, "auto_retry")
