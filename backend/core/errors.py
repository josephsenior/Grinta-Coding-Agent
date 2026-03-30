"""Canonical error types for boundary normalization.

These are intentionally small and generic. Layers (server/runtime/storage) can
wrap arbitrary exceptions into one of these for consistent handling.
"""

from __future__ import annotations

from typing import Any


class AppError(RuntimeError):
    """Base class for normalized app errors."""


class RetryableError(AppError):
    """Operation may succeed if retried."""


class UserActionRequiredError(AppError):
    """User must change config/inputs before retrying."""


class InvariantBrokenError(AppError):
    """A system invariant was violated; continuing may be unsafe."""


def classify_error(exc: Exception) -> type[AppError]:
    """Best-effort classification helper.

    Maps arbitrary exceptions to the closest canonical ``AppError`` subclass.
    Useful for boundary normalization in catch-all handlers.
    """
    if isinstance(exc, AppError):
        return type(exc)
    if isinstance(exc, ValueError | TypeError | KeyError):
        return UserActionRequiredError
    if isinstance(exc, TimeoutError | ConnectionError | OSError):
        return RetryableError
    if isinstance(exc, AssertionError | RuntimeError):
        return InvariantBrokenError
    return AppError


# ============================================================================
# Agent Runtime Errors (Phase 2: Bulletproof Execution)
# ============================================================================


class AgentRuntimeError(AppError):
    """Base class for all agent runtime errors with context."""

    def __init__(self, message: str, context: dict[str, Any] | None = None):
        super().__init__(message)
        self.context: dict[str, Any] = context or {}


class ToolExecutionError(AgentRuntimeError):
    """Raised when a tool fails to execute (e.g., file not found, syntax error)."""


class ContextLimitError(AgentRuntimeError):
    """Raised when the LLM context window is exceeded."""


class PlanningError(AgentRuntimeError):
    """Raised when the planner fails to produce a valid next step."""


class ModelProviderError(AgentRuntimeError):
    """Raised when the LLM provider API fails (timeouts, rate limits)."""


class ConfigurationError(AgentRuntimeError):
    """Raised when the agent is misconfigured."""


# ============================================================================
# Session / Lifecycle Errors
# ============================================================================


class SessionError(AppError):
    """Base class for session lifecycle errors."""


class SessionStartupError(SessionError):
    """Raised when agent-session startup fails (runtime, controller, etc.)."""


class SessionAlreadyActiveError(SessionError):
    """Raised when trying to start a session that is already running."""


class RuntimeConnectError(SessionError, RetryableError):
    """Raised when the runtime fails to connect during session startup."""


class SessionInvariantError(SessionError):
    """Raised when a session invariant is violated (ordering, IDs, etc.)."""


class PersistenceError(SessionError):
    """Raised when event persistence is unavailable or corrupted."""


class ReplayError(SessionError):
    """Raised when trajectory replay/export fails."""


class SocketConnectionError(AppError):
    """Raised when Socket.IO connection validation fails."""


class EventStreamError(AppError):
    """Raised when event-stream operations fail."""


__all__ = [
    "AppError",
    "RetryableError",
    "UserActionRequiredError",
    "InvariantBrokenError",
    "classify_error",
    "AgentRuntimeError",
    "ToolExecutionError",
    "ContextLimitError",
    "PlanningError",
    "ModelProviderError",
    "ConfigurationError",
    "SessionError",
    "SessionStartupError",
    "SessionAlreadyActiveError",
    "RuntimeConnectError",
    "SessionInvariantError",
    "PersistenceError",
    "ReplayError",
    "SocketConnectionError",
    "EventStreamError",
]

class AgentError(AppError):
    """Base class for all agent exceptions."""


class AgentNoInstructionError(AgentError):
    """Raised when an agent is invoked without required instructions.

    Args:
        message: Error message describing the missing instruction requirement.

    """

    def __init__(self, message: str = "Instruction must be provided") -> None:
        """Initialize the error with an optional custom message."""
        super().__init__(message)


class AgentEventTypeError(AgentError):
    """Raised when an agent receives an event of invalid type.

    Args:
        message: Error message describing the type mismatch.

    """

    def __init__(self, message: str = "Event must be a dictionary") -> None:
        """Initialize the error describing the invalid event type."""
        super().__init__(message)


class AgentAlreadyRegisteredError(AgentError):
    """Raised when attempting to register an agent class that already exists.

    Args:
        name: Optional name of the agent class that's already registered.

    """

    def __init__(self, name: str | None = None) -> None:
        """Initialize the error with the duplicate agent name if provided."""
        if name is not None:
            message = f"Agent class already registered under '{name}'"
        else:
            message = "Agent class already registered"
        super().__init__(message)


class AgentNotRegisteredError(AgentError):
    """Raised when attempting to access an unregistered agent class.

    Args:
        name: Optional name of the agent class that's not found.

    """

    def __init__(self, name: str | None = None) -> None:
        """Initialize the error with the missing agent name if provided."""
        if name is not None:
            message = f"No agent class registered under '{name}'"
        else:
            message = "No agent class registered"
        super().__init__(message)


class AgentStuckInLoopError(AgentError):
    """Raised when an agent gets stuck in a repetitive action loop.

    Args:
        message: Error message describing the loop condition.

    """

    def __init__(self, message: str = "Agent got stuck in a loop") -> None:
        """Initialize the error with a message describing the loop condition."""
        super().__init__(message)


class TaskInvalidStateError(AppError):
    """Raised when a task enters an invalid or unexpected state.

    Args:
        state: Optional description of the invalid state.

    """

    def __init__(self, state: str | None = None) -> None:
        """Initialize the error with the invalid state description if provided."""
        message = f"Invalid state {state}" if state is not None else "Invalid state"
        super().__init__(message)


class LLMMalformedActionError(AppError):
    """Raised when LLM returns a malformed action response.

    Args:
        message: Error message describing the malformed response.

    """

    def __init__(self, message: str = "Malformed response") -> None:
        """Initialize the error with details about the malformed response."""
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        """Return the stored malformed response message."""
        return self.message


class LLMNoActionError(AppError):
    """Raised when LLM fails to return an action when one is required.

    Args:
        message: Error message describing the missing action.

    """

    def __init__(self, message: str = "Agent must return an action") -> None:
        """Initialize the error with details about the missing action."""
        super().__init__(message)


class LLMResponseError(AppError):
    """Raised when unable to extract an action from LLM response.

    Args:
        message: Error message describing the extraction failure.

    """

    def __init__(
        self, message: str = "Failed to retrieve action from LLM response"
    ) -> None:
        """Initialize the error with information about the extraction failure."""
        super().__init__(message)


class LLMNoResponseError(AppError):
    """Raised when LLM returns no response at all.

    This is particularly seen with Gemini models in certain conditions.

    Args:
        message: Error message describing the missing response.

    """

    def __init__(
        self,
        message: str = "LLM did not return a response. This is only seen in Gemini models so far.",
    ) -> None:
        """Initialize the error with details about the missing LLM response."""
        super().__init__(message)


class UserCancelledError(AppError):
    """Raised when a user explicitly cancels an operation.

    Args:
        message: Error message describing the cancellation.

    """

    def __init__(self, message: str = "User cancelled the request") -> None:
        """Initialize the error with an optional cancellation message."""
        super().__init__(message)


class OperationCancelled(AppError):
    """Exception raised when an operation is cancelled (e.g. by a keyboard interrupt)."""

    def __init__(self, message: str = "Operation was cancelled") -> None:
        """Initialize the error with an optional cancellation message."""
        super().__init__(message)


class LLMContextWindowExceedError(AppError):
    """Raised when conversation history exceeds LLM context window limit.

    Args:
        message: Error message with suggestion to enable history truncation.

    """

    def __init__(
        self,
        message: str = (
            "Conversation history longer than LLM context window limit. "
            "Consider turning on enable_history_truncation config to avoid this error"
        ),
    ) -> None:
        """Initialize the error with guidance about the context window limit."""
        super().__init__(message)


class FunctionCallConversionError(AppError):
    """Exception raised when FunctionCallingConverter failed to convert a non-function call message
    to a function call message.

    This typically happens when there's a malformed message (e.g., missing <function=...> tags).
    But not due to LLM output.
    """

    def __init__(self, message: str) -> None:
        """Initialize the error with details about the conversion failure."""
        super().__init__(message)


class FunctionCallValidationError(AppError):
    """Exception raised when FunctionCallingConverter failed to validate a function call message.

    This typically happens when the LLM outputs unrecognized function call / parameter names / values.
    """

    def __init__(self, message: str) -> None:
        """Initialize the error with details about the validation failure."""
        super().__init__(message)


class FunctionCallNotExistsError(AppError):
    """Exception raised when an LLM call a tool that is not registered."""

    def __init__(self, message: str) -> None:
        """Initialize the error with the missing tool name or message."""
        super().__init__(message)


# Canonical runtime error class is defined in backend.core.errors.


class ResourceLimitExceededError(AppError):
    """Raised when a resource limit is exceeded (memory, CPU, disk, etc.).

    This exception is raised when:
    - Memory usage exceeds configured limit
    - Disk usage exceeds configured limit
    - File count exceeds configured limit
    - Other resource limits are violated

    Args:
        message: Error message describing which limit was exceeded

    """

    def __init__(self, message: str) -> None:
        """Initialize resource limit error with message."""
        super().__init__(message)


class PathValidationError(AppError):
    """Raised when path validation fails due to security concerns.

    This exception is raised when:
    - Directory traversal attempts are detected
    - Paths violate workspace boundaries
    - Invalid characters are found in paths
    - Path length or depth limits are exceeded

    Args:
        message: Error message describing the validation failure
        path: The invalid path (if available)

    """

    def __init__(self, message: str, path: str | None = None) -> None:
        """Initialize path validation error with message and optional path."""
        super().__init__(message)
        self.message = message
        self.path = path


class AgentRuntimeBuildError(AgentRuntimeError):
    """Exception raised when an agent runtime build operation fails."""


class AgentRuntimeTimeoutError(AgentRuntimeError):
    """Exception raised when an agent runtime operation times out."""


class AgentRuntimeUnavailableError(AgentRuntimeError):
    """Exception raised when an agent runtime is unavailable."""


class AgentRuntimeNotReadyError(AgentRuntimeUnavailableError):
    """Exception raised when an agent runtime is not ready."""


class AgentRuntimeDisconnectedError(AgentRuntimeUnavailableError):
    """Exception raised when an agent runtime is disconnected."""


class AgentRuntimeNotFoundError(AgentRuntimeUnavailableError):
    """Exception raised when an agent runtime is not found."""


class BrowserInitException(AppError):
    """Raised when browser environment initialization fails.

    Args:
        message: Error message describing the initialization failure.

    """

    def __init__(
        self, message: str = "Failed to initialize browser environment"
    ) -> None:
        """Initialize the error with details about the initialization failure."""
        super().__init__(message)


class BrowserUnavailableException(AppError):
    """Raised when browser environment is not available or not initialized.

    Args:
        message: Error message with instructions to check initialization.

    """

    def __init__(
        self,
        message: str = "Browser environment is not available, please check if has been initialized",
    ) -> None:
        """Initialize the error explaining why the browser is unavailable."""
        super().__init__(message)


class PlaybookError(AppError):
    """Base exception for all playbook errors."""


class PlaybookValidationError(PlaybookError):
    """Raised when there's a validation error in playbook metadata."""

    def __init__(self, message: str = "Playbook validation failed") -> None:
        """Initialize the error with details about the validation failure."""
        super().__init__(message)
