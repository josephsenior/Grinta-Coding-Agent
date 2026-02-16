"""Unit tests for backend.controller.error_recovery — Error classification and recovery."""

import pytest

from backend.controller.error_recovery import ErrorRecoveryStrategy, ErrorType
from backend.core.exceptions import (
    FunctionCallNotExistsError,
    FunctionCallValidationError,
)
from backend.events.action import AgentThinkAction, CmdRunAction, MessageAction
from backend.llm.exceptions import AuthenticationError


# ---------------------------------------------------------------------------
# Exception type classification
# ---------------------------------------------------------------------------


class TestClassifyByExceptionType:
    def test_import_error(self):
        error = ImportError("No module named 'requests'")
        assert ErrorRecoveryStrategy.classify_error(error) == ErrorType.MODULE_NOT_FOUND

    def test_module_not_found_error(self):
        error = ModuleNotFoundError("No module named 'pandas'")
        assert ErrorRecoveryStrategy.classify_error(error) == ErrorType.MODULE_NOT_FOUND

    def test_syntax_error(self):
        error = SyntaxError("invalid syntax")
        assert ErrorRecoveryStrategy.classify_error(error) == ErrorType.SYNTAX_ERROR

    def test_permission_error(self):
        error = PermissionError("Permission denied")
        assert ErrorRecoveryStrategy.classify_error(error) == ErrorType.PERMISSION_ERROR

    def test_timeout_error(self):
        error = TimeoutError("Operation timed out")
        assert ErrorRecoveryStrategy.classify_error(error) == ErrorType.TIMEOUT_ERROR

    def test_file_not_found_error(self):
        error = FileNotFoundError("No such file or directory")
        assert ErrorRecoveryStrategy.classify_error(error) == ErrorType.FILESYSTEM_ERROR

    def test_function_call_validation_error(self):
        error = FunctionCallValidationError("Invalid parameter")
        assert ErrorRecoveryStrategy.classify_error(error) == ErrorType.TOOL_CALL_ERROR

    def test_function_call_not_exists_error(self):
        error = FunctionCallNotExistsError("Function does not exist")
        assert ErrorRecoveryStrategy.classify_error(error) == ErrorType.TOOL_CALL_ERROR


# ---------------------------------------------------------------------------
# Message pattern classification
# ---------------------------------------------------------------------------


class TestClassifyByMessagePatterns:
    @pytest.mark.parametrize(
        "error_msg,expected_type",
        [
            ("runtime container terminated unexpectedly", ErrorType.RUNTIME_CRASH),
            ("Connection reset by peer", ErrorType.RUNTIME_CRASH),
            ("Broken pipe", ErrorType.RUNTIME_CRASH),
            ("runtime is not running", ErrorType.RUNTIME_CRASH),
        ],
    )
    def test_runtime_crash_patterns(self, error_msg, expected_type):
        error = RuntimeError(error_msg)
        assert ErrorRecoveryStrategy.classify_error(error) == expected_type

    @pytest.mark.parametrize(
        "error_msg,expected_type",
        [
            ("Connection refused", ErrorType.NETWORK_ERROR),
            ("Connection timeout", ErrorType.NETWORK_ERROR),
            ("Network unreachable", ErrorType.NETWORK_ERROR),
            ("DNS resolution failed", ErrorType.NETWORK_ERROR),
            ("Could not resolve host", ErrorType.NETWORK_ERROR),
            ("git clone failed", ErrorType.NETWORK_ERROR),
            ("curl error: Connection refused", ErrorType.NETWORK_ERROR),
            ("wget error: Unable to fetch", ErrorType.NETWORK_ERROR),
            ("Failed to fetch package", ErrorType.NETWORK_ERROR),
        ],
    )
    def test_network_error_patterns(self, error_msg, expected_type):
        error = Exception(error_msg)
        assert ErrorRecoveryStrategy.classify_error(error) == expected_type

    @pytest.mark.parametrize(
        "error_msg,expected_type",
        [
            ("no space left on device", ErrorType.DISK_FULL_ERROR),
            ("disk full", ErrorType.DISK_FULL_ERROR),
            ("permission denied", ErrorType.PERMISSION_ERROR),
            ("read-only file system", ErrorType.FILESYSTEM_ERROR),
            ("file not found", ErrorType.FILESYSTEM_ERROR),
            ("directory not found", ErrorType.FILESYSTEM_ERROR),
        ],
    )
    def test_filesystem_error_patterns(self, error_msg, expected_type):
        error = Exception(error_msg)
        assert ErrorRecoveryStrategy.classify_error(error) == expected_type

    @pytest.mark.parametrize(
        "error_msg",
        [
            "invalid json in response",
            "malformed json string",
            "unexpected parameter 'foo'",
            "missing required parameter 'bar'",
            "invalid argument type",
        ],
    )
    def test_tool_call_error_patterns(self, error_msg):
        error = Exception(error_msg)
        assert ErrorRecoveryStrategy.classify_error(error) == ErrorType.TOOL_CALL_ERROR

    @pytest.mark.parametrize(
        "error_msg",
        [
            "timeout after 30 seconds",
            "operation timed out",
            "deadline exceeded",
            "operation is too slow",
        ],
    )
    def test_timeout_error_patterns(self, error_msg):
        error = Exception(error_msg)
        assert ErrorRecoveryStrategy.classify_error(error) == ErrorType.TIMEOUT_ERROR


# ---------------------------------------------------------------------------
# Unknown error classification
# ---------------------------------------------------------------------------


class TestUnknownErrorClassification:
    def test_unrecognized_error_message(self):
        error = Exception("Something completely unexpected")
        assert ErrorRecoveryStrategy.classify_error(error) == ErrorType.UNKNOWN_ERROR

    def test_generic_runtime_error(self):
        error = RuntimeError("Generic error")
        assert ErrorRecoveryStrategy.classify_error(error) == ErrorType.UNKNOWN_ERROR


# ---------------------------------------------------------------------------
# Recovery action generation - MODULE_NOT_FOUND
# ---------------------------------------------------------------------------


class TestRecoverModuleNotFound:
    def test_extract_single_module_name(self):
        error = ImportError("No module named 'requests'")
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.MODULE_NOT_FOUND, error
        )
        assert len(actions) == 3
        assert isinstance(actions[0], AgentThinkAction)
        assert isinstance(actions[1], CmdRunAction)
        assert isinstance(actions[2], MessageAction)
        assert actions[1].command == "pip install requests"

    def test_extract_nested_module_name(self):
        error = ImportError("No module named 'requests.auth'")
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.MODULE_NOT_FOUND, error
        )
        # Should extract base package 'requests', not 'requests.auth'
        assert actions[1].command == "pip install requests"

    def test_module_not_found_without_pattern(self):
        error = ImportError("Import error occurred")
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.MODULE_NOT_FOUND, error
        )
        assert len(actions) == 1
        assert isinstance(actions[0], AgentThinkAction)


# ---------------------------------------------------------------------------
# Recovery action generation - Other error types
# ---------------------------------------------------------------------------


class TestRecoveryActionsForOtherErrors:
    def test_runtime_crash_recovery(self):
        error = RuntimeError("runtime container terminated")
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.RUNTIME_CRASH, error
        )
        assert len(actions) > 0
        assert any(isinstance(a, AgentThinkAction) for a in actions)

    def test_network_error_recovery(self):
        error = Exception("Connection refused")
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.NETWORK_ERROR, error
        )
        assert len(actions) > 0

    def test_timeout_error_recovery(self):
        error = TimeoutError("Operation timed out")
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.TIMEOUT_ERROR, error
        )
        assert len(actions) > 0

    def test_permission_error_recovery(self):
        error = PermissionError("Permission denied")
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.PERMISSION_ERROR, error
        )
        assert len(actions) > 0

    def test_disk_full_error_recovery(self):
        error = Exception("No space left on device")
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.DISK_FULL_ERROR, error
        )
        assert len(actions) > 0

    def test_syntax_error_recovery(self):
        error = SyntaxError("invalid syntax")
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.SYNTAX_ERROR, error
        )
        assert len(actions) > 0

    def test_unknown_error_recovery(self):
        error = Exception("Unknown error")
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.UNKNOWN_ERROR, error
        )
        # Unknown errors should return generic recovery actions
        assert isinstance(actions, list)


# ---------------------------------------------------------------------------
# Authentication error handling
# ---------------------------------------------------------------------------


class TestAuthenticationErrorHandling:
    def test_authentication_error_blocks_recovery(self):
        """AuthenticationError should not trigger recovery to avoid loops."""
        error = AuthenticationError("Invalid API key")
        # Classify as tool call error (generic classification)
        error_type = ErrorType.TOOL_CALL_ERROR
        actions = ErrorRecoveryStrategy.get_recovery_actions(error_type, error)
        # Should return empty list to avoid infinite retry loops
        assert actions == []


# ---------------------------------------------------------------------------
# Pattern matching utility
# ---------------------------------------------------------------------------


class TestMatchesPatterns:
    def test_pattern_matches(self):
        patterns = [r"connection.*refused", r"network.*error"]
        assert ErrorRecoveryStrategy._matches_patterns(
            "connection refused", patterns
        )
        assert ErrorRecoveryStrategy._matches_patterns("network unreachable error", patterns)

    def test_pattern_no_match(self):
        patterns = [r"connection.*refused", r"network.*error"]
        assert not ErrorRecoveryStrategy._matches_patterns(
            "disk full", patterns
        )

    def test_case_insensitive_matching(self):
        patterns = [r"Connection.*Refused"]
        assert ErrorRecoveryStrategy._matches_patterns(
            "connection refused", patterns
        )
        assert ErrorRecoveryStrategy._matches_patterns(
            "CONNECTION REFUSED", patterns
        )
