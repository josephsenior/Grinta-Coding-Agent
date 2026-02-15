"""Error recovery system for automatic error handling.

This module provides comprehensive recovery for non-LLM errors including:
- ImportError (auto pip install)
- Runtime crashes (container restart detection)
- Network errors (retry with backoff)
- Filesystem errors (disk space, permissions)
- Tool call errors (parameter validation)
- Timeout errors (extend timeout or split task)

Note: LLM errors (APIError, RateLimitError, etc.) are already handled by the
LLM RetryMixin with 6 retries and exponential backoff.
"""

from __future__ import annotations

import logging
import re
from enum import Enum

from backend.core.exceptions import (
    FunctionCallNotExistsError,
    FunctionCallValidationError,
)
from backend.events.action import (
    Action,
    AgentThinkAction,
    CmdRunAction,
    MessageAction,
)
from backend.llm.exceptions import AuthenticationError

logger = logging.getLogger(__name__)


class ErrorType(str, Enum):
    """Types of non-LLM errors that can be recovered."""

    MODULE_NOT_FOUND = "module_not_found"
    RUNTIME_CRASH = "runtime_crash"
    NETWORK_ERROR = "network_error"
    FILESYSTEM_ERROR = "filesystem_error"
    TOOL_CALL_ERROR = "tool_call_error"
    TIMEOUT_ERROR = "timeout_error"
    PERMISSION_ERROR = "permission_error"
    DISK_FULL_ERROR = "disk_full_error"
    SYNTAX_ERROR = "syntax_error"
    UNKNOWN_ERROR = "unknown_error"


class ErrorRecoveryStrategy:
    """Comprehensive error recovery strategy for autonomous agents.

    Provides targeted recovery actions for various error types:
    - Auto pip install for missing modules
    - Runtime restart detection and recovery
    - Network retry with exponential backoff
    - Filesystem error handling (disk space, permissions)
    - Tool call parameter fixing
    - Timeout handling

    Note: LLM errors are already handled by LLM RetryMixin.
    """

    # Error message patterns for classification
    RUNTIME_CRASH_PATTERNS = [
        r"runtime.*terminated",
        r"connection.*reset",
        r"broken pipe",
        r"runtime.*not.*running",
    ]

    NETWORK_ERROR_PATTERNS = [
        r"connection.*refused",
        r"connection.*timeout",
        r"network.*unreachable",
        r"dns.*resolution.*failed",
        r"could not resolve host",
        r"git.*clone.*failed",
        r"curl.*error",
        r"wget.*error",
        r"failed to fetch",
    ]

    FILESYSTEM_ERROR_PATTERNS = [
        r"no space left on device",
        r"disk.*full",
        r"permission denied",
        r"read-only file system",
        r"file.*not.*found",
        r"directory.*not.*found",
    ]

    TOOL_CALL_ERROR_PATTERNS = [
        r"invalid.*json",
        r"malformed.*json",
        r"unexpected.*parameter",
        r"missing.*required.*parameter",
        r"invalid.*argument",
    ]

    TIMEOUT_ERROR_PATTERNS = [
        r"timeout",
        r"timed out",
        r"deadline exceeded",
        r"operation.*too.*slow",
    ]

    @staticmethod
    def classify_error(error: Exception) -> ErrorType:
        """Classify an error to determine recovery strategy.

        Args:
            error: The exception that occurred

        Returns:
            ErrorType enum value

        """
        # Check specific exception types first
        error_type = ErrorRecoveryStrategy._classify_by_exception_type(error)
        if error_type:
            return error_type

        # Check error message patterns
        error_str = str(error).lower()
        error_type = ErrorRecoveryStrategy._classify_by_message_patterns(error_str)

        if error_type == ErrorType.UNKNOWN_ERROR:
            logger.debug(
                "Error type '%s' could not be classified: %s",
                type(error).__name__,
                error_str[:100],
            )

        return error_type

    @staticmethod
    def _classify_by_exception_type(error: Exception) -> ErrorType | None:
        """Classify error by exception type.

        Args:
            error: Exception to classify

        Returns:
            ErrorType if matched, None otherwise

        """
        if isinstance(error, (ImportError, ModuleNotFoundError)):
            return ErrorType.MODULE_NOT_FOUND
        if isinstance(error, SyntaxError):
            return ErrorType.SYNTAX_ERROR
        if isinstance(error, PermissionError):
            return ErrorType.PERMISSION_ERROR
        if isinstance(error, TimeoutError):
            return ErrorType.TIMEOUT_ERROR
        if isinstance(
            error, (FileNotFoundError, IsADirectoryError, NotADirectoryError)
        ):
            return ErrorType.FILESYSTEM_ERROR
        if isinstance(error, (FunctionCallValidationError, FunctionCallNotExistsError)):
            return ErrorType.TOOL_CALL_ERROR
        return None

    @staticmethod
    def _classify_by_message_patterns(error_str: str) -> ErrorType:
        """Classify error by message patterns.

        Args:
            error_str: Lowercased error message

        Returns:
            ErrorType enum value

        """
        if ErrorRecoveryStrategy._matches_patterns(
            error_str, ErrorRecoveryStrategy.RUNTIME_CRASH_PATTERNS
        ):
            return ErrorType.RUNTIME_CRASH
        if ErrorRecoveryStrategy._matches_patterns(
            error_str, ErrorRecoveryStrategy.NETWORK_ERROR_PATTERNS
        ):
            return ErrorType.NETWORK_ERROR
        if ErrorRecoveryStrategy._matches_patterns(
            error_str, ErrorRecoveryStrategy.FILESYSTEM_ERROR_PATTERNS
        ):
            return ErrorRecoveryStrategy._classify_filesystem_error(error_str)
        if ErrorRecoveryStrategy._matches_patterns(
            error_str, ErrorRecoveryStrategy.TOOL_CALL_ERROR_PATTERNS
        ):
            return ErrorType.TOOL_CALL_ERROR
        if ErrorRecoveryStrategy._matches_patterns(
            error_str, ErrorRecoveryStrategy.TIMEOUT_ERROR_PATTERNS
        ):
            return ErrorType.TIMEOUT_ERROR

        return ErrorType.UNKNOWN_ERROR

    @staticmethod
    def _classify_filesystem_error(error_str: str) -> ErrorType:
        """Classify filesystem error subtype.

        Args:
            error_str: Lowercased error message

        Returns:
            Specific filesystem error type

        """
        if "no space" in error_str or "disk full" in error_str:
            return ErrorType.DISK_FULL_ERROR
        if "permission" in error_str:
            return ErrorType.PERMISSION_ERROR
        return ErrorType.FILESYSTEM_ERROR

    @staticmethod
    def _matches_patterns(text: str, patterns: list[str]) -> bool:
        """Check if text matches any of the patterns.

        Args:
            text: Text to check
            patterns: List of regex patterns

        Returns:
            True if any pattern matches

        """
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)

    @staticmethod
    def get_recovery_actions(error_type: ErrorType, error: Exception) -> list[Action]:
        """Get recovery actions for the specified error type.

        Args:
            error_type: The classified error type
            error: The original exception

        Returns:
            List of recovery actions to execute

        """
        error_str = str(error)

        # Do not attempt recovery actions that require LLM calls if there's an authentication error
        # This prevents infinite loops where tool call errors trigger recovery actions that fail due to auth issues
        if isinstance(error, AuthenticationError):
            logger.info(
                "Skipping recovery actions for AuthenticationError - requires user intervention"
            )
            return []

        recovery_map = {
            ErrorType.MODULE_NOT_FOUND: ErrorRecoveryStrategy._recover_module_not_found,
            ErrorType.RUNTIME_CRASH: ErrorRecoveryStrategy._recover_runtime_crash,
            ErrorType.NETWORK_ERROR: ErrorRecoveryStrategy._recover_network_error,
            ErrorType.FILESYSTEM_ERROR: ErrorRecoveryStrategy._recover_filesystem_error,
            ErrorType.TOOL_CALL_ERROR: ErrorRecoveryStrategy._recover_tool_call_error,
            ErrorType.TIMEOUT_ERROR: ErrorRecoveryStrategy._recover_timeout_error,
            ErrorType.PERMISSION_ERROR: ErrorRecoveryStrategy._recover_permission_error,
            ErrorType.DISK_FULL_ERROR: ErrorRecoveryStrategy._recover_disk_full_error,
            ErrorType.SYNTAX_ERROR: ErrorRecoveryStrategy._recover_syntax_error,
            ErrorType.UNKNOWN_ERROR: ErrorRecoveryStrategy._recover_unknown_error,
        }

        recovery_func = recovery_map.get(error_type)
        if recovery_func:
            return recovery_func(error_str)

        return []

    @staticmethod
    def _recover_module_not_found(error_str: str) -> list[Action]:
        """Recover from module not found error by installing the package."""
        # Extract package name from error message
        match = re.search(r"No module named ['\"]([^'\"]+)['\"]", error_str)
        if match:
            package = match.group(1)
            # Try to get base package name (e.g., 'requests' from 'requests.auth')
            base_package = package.split(".")[0]

            return [
                AgentThinkAction(
                    thought=f"Module '{package}' not found. Attempting to install package '{base_package}'...",
                ),
                CmdRunAction(command=f"pip install {base_package}"),
                MessageAction(
                    content=f"Installed missing package '{base_package}'. Retrying the operation...",
                ),
            ]

        return [
            AgentThinkAction(
                thought="Module not found error detected. Will retry after analyzing dependencies...",
            ),
        ]

    @staticmethod
    def _recover_runtime_crash(error_str: str) -> list[Action]:
        """Recover from runtime/container crash."""
        return [
            AgentThinkAction(
                thought="Runtime crash detected. The container may have restarted. "
                "Checking runtime status and re-establishing connection...",
            ),
            CmdRunAction(command="echo 'Runtime check: $HOSTNAME'"),
            MessageAction(
                content="Runtime appears to have crashed and restarted. "
                "Note: Any previously established environment state may have been lost. "
                "Will re-verify environment setup before continuing.",
            ),
        ]

    @staticmethod
    def _recover_network_error(error_str: str) -> list[Action]:
        """Recover from network errors with retry suggestions."""
        # Check if it's a git operation
        if "git" in error_str.lower():
            return [
                AgentThinkAction(
                    thought="Git network error detected. Will retry with increased timeout...",
                ),
                CmdRunAction(command="git config --global http.postBuffer 524288000"),
                CmdRunAction(command="git config --global http.lowSpeedLimit 0"),
                CmdRunAction(command="git config --global http.lowSpeedTime 999999"),
                MessageAction(
                    content="Configured git for better network resilience. Retrying operation...",
                ),
            ]

        # General network error
        return [
            AgentThinkAction(
                thought="Network error detected. Will retry after brief wait...",
            ),
            CmdRunAction(command="sleep 2"),
            MessageAction(
                content="Network connectivity issue encountered. "
                "Will retry the operation. If this persists, please check network connection.",
            ),
        ]

    @staticmethod
    def _recover_filesystem_error(error_str: str) -> list[Action]:
        """Recover from filesystem errors."""
        # Check if it's a file not found error
        if "not found" in error_str.lower() or "no such file" in error_str.lower():
            # Extract possible filename
            match = re.search(r"['\"]([^'\"]+)['\"]", error_str)
            filename = match.group(1) if match else None

            actions = [
                AgentThinkAction(
                    thought="File not found error. Verifying current directory and listing files...",
                ),
                CmdRunAction(command="pwd"),
                CmdRunAction(command="ls -F"),
            ]

            if filename:
                # If we have a filename, try to find it
                base_name = filename.split("/")[-1]
                if base_name and len(base_name) > 0:
                    actions.append(
                        CmdRunAction(
                            command=f"find . -name '*{base_name}*' -not -path '*/.*' -maxdepth 3 2>/dev/null || true"
                        )
                    )

            actions.append(
                MessageAction(
                    content="File access failed. Searching for the file in the current and nearby directories."
                )
            )
            return actions

        return [
            AgentThinkAction(
                thought="Filesystem error detected. Checking directory structure and permissions...",
            ),
            CmdRunAction(command="pwd"),
            CmdRunAction(command="ls -la"),
            MessageAction(
                content="Filesystem error encountered. Verified current directory. "
                "Will create necessary directories or adjust approach.",
            ),
        ]

    @staticmethod
    def _recover_tool_call_error(error_str: str) -> list[Action]:
        """Recover from tool call/parameter errors."""
        # Check if error might be related to authentication issues
        auth_indicators = [
            "authentication",
            "api key",
            "unauthorized",
            "invalid credentials",
            "authenticate",
        ]
        if any(indicator in error_str.lower() for indicator in auth_indicators):
            logger.info(
                "Tool call error appears to be authentication-related, skipping recovery actions that require LLM calls"
            )
            return []

        # To prevent infinite loops, we should avoid creating any actions that would trigger LLM calls
        # because tool call errors often happen during LLM processing, and creating more actions
        # (like AgentThinkAction or MessageAction) would cause more LLM calls and potentially more tool call errors.
        logger.error(
            "Tool call parameter error: %s%s",
            error_str[:200],
            "..." if len(error_str) > 200 else "",
        )
        logger.info(
            "Skipping recovery actions for tool call error to prevent infinite loop"
        )

        # Return empty list to prevent any recovery actions that could trigger more LLM calls
        return []

    @staticmethod
    def _recover_timeout_error(error_str: str) -> list[Action]:
        """Recover from timeout errors."""
        return [
            AgentThinkAction(
                thought="Timeout error detected. The operation may be taking too long. "
                "Will try splitting into smaller operations or extending timeout...",
            ),
            MessageAction(
                content="Operation timed out. Will try a different approach: "
                "either breaking the task into smaller steps or using a more efficient method.",
            ),
        ]

    @staticmethod
    def _recover_permission_error(error_str: str) -> list[Action]:
        """Recover from permission errors."""
        # Check what file/directory had the permission issue
        file_match = re.search(r'["\']([^"\']+)["\']', error_str)
        file_path = file_match.group(1) if file_match else "the file"

        return [
            AgentThinkAction(
                thought=f"Permission denied for {file_path}. Checking current permissions...",
            ),
            CmdRunAction(
                command=f"ls -l {file_path} 2>/dev/null || echo 'File not accessible'"
            ),
            MessageAction(
                content=f"Permission error for {file_path}. "
                "Will try an alternative approach that doesn't require special permissions.",
            ),
        ]

    @staticmethod
    def _recover_disk_full_error(error_str: str) -> list[Action]:
        """Recover from disk full errors."""
        return [
            AgentThinkAction(
                thought="Disk full error detected. Checking disk usage and cleaning up temporary files...",
            ),
            CmdRunAction(command="df -h"),
            CmdRunAction(
                command="du -sh /tmp/* 2>/dev/null | sort -hr | head -10 || true"
            ),
            CmdRunAction(command="rm -rf /tmp/tmp* /tmp/pip* 2>/dev/null || true"),
            MessageAction(
                content="Disk space exhausted. Attempted to clean temporary files. "
                "If issue persists, the operation may need to be simplified or split into smaller parts.",
            ),
        ]

    @staticmethod
    def _recover_syntax_error(error_str: str) -> list[Action]:
        """Recover from syntax errors."""
        # Try to extract file and line info
        file_match = re.search(r"File \"([^\"]+)\", line (\d+)", error_str)
        if file_match:
            file_path = file_match.group(1)
            line_num = file_match.group(2)

            # Start and end lines for context (5 lines before and after)
            try:
                line_val = int(line_num)
                start_line = max(1, line_val - 5)
                end_line = line_val + 5

                return [
                    AgentThinkAction(
                        thought=f"Syntax error detected in {file_path} at line {line_num}. "
                        "Reading surrounding code to identify the issue...",
                    ),
                    CmdRunAction(
                        command=f"sed -n '{start_line},{end_line}p' {file_path} || cat {file_path}"
                    ),
                    MessageAction(
                        content=f"Syntax error in {file_path}:{line_num}. Reviewing code context to propose a fix.",
                    ),
                ]
            except ValueError:
                pass

        return [
            AgentThinkAction(
                thought="Syntax error detected. Reviewing the error message to identify the cause...",
            ),
            MessageAction(
                content="Syntax error encountered. Please check the code structure. "
                "Will review the error documentation/message for more details.",
            ),
        ]

    @staticmethod
    def _recover_unknown_error(error_str: str) -> list[Action]:
        """Generic recovery for unknown errors."""
        return [
            AgentThinkAction(
                thought=f"Unexpected error encountered: {error_str[:200]}. "
                "Will analyze the error and adjust approach...",
            ),
            MessageAction(
                content="An unexpected error occurred. Reviewing the error message and adjusting the approach. "
                "If this error persists, a different strategy may be needed.",
            ),
        ]
