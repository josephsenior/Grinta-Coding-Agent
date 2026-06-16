"""Unit tests for backend.orchestration.autonomy module.

Tests cover:
- AutonomyLevel enum values
- AutonomyController initialization with various configs
- should_request_confirmation logic for all autonomy levels
- High-risk action detection patterns
- Auto-retry logic for ImportError only
"""

from unittest.mock import MagicMock

from backend.ledger.action import (
    ActionSecurityRisk,
    CmdRunAction,
    FileEditAction,
    FileReadAction,
    FileWriteAction,
    TerminalInputAction,
    TerminalRunAction,
)
from backend.ledger.action.agent import BlackboardAction, DelegateTaskAction
from backend.orchestration.autonomy import AutonomyController, AutonomyLevel


class TestAutonomyLevel:
    """Test AutonomyLevel enum."""

    def test_autonomy_level_values(self):
        """AutonomyLevel should have three canonical levels."""
        assert AutonomyLevel.CONSERVATIVE.value == 'conservative'
        assert AutonomyLevel.BALANCED.value == 'balanced'
        assert AutonomyLevel.FULL.value == 'full'
        assert len(AutonomyLevel) == 3

    def test_autonomy_level_is_string_enum(self):
        """AutonomyLevel should be a string enum."""
        assert isinstance(AutonomyLevel.CONSERVATIVE, str)
        assert isinstance(AutonomyLevel.BALANCED, str)
        assert isinstance(AutonomyLevel.FULL, str)


class TestAutonomyControllerInit:
    """Test AutonomyController initialization."""

    def test_init_with_defaults(self):
        """Should initialize with default BALANCED level."""
        config = MagicMock()
        config.autonomy_level = 'balanced'
        config.auto_retry_on_error = False
        config.max_autonomous_iterations = 0
        config.stuck_detection_enabled = False
        config.stuck_threshold_iterations = 0

        controller = AutonomyController(config)

        assert controller.autonomy_level == 'balanced'
        assert controller.auto_retry is False
        assert controller.max_iterations == 0
        assert controller.stuck_detection is False
        assert controller.stuck_threshold == 0

    def test_init_with_full_autonomy(self):
        """Should initialize with FULL autonomy level."""
        config = MagicMock()
        config.autonomy_level = 'full'
        config.auto_retry_on_error = True
        config.max_autonomous_iterations = 10
        config.stuck_detection_enabled = True
        config.stuck_threshold_iterations = 5

        controller = AutonomyController(config)

        assert controller.autonomy_level == 'full'
        assert controller.auto_retry is True
        assert controller.max_iterations == 10
        assert controller.stuck_detection is True
        assert controller.stuck_threshold == 5

    def test_init_with_conservative_mode(self):
        """Should initialize with CONSERVATIVE level."""
        config = MagicMock()
        config.autonomy_level = 'conservative'
        config.auto_retry_on_error = False
        config.max_autonomous_iterations = 1
        config.stuck_detection_enabled = False
        config.stuck_threshold_iterations = 3

        controller = AutonomyController(config)

        assert controller.autonomy_level == 'conservative'
        assert controller.max_iterations == 1

    def test_init_uses_getattr_with_defaults(self):
        """Should use getattr fallbacks if config lacks attributes."""
        config = MagicMock(spec=[])  # Empty spec - no attributes

        controller = AutonomyController(config)

        # Should fall back to balanced and default values
        assert controller.autonomy_level == 'balanced'
        assert controller.auto_retry is False


class TestShouldRequestConfirmation:
    """Test should_request_confirmation method."""

    def test_full_autonomy_never_asks(self):
        """FULL autonomy should never request confirmation."""
        config = MagicMock()
        config.autonomy_level = 'full'
        controller = AutonomyController(config)

        # High-risk action
        action = CmdRunAction(command='rm -rf /tmp/test')
        assert controller.should_request_confirmation(action) is False

        # Safe action
        safe_action = FileReadAction(path='/tmp/file.txt')
        assert controller.should_request_confirmation(safe_action) is False

    def test_conservative_always_asks(self):
        """CONSERVATIVE mode should always request confirmation."""
        config = MagicMock()
        config.autonomy_level = 'conservative'
        controller = AutonomyController(config)

        # High-risk action
        action = CmdRunAction(command='rm -rf /tmp/test')
        assert controller.should_request_confirmation(action) is True

        # Safe action
        safe_action = FileReadAction(path='/tmp/file.txt')
        assert controller.should_request_confirmation(safe_action) is True

    def test_balanced_asks_for_high_risk_only(self):
        """BALANCED mode should ask only for high-risk actions."""
        config = MagicMock()
        config.autonomy_level = 'balanced'
        controller = AutonomyController(config)

        # High-risk action
        risky_action = CmdRunAction(command='rm -rf /tmp/test')
        assert controller.should_request_confirmation(risky_action) is True

        # Safe action
        safe_action = FileReadAction(path='/tmp/file.txt')
        assert controller.should_request_confirmation(safe_action) is False

    def test_balanced_honors_declared_high_risk(self):
        """BALANCED mode must honor model/tool-declared HIGH risk."""
        config = MagicMock()
        config.autonomy_level = 'balanced'
        controller = AutonomyController(config)

        action = CmdRunAction(command='echo harmless')
        action.security_risk = ActionSecurityRisk.HIGH

        assert controller.should_request_confirmation(action) is True

    def test_balanced_detects_terminal_command_risk(self):
        """Terminal open/input commands use the same command classifier."""
        config = MagicMock()
        config.autonomy_level = 'balanced'
        controller = AutonomyController(config)

        assert (
            controller.should_request_confirmation(
                TerminalRunAction(command='rm -rf /tmp/demo')
            )
            is True
        )
        assert (
            controller.should_request_confirmation(
                TerminalInputAction(session_id='term-1', input='rm -rf /tmp/demo')
            )
            is True
        )

    def test_balanced_prompts_for_concurrency_coordination_actions(self):
        """Experimental worker orchestration actions should be user-visible."""
        config = MagicMock()
        config.autonomy_level = 'balanced'
        controller = AutonomyController(config)

        assert (
            controller.should_request_confirmation(
                DelegateTaskAction(task_description='inspect module')
            )
            is True
        )
        assert (
            controller.should_request_confirmation(
                BlackboardAction(command='set', key='status', value='ready')
            )
            is True
        )


class TestHighRiskDetection:
    """Test _is_high_risk_action detection patterns."""

    def test_detects_rm_rf_command(self):
        """Should detect 'rm -rf' as high-risk."""
        config = MagicMock()
        config.autonomy_level = 'balanced'
        controller = AutonomyController(config)

        action = CmdRunAction(command='rm -rf /tmp/dangerous')
        assert controller._is_high_risk_action(action) is True

    def test_detects_dd_command(self):
        """Should detect 'dd if=' as high-risk."""
        config = MagicMock()
        config.autonomy_level = 'balanced'
        controller = AutonomyController(config)

        action = CmdRunAction(command='dd if=/dev/zero of=/dev/sda')
        assert controller._is_high_risk_action(action) is True

    def test_detects_mkfs_command(self):
        """Should detect 'mkfs' as high-risk."""
        config = MagicMock()
        config.autonomy_level = 'balanced'
        controller = AutonomyController(config)

        action = CmdRunAction(command='mkfs.ext4 /dev/sdb1')
        assert controller._is_high_risk_action(action) is True

    def test_detects_fork_bomb(self):
        """Should detect fork bomb pattern as high-risk."""
        config = MagicMock()
        config.autonomy_level = 'balanced'
        controller = AutonomyController(config)

        action = CmdRunAction(command=':(){:|:&};:')
        assert controller._is_high_risk_action(action) is True

    def test_detects_dev_redirect(self):
        """Should detect redirect to /dev/ as high-risk."""
        config = MagicMock()
        config.autonomy_level = 'balanced'
        controller = AutonomyController(config)

        action = CmdRunAction(command='echo test > /dev/sda')
        assert controller._is_high_risk_action(action) is True

    def test_detects_dangerous_chmod(self):
        """Should detect 'chmod -r 777' as high-risk."""
        config = MagicMock()
        config.autonomy_level = 'balanced'
        controller = AutonomyController(config)

        action = CmdRunAction(command='chmod -r 777 /')
        assert controller._is_high_risk_action(action) is True

    def test_detects_chown_recursive(self):
        """Should detect 'chown -r' as high-risk."""
        config = MagicMock()
        config.autonomy_level = 'balanced'
        controller = AutonomyController(config)

        action = CmdRunAction(command='chown -r nobody:nobody /etc')
        assert controller._is_high_risk_action(action) is True

    def test_detects_reboot_command(self):
        """Should detect 'reboot' as high-risk."""
        config = MagicMock()
        config.autonomy_level = 'balanced'
        controller = AutonomyController(config)

        action = CmdRunAction(command='reboot now')
        assert controller._is_high_risk_action(action) is True

    def test_detects_shutdown_command(self):
        """Should detect 'shutdown' as high-risk."""
        config = MagicMock()
        config.autonomy_level = 'balanced'
        controller = AutonomyController(config)

        action = CmdRunAction(command='shutdown -h now')
        assert controller._is_high_risk_action(action) is True

    def test_detects_systemctl_command(self):
        """Should detect 'systemctl' as high-risk."""
        config = MagicMock()
        config.autonomy_level = 'balanced'
        controller = AutonomyController(config)

        action = CmdRunAction(command='systemctl stop nginx')
        assert controller._is_high_risk_action(action) is True

    def test_case_insensitive_detection(self):
        """Risk detection should be case-insensitive."""
        config = MagicMock()
        config.autonomy_level = 'balanced'
        controller = AutonomyController(config)

        action = CmdRunAction(command='RM -RF /tmp/test')
        assert controller._is_high_risk_action(action) is True

    def test_safe_command_not_high_risk(self):
        """Safe commands should not be flagged as high-risk."""
        config = MagicMock()
        config.autonomy_level = 'balanced'
        controller = AutonomyController(config)

        safe_commands = [
            CmdRunAction(command='ls -la'),
            CmdRunAction(command='cat file.txt'),
            CmdRunAction(command='echo hello'),
            CmdRunAction(command='python script.py'),
        ]

        for action in safe_commands:
            assert controller._is_high_risk_action(action) is False

    def test_file_write_not_high_risk(self):
        """FileWriteAction should not be flagged as high-risk."""
        config = MagicMock()
        config.autonomy_level = 'balanced'
        controller = AutonomyController(config)

        action = FileWriteAction(path='/tmp/test.txt', content='test')
        assert controller._is_high_risk_action(action) is False

    def test_file_edit_is_high_risk(self):
        """FileEditAction should be flagged as high-risk in balanced mode."""
        config = MagicMock()
        config.autonomy_level = 'balanced'
        controller = AutonomyController(config)

        action = FileEditAction(
            path='/tmp/test.txt', start_line=1, end_line=1, new_str='new'
        )
        assert controller._is_high_risk_action(action) is True

    def test_file_read_not_high_risk(self):
        """FileReadAction should not be flagged as high-risk."""
        config = MagicMock()
        config.autonomy_level = 'balanced'
        controller = AutonomyController(config)

        action = FileReadAction(path='/tmp/test.txt')
        assert controller._is_high_risk_action(action) is False


class TestAlwaysAllowMemory:
    """Per-session 'always allow' memory short-circuits the confirmation gate."""

    def test_remembered_command_skips_confirmation_in_conservative(self):
        config = MagicMock()
        config.autonomy_level = 'conservative'
        controller = AutonomyController(config)

        action = CmdRunAction(command='pytest -q')
        # Conservative would normally always ask.
        assert controller.should_request_confirmation(action) is True
        controller.remember_always_allow(action)
        assert controller.should_request_confirmation(action) is False

    def test_remembered_signature_is_command_specific(self):
        config = MagicMock()
        config.autonomy_level = 'conservative'
        controller = AutonomyController(config)

        controller.remember_always_allow(CmdRunAction(command='pytest -q'))
        # A different command must still be gated.
        assert (
            controller.should_request_confirmation(CmdRunAction(command='pytest -v'))
            is True
        )

    def test_action_signature_is_stable(self):
        sig_a = AutonomyController.action_signature(CmdRunAction(command='ls -la'))
        sig_b = AutonomyController.action_signature(CmdRunAction(command='ls -la'))
        assert sig_a == sig_b == 'cmd:ls -la'


class TestShouldRetryOnError:
    """Test should_retry_on_error method."""

    def test_auto_retry_disabled_returns_false(self):
        """Should return False when auto_retry is disabled."""
        config = MagicMock()
        config.auto_retry_on_error = False
        controller = AutonomyController(config)

        error = ImportError("No module named 'foo'")
        assert controller.should_retry_on_error(error, attempts=0) is False

    def test_import_error_triggers_retry_on_first_attempt(self):
        """ImportError should trigger retry on first attempt."""
        config = MagicMock()
        config.auto_retry_on_error = True
        controller = AutonomyController(config)

        error = ImportError("No module named 'foo'")
        assert controller.should_retry_on_error(error, attempts=0) is True

    def test_module_not_found_error_triggers_retry(self):
        """ModuleNotFoundError should trigger retry on first attempt."""
        config = MagicMock()
        config.auto_retry_on_error = True
        controller = AutonomyController(config)

        error = ModuleNotFoundError("No module named 'bar'")
        assert controller.should_retry_on_error(error, attempts=0) is True

    def test_import_error_no_retry_after_one_attempt(self):
        """ImportError should not retry after 1 attempt."""
        config = MagicMock()
        config.auto_retry_on_error = True
        controller = AutonomyController(config)

        error = ImportError("No module named 'foo'")
        assert controller.should_retry_on_error(error, attempts=1) is False

    def test_import_error_no_retry_after_multiple_attempts(self):
        """ImportError should not retry after multiple attempts."""
        config = MagicMock()
        config.auto_retry_on_error = True
        controller = AutonomyController(config)

        error = ImportError("No module named 'foo'")
        assert controller.should_retry_on_error(error, attempts=5) is False

    def test_other_errors_do_not_trigger_retry(self):
        """Non-ImportError exceptions should not trigger retry."""
        config = MagicMock()
        config.auto_retry_on_error = True
        controller = AutonomyController(config)

        errors = [
            ValueError('Invalid value'),
            RuntimeError('Runtime error'),
            KeyError('Missing key'),
            AttributeError('No attribute'),
        ]

        for error in errors:
            assert controller.should_retry_on_error(error, attempts=0) is False
