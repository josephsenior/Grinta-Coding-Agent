"""Tests for backend.controller.error_recovery — ErrorType + ErrorRecoveryStrategy."""

from __future__ import annotations


from backend.controller.error_recovery import ErrorRecoveryStrategy, ErrorType
from backend.core.exceptions import (
    FunctionCallNotExistsError,
    FunctionCallValidationError,
)


# ---------------------------------------------------------------------------
# ErrorType enum
# ---------------------------------------------------------------------------
class TestErrorType:
    def test_all_values(self):
        expected = {
            "module_not_found",
            "runtime_crash",
            "network_error",
            "filesystem_error",
            "tool_call_error",
            "timeout_error",
            "permission_error",
            "disk_full_error",
            "syntax_error",
            "unknown_error",
        }
        actual = {e.value for e in ErrorType}
        assert actual == expected


# ---------------------------------------------------------------------------
# classify_error — by exception type
# ---------------------------------------------------------------------------
class TestClassifyByExceptionType:
    def test_import_error(self):
        assert (
            ErrorRecoveryStrategy.classify_error(ImportError("no mod"))
            == ErrorType.MODULE_NOT_FOUND
        )

    def test_module_not_found(self):
        assert (
            ErrorRecoveryStrategy.classify_error(ModuleNotFoundError("x"))
            == ErrorType.MODULE_NOT_FOUND
        )

    def test_syntax_error(self):
        assert (
            ErrorRecoveryStrategy.classify_error(SyntaxError("bad"))
            == ErrorType.SYNTAX_ERROR
        )

    def test_permission_error(self):
        assert (
            ErrorRecoveryStrategy.classify_error(PermissionError("denied"))
            == ErrorType.PERMISSION_ERROR
        )

    def test_timeout_error(self):
        assert (
            ErrorRecoveryStrategy.classify_error(TimeoutError("slow"))
            == ErrorType.TIMEOUT_ERROR
        )

    def test_file_not_found(self):
        assert (
            ErrorRecoveryStrategy.classify_error(FileNotFoundError("gone"))
            == ErrorType.FILESYSTEM_ERROR
        )

    def test_is_a_directory(self):
        assert (
            ErrorRecoveryStrategy.classify_error(IsADirectoryError("dir"))
            == ErrorType.FILESYSTEM_ERROR
        )

    def test_not_a_directory(self):
        assert (
            ErrorRecoveryStrategy.classify_error(NotADirectoryError("file"))
            == ErrorType.FILESYSTEM_ERROR
        )

    def test_function_call_validation_error(self):
        assert (
            ErrorRecoveryStrategy.classify_error(
                FunctionCallValidationError("bad param")
            )
            == ErrorType.TOOL_CALL_ERROR
        )

    def test_function_call_not_exists_error(self):
        assert (
            ErrorRecoveryStrategy.classify_error(FunctionCallNotExistsError("no_func"))
            == ErrorType.TOOL_CALL_ERROR
        )


# ---------------------------------------------------------------------------
# classify_error — by message patterns
# ---------------------------------------------------------------------------
class TestClassifyByMessage:
    def test_runtime_crash(self):
        assert (
            ErrorRecoveryStrategy.classify_error(Exception("runtime terminated"))
            == ErrorType.RUNTIME_CRASH
        )

    def test_connection_reset(self):
        assert (
            ErrorRecoveryStrategy.classify_error(Exception("connection reset"))
            == ErrorType.RUNTIME_CRASH
        )

    def test_broken_pipe(self):
        assert (
            ErrorRecoveryStrategy.classify_error(Exception("broken pipe"))
            == ErrorType.RUNTIME_CRASH
        )

    def test_network_connection_refused(self):
        assert (
            ErrorRecoveryStrategy.classify_error(Exception("connection refused"))
            == ErrorType.NETWORK_ERROR
        )

    def test_network_dns_failed(self):
        assert (
            ErrorRecoveryStrategy.classify_error(Exception("dns resolution failed"))
            == ErrorType.NETWORK_ERROR
        )

    def test_network_git_clone(self):
        assert (
            ErrorRecoveryStrategy.classify_error(Exception("git clone failed"))
            == ErrorType.NETWORK_ERROR
        )

    def test_filesystem_no_space(self):
        assert (
            ErrorRecoveryStrategy.classify_error(Exception("no space left on device"))
            == ErrorType.DISK_FULL_ERROR
        )

    def test_filesystem_disk_full(self):
        assert (
            ErrorRecoveryStrategy.classify_error(Exception("disk full"))
            == ErrorType.DISK_FULL_ERROR
        )

    def test_filesystem_permission_denied(self):
        assert (
            ErrorRecoveryStrategy.classify_error(Exception("permission denied for /x"))
            == ErrorType.PERMISSION_ERROR
        )

    def test_tool_call_invalid_json(self):
        assert (
            ErrorRecoveryStrategy.classify_error(Exception("invalid json in call"))
            == ErrorType.TOOL_CALL_ERROR
        )

    def test_timeout_message(self):
        assert (
            ErrorRecoveryStrategy.classify_error(Exception("operation timed out"))
            == ErrorType.TIMEOUT_ERROR
        )

    def test_unknown(self):
        assert (
            ErrorRecoveryStrategy.classify_error(Exception("something weird"))
            == ErrorType.UNKNOWN_ERROR
        )


# ---------------------------------------------------------------------------
# _matches_patterns
# ---------------------------------------------------------------------------
class TestMatchesPatterns:
    def test_returns_true(self):
        assert ErrorRecoveryStrategy._matches_patterns("foo timeout bar", [r"timeout"])

    def test_returns_false(self):
        assert not ErrorRecoveryStrategy._matches_patterns("safe text", [r"timeout"])


# ---------------------------------------------------------------------------
# get_recovery_actions
# ---------------------------------------------------------------------------
class TestGetRecoveryActions:
    def test_module_not_found_with_package(self):
        err = ImportError("No module named 'requests'")
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.MODULE_NOT_FOUND, err
        )
        assert len(actions) == 3
        assert "pip install requests" in actions[1].command

    def test_module_not_found_submodule(self):
        err = ImportError("No module named 'requests.auth'")
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.MODULE_NOT_FOUND, err
        )
        assert "pip install requests" in actions[1].command

    def test_module_not_found_no_match(self):
        err = ImportError("Something else happened")
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.MODULE_NOT_FOUND, err
        )
        assert len(actions) == 1  # Just the think action

    def test_runtime_crash(self):
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.RUNTIME_CRASH, Exception("runtime terminated")
        )
        assert len(actions) >= 2

    def test_network_error_git(self):
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.NETWORK_ERROR, Exception("git clone failed")
        )
        assert any("git config" in a.command for a in actions if hasattr(a, "command"))

    def test_network_error_general(self):
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.NETWORK_ERROR, Exception("connection refused")
        )
        assert len(actions) >= 2

    def test_filesystem_error_file_not_found(self):
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.FILESYSTEM_ERROR, Exception("file 'foo.py' not found")
        )
        assert any("find" in a.command for a in actions if hasattr(a, "command"))

    def test_filesystem_error_generic(self):
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.FILESYSTEM_ERROR, Exception("read-only file system")
        )
        assert len(actions) >= 2

    def test_tool_call_error_returns_feedback(self):
        """Tool call errors return feedback for self-correction."""
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.TOOL_CALL_ERROR, Exception("invalid json")
        )
        assert actions
        assert any("tool call error" in (a.thought or "").lower() for a in actions if hasattr(a, "thought"))

    def test_tool_call_error_auth_related(self):
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.TOOL_CALL_ERROR, Exception("authentication failed")
        )
        assert actions == []

    def test_timeout_error(self):
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.TIMEOUT_ERROR, Exception("timed out")
        )
        assert actions

    def test_permission_error(self):
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.PERMISSION_ERROR, Exception("permission denied for '/etc/x'")
        )
        assert len(actions) >= 2

    def test_disk_full_error(self):
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.DISK_FULL_ERROR, Exception("no space left on device")
        )
        assert any("df" in a.command for a in actions if hasattr(a, "command"))

    def test_syntax_error_with_file_info(self):
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.SYNTAX_ERROR, Exception('File "test.py", line 10')
        )
        assert any("sed" in a.command for a in actions if hasattr(a, "command"))

    def test_syntax_error_no_file(self):
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.SYNTAX_ERROR, Exception("invalid syntax")
        )
        assert actions

    def test_unknown_error(self):
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.UNKNOWN_ERROR, Exception("mystery")
        )
        assert actions

    def test_authentication_error_returns_empty(self):
        from backend.llm.exceptions import AuthenticationError

        err = AuthenticationError("invalid key")
        actions = ErrorRecoveryStrategy.get_recovery_actions(
            ErrorType.UNKNOWN_ERROR, err
        )
        assert actions == []
