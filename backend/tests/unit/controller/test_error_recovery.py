"""Tests for backend.controller.error_recovery module."""

from backend.controller.error_recovery import (
    ErrorRecoveryStrategy,
    ErrorType,
)
from backend.core.exceptions import (
    FunctionCallNotExistsError,
    FunctionCallValidationError,
)
from backend.events.action import AgentThinkAction, CmdRunAction, MessageAction
from backend.llm.exceptions import AuthenticationError


class TestErrorType:
    """Tests for ErrorType enum."""

    def test_error_types_defined(self):
        """Test all error types are defined."""
        assert ErrorType.MODULE_NOT_FOUND == "module_not_found"
        assert ErrorType.RUNTIME_CRASH == "runtime_crash"
        assert ErrorType.NETWORK_ERROR == "network_error"
        assert ErrorType.FILESYSTEM_ERROR == "filesystem_error"
        assert ErrorType.TOOL_CALL_ERROR == "tool_call_error"
        assert ErrorType.TIMEOUT_ERROR == "timeout_error"
        assert ErrorType.PERMISSION_ERROR == "permission_error"
        assert ErrorType.DISK_FULL_ERROR == "disk_full_error"
        assert ErrorType.SYNTAX_ERROR == "syntax_error"
        assert ErrorType.UNKNOWN_ERROR == "unknown_error"


class TestClassifyError:
    """Tests for ErrorRecoveryStrategy.classify_error method."""

    def test_classify_module_not_found(self):
        """Test classifies ModuleNotFoundError."""
        error = ModuleNotFoundError("No module named 'requests'")
        result = ErrorRecoveryStrategy.classify_error(error)
        assert result == ErrorType.MODULE_NOT_FOUND

    def test_classify_import_error(self):
        """Test classifies ImportError."""
        error = ImportError("cannot import name 'foo'")
        result = ErrorRecoveryStrategy.classify_error(error)
        assert result == ErrorType.MODULE_NOT_FOUND

    def test_classify_syntax_error(self):
        """Test classifies SyntaxError."""
        error = SyntaxError("invalid syntax")
        result = ErrorRecoveryStrategy.classify_error(error)
        assert result == ErrorType.SYNTAX_ERROR

    def test_classify_permission_error(self):
        """Test classifies PermissionError."""
        error = PermissionError("Permission denied")
        result = ErrorRecoveryStrategy.classify_error(error)
        assert result == ErrorType.PERMISSION_ERROR

    def test_classify_timeout_error(self):
        """Test classifies TimeoutError."""
        error = TimeoutError("Operation timed out")
        result = ErrorRecoveryStrategy.classify_error(error)
        assert result == ErrorType.TIMEOUT_ERROR

    def test_classify_file_not_found_error(self):
        """Test classifies FileNotFoundError."""
        error = FileNotFoundError("file.txt not found")
        result = ErrorRecoveryStrategy.classify_error(error)
        assert result == ErrorType.FILESYSTEM_ERROR

    def test_classify_function_call_validation_error(self):
        """Test classifies FunctionCallValidationError."""
        error = FunctionCallValidationError("Invalid parameter")
        result = ErrorRecoveryStrategy.classify_error(error)
        assert result == ErrorType.TOOL_CALL_ERROR

    def test_classify_function_call_not_exists_error(self):
        """Test classifies FunctionCallNotExistsError."""
        error = FunctionCallNotExistsError("Function not found")
        result = ErrorRecoveryStrategy.classify_error(error)
        assert result == ErrorType.TOOL_CALL_ERROR

    def test_classify_runtime_crash_by_message(self):
        """Test classifies runtime crash by message pattern."""
        error = Exception("runtime terminated unexpectedly")
        result = ErrorRecoveryStrategy.classify_error(error)
        assert result == ErrorType.RUNTIME_CRASH

    def test_classify_network_error_by_message(self):
        """Test classifies network error by message pattern."""
        error = Exception("connection refused")
        result = ErrorRecoveryStrategy.classify_error(error)
        assert result == ErrorType.NETWORK_ERROR

    def test_classify_disk_full_by_message(self):
        """Test classifies disk full error by message pattern."""
        error = Exception("no space left on device")
        result = ErrorRecoveryStrategy.classify_error(error)
        assert result == ErrorType.DISK_FULL_ERROR

    def test_classify_unknown_error(self):
        """Test classifies unknown error."""
        error = Exception("something completely unexpected")
        result = ErrorRecoveryStrategy.classify_error(error)
        assert result == ErrorType.UNKNOWN_ERROR


class TestMatchesPatterns:
    """Tests for ErrorRecoveryStrategy._matches_patterns method."""

    def test_matches_single_pattern(self):
        """Test matches single pattern."""
        result = ErrorRecoveryStrategy._matches_patterns(
            "connection timeout occurred",
            ["timeout"],
        )
        assert result is True

    def test_matches_multiple_patterns(self):
        """Test matches one of multiple patterns."""
        result = ErrorRecoveryStrategy._matches_patterns(
            "network unreachable",
            ["timeout", "network.*unreachable", "dns"],
        )
        assert result is True

    def test_no_match(self):
        """Test no pattern matches."""
        result = ErrorRecoveryStrategy._matches_patterns(
            "something else",
            ["timeout", "network"],
        )
        assert result is False

    def test_case_insensitive(self):
        """Test pattern matching is case insensitive."""
        result = ErrorRecoveryStrategy._matches_patterns(
            "TIMEOUT OCCURRED",
            ["timeout"],
        )
        assert result is True


class TestGetRecoveryActions:
    """Tests for ErrorRecoveryStrategy.get_recovery_actions method."""

    def test_module_not_found_recovery(self):
        """Test recovery actions for module not found."""
        error = ModuleNotFoundError("No module named 'requests'")
        error_type = ErrorType.MODULE_NOT_FOUND

        actions = ErrorRecoveryStrategy.get_recovery_actions(error_type, error)

        assert len(actions) > 0
        # Should include pip install
        assert any(isinstance(action, CmdRunAction) and "pip install" in action.command for action in actions)

    def test_runtime_crash_recovery(self):
        """Test recovery actions for runtime crash."""
        error = Exception("runtime terminated")
        error_type = ErrorType.RUNTIME_CRASH

        actions = ErrorRecoveryStrategy.get_recovery_actions(error_type, error)

        assert len(actions) > 0
        assert any(isinstance(action, AgentThinkAction) for action in actions)

    def test_network_error_recovery(self):
        """Test recovery actions for network error."""
        error = Exception("connection refused")
        error_type = ErrorType.NETWORK_ERROR

        actions = ErrorRecoveryStrategy.get_recovery_actions(error_type, error)

        assert len(actions) > 0
        assert any(isinstance(action, MessageAction) for action in actions)

    def test_network_error_git_specific(self):
        """Test recovery actions for git network error."""
        error = Exception("git clone failed: connection timeout")
        error_type = ErrorType.NETWORK_ERROR

        actions = ErrorRecoveryStrategy.get_recovery_actions(error_type, error)

        assert len(actions) > 0
        # Should include git config commands
        assert any(isinstance(action, CmdRunAction) and "git config" in action.command for action in actions)

    def test_filesystem_error_recovery(self):
        """Test recovery actions for filesystem error."""
        error = FileNotFoundError("test.py not found")
        error_type = ErrorType.FILESYSTEM_ERROR

        actions = ErrorRecoveryStrategy.get_recovery_actions(error_type, error)

        assert len(actions) > 0
        assert any(isinstance(action, CmdRunAction) for action in actions)

    def test_tool_call_error_recovery_empty(self):
        """Test tool call error returns empty to prevent loops."""
        error = FunctionCallValidationError("Invalid parameter")
        error_type = ErrorType.TOOL_CALL_ERROR

        actions = ErrorRecoveryStrategy.get_recovery_actions(error_type, error)

        # Should return empty to prevent infinite loop
        assert len(actions) == 0

    def test_tool_call_error_auth_empty(self):
        """Test tool call error with auth indicator returns empty."""
        error = Exception("authentication failed")
        error_type = ErrorType.TOOL_CALL_ERROR

        actions = ErrorRecoveryStrategy.get_recovery_actions(error_type, error)

        assert len(actions) == 0

    def test_timeout_error_recovery(self):
        """Test recovery actions for timeout error."""
        error = TimeoutError("Operation timed out")
        error_type = ErrorType.TIMEOUT_ERROR

        actions = ErrorRecoveryStrategy.get_recovery_actions(error_type, error)

        assert len(actions) > 0
        assert any(isinstance(action, AgentThinkAction) for action in actions)

    def test_permission_error_recovery(self):
        """Test recovery actions for permission error."""
        error = PermissionError("Permission denied: '/etc/config'")
        error_type = ErrorType.PERMISSION_ERROR

        actions = ErrorRecoveryStrategy.get_recovery_actions(error_type, error)

        assert len(actions) > 0
        assert any(isinstance(action, MessageAction) for action in actions)

    def test_disk_full_error_recovery(self):
        """Test recovery actions for disk full error."""
        error = Exception("no space left on device")
        error_type = ErrorType.DISK_FULL_ERROR

        actions = ErrorRecoveryStrategy.get_recovery_actions(error_type, error)

        assert len(actions) > 0
        # Should include df and cleanup commands
        assert any(isinstance(action, CmdRunAction) and "df" in action.command for action in actions)
        assert any(isinstance(action, CmdRunAction) and "rm" in action.command for action in actions)

    def test_syntax_error_recovery(self):
        """Test recovery actions for syntax error."""
        error = SyntaxError("invalid syntax (test.py, line 10)")
        error_type = ErrorType.SYNTAX_ERROR

        actions = ErrorRecoveryStrategy.get_recovery_actions(error_type, error)

        assert len(actions) > 0
        assert any(isinstance(action, AgentThinkAction) for action in actions)

    def test_unknown_error_recovery(self):
        """Test recovery actions for unknown error."""
        error = Exception("completely unexpected error")
        error_type = ErrorType.UNKNOWN_ERROR

        actions = ErrorRecoveryStrategy.get_recovery_actions(error_type, error)

        assert len(actions) > 0
        assert any(isinstance(action, AgentThinkAction) for action in actions)

    def test_authentication_error_returns_empty(self):
        """Test AuthenticationError returns empty actions."""
        error = AuthenticationError("API key invalid")
        error_type = ErrorType.UNKNOWN_ERROR

        actions = ErrorRecoveryStrategy.get_recovery_actions(error_type, error)

        # Should return empty for auth errors
        assert len(actions) == 0


class TestRecoverModuleNotFound:
    """Tests for _recover_module_not_found method."""

    def test_extracts_package_name(self):
        """Test extracts package name from error message."""
        error_str = "No module named 'requests'"
        actions = ErrorRecoveryStrategy._recover_module_not_found(error_str)

        assert len(actions) > 0
        # Should install 'requests'
        cmd_actions = [a for a in actions if isinstance(a, CmdRunAction)]
        assert any("requests" in action.command for action in cmd_actions)

    def test_extracts_base_package(self):
        """Test extracts base package from submodule."""
        error_str = "No module named 'requests.auth'"
        actions = ErrorRecoveryStrategy._recover_module_not_found(error_str)

        assert len(actions) > 0
        # Should install 'requests', not 'requests.auth'
        cmd_actions = [a for a in actions if isinstance(a, CmdRunAction)]
        assert any("pip install requests" in action.command for action in cmd_actions)

    def test_no_package_name_returns_think_action(self):
        """Test returns think action when can't extract package."""
        error_str = "Some other import error"
        actions = ErrorRecoveryStrategy._recover_module_not_found(error_str)

        assert len(actions) > 0
        # Should still return some action
        assert any(isinstance(action, AgentThinkAction) for action in actions)


class TestRecoverRuntimeCrash:
    """Tests for _recover_runtime_crash method."""

    def test_returns_recovery_actions(self):
        """Test returns runtime check and message actions."""
        error_str = "runtime terminated"
        actions = ErrorRecoveryStrategy._recover_runtime_crash(error_str)

        assert len(actions) > 0
        assert any(isinstance(action, AgentThinkAction) for action in actions)
        assert any(isinstance(action, CmdRunAction) for action in actions)
        assert any(isinstance(action, MessageAction) for action in actions)

    def test_includes_runtime_check_command(self):
        """Test includes echo command to check runtime."""
        error_str = "connection reset"
        actions = ErrorRecoveryStrategy._recover_runtime_crash(error_str)

        cmd_actions = [a for a in actions if isinstance(a, CmdRunAction)]
        assert any("echo" in action.command for action in cmd_actions)


class TestRecoverNetworkError:
    """Tests for _recover_network_error method."""

    def test_git_network_error_specific_recovery(self):
        """Test git-specific recovery for git errors."""
        error_str = "git clone failed: timeout"
        actions = ErrorRecoveryStrategy._recover_network_error(error_str)

        assert len(actions) > 0
        cmd_actions = [a for a in actions if isinstance(a, CmdRunAction)]
        # Should configure git
        assert any("git config" in action.command for action in cmd_actions)

    def test_general_network_error_recovery(self):
        """Test general recovery for non-git network errors."""
        error_str = "connection refused"
        actions = ErrorRecoveryStrategy._recover_network_error(error_str)

        assert len(actions) > 0
        assert any(isinstance(action, AgentThinkAction) for action in actions)
        # Should include sleep command
        cmd_actions = [a for a in actions if isinstance(a, CmdRunAction)]
        assert any("sleep" in action.command for action in cmd_actions)


class TestRecoverFilesystemError:
    """Tests for _recover_filesystem_error method."""

    def test_file_not_found_recovery(self):
        """Test recovery for file not found."""
        error_str = "'test.py' not found"
        actions = ErrorRecoveryStrategy._recover_filesystem_error(error_str)

        assert len(actions) > 0
        # Should include pwd and ls commands
        cmd_actions = [a for a in actions if isinstance(a, CmdRunAction)]
        assert any("pwd" in action.command for action in cmd_actions)
        assert any("ls" in action.command for action in cmd_actions)

    def test_file_not_found_includes_find(self):
        """Test includes find command to search for file."""
        error_str = "'file.txt' not found"
        actions = ErrorRecoveryStrategy._recover_filesystem_error(error_str)

        cmd_actions = [a for a in actions if isinstance(a, CmdRunAction)]
        # Should include find command when filename is extracted
        assert any("find" in action.command for action in cmd_actions)

    def test_general_filesystem_error(self):
        """Test general filesystem error recovery."""
        error_str = "filesystem error"
        actions = ErrorRecoveryStrategy._recover_filesystem_error(error_str)

        assert len(actions) > 0
        cmd_actions = [a for a in actions if isinstance(a, CmdRunAction)]
        assert any("pwd" in action.command for action in cmd_actions)


class TestRecoverTimeoutError:
    """Tests for _recover_timeout_error method."""

    def test_returns_timeout_recovery_actions(self):
        """Test returns timeout recovery actions."""
        error_str = "timeout"
        actions = ErrorRecoveryStrategy._recover_timeout_error(error_str)

        assert len(actions) > 0
        assert any(isinstance(action, AgentThinkAction) for action in actions)
        assert any(isinstance(action, MessageAction) for action in actions)


class TestRecoverPermissionError:
    """Tests for _recover_permission_error method."""

    def test_extracts_file_path(self):
        """Test extracts file path from error message."""
        error_str = "Permission denied: '/etc/config.txt'"
        actions = ErrorRecoveryStrategy._recover_permission_error(error_str)

        assert len(actions) > 0
        # Should include ls command with the file path
        cmd_actions = [a for a in actions if isinstance(a, CmdRunAction)]
        assert any("config.txt" in action.command for action in cmd_actions)

    def test_no_file_path_uses_generic(self):
        """Test uses generic message when no file path found."""
        error_str = "Permission denied"
        actions = ErrorRecoveryStrategy._recover_permission_error(error_str)

        assert len(actions) > 0
        # Should still return actions with "the file"
        cmd_actions = [a for a in actions if isinstance(a, CmdRunAction)]
        assert len(cmd_actions) > 0


class TestRecoverDiskFullError:
    """Tests for _recover_disk_full_error method."""

    def test_includes_disk_usage_check(self):
        """Test includes df command."""
        error_str = "no space left on device"
        actions = ErrorRecoveryStrategy._recover_disk_full_error(error_str)

        assert len(actions) > 0
        cmd_actions = [a for a in actions if isinstance(a, CmdRunAction)]
        assert any("df" in action.command for action in cmd_actions)

    def test_includes_cleanup_commands(self):
        """Test includes cleanup commands."""
        error_str = "disk full"
        actions = ErrorRecoveryStrategy._recover_disk_full_error(error_str)

        cmd_actions = [a for a in actions if isinstance(a, CmdRunAction)]
        # Should include du (disk usage) and rm (remove) commands
        assert any("du" in action.command for action in cmd_actions)
        assert any("rm" in action.command for action in cmd_actions)


class TestRecoverSyntaxError:
    """Tests for _recover_syntax_error method."""

    def test_extracts_file_and_line(self):
        """Test extracts file and line number from error."""
        error_str = 'File "test.py", line 42, syntax error'
        actions = ErrorRecoveryStrategy._recover_syntax_error(error_str)

        assert len(actions) > 0
        cmd_actions = [a for a in actions if isinstance(a, CmdRunAction)]
        # Should include sed/cat command to show file context
        assert any(("sed" in action.command or "cat" in action.command) for action in cmd_actions)

    def test_no_file_info_returns_generic(self):
        """Test returns generic actions when can't extract file info."""
        error_str = "syntax error somewhere"
        actions = ErrorRecoveryStrategy._recover_syntax_error(error_str)

        assert len(actions) > 0
        assert any(isinstance(action, AgentThinkAction) for action in actions)


class TestRecoverUnknownError:
    """Tests for _recover_unknown_error method."""

    def test_returns_generic_recovery_actions(self):
        """Test returns generic recovery actions."""
        error_str = "unexpected error"
        actions = ErrorRecoveryStrategy._recover_unknown_error(error_str)

        assert len(actions) > 0
        assert any(isinstance(action, AgentThinkAction) for action in actions)
        assert any(isinstance(action, MessageAction) for action in actions)

    def test_truncates_long_error_messages(self):
        """Test truncates very long error messages in think action."""
        error_str = "x" * 300
        actions = ErrorRecoveryStrategy._recover_unknown_error(error_str)

        think_actions = [a for a in actions if isinstance(a, AgentThinkAction)]
        # Error should be truncated in thought
        for action in think_actions:
            assert len(action.thought) < 400  # Should be truncated at 200 + overhead
