"""Tests for backend.core.exceptions — custom exception hierarchy."""

from __future__ import annotations

import pytest

from backend.core.exceptions import (
    AgentAlreadyRegisteredError,
    AgentError,
    AgentEventTypeError,
    AgentNoInstructionError,
    AgentNotRegisteredError,
    AgentStuckInLoopError,
    BrowserInitException,
    BrowserUnavailableException,
    FunctionCallConversionError,
    FunctionCallNotExistsError,
    FunctionCallValidationError,
    LLMContextWindowExceedError,
    LLMMalformedActionError,
    LLMNoActionError,
    LLMNoResponseError,
    LLMResponseError,
    OperationCancelled,
    PathValidationError,
    PlaybookError,
    PlaybookValidationError,
    ResourceLimitExceededError,
    TaskInvalidStateError,
    UserCancelledError,
)
from backend.core.errors import ForgeError


# ---------------------------------------------------------------------------
# Test that all exceptions are subclasses of ForgeError or AgentError
# ---------------------------------------------------------------------------

class TestExceptionHierarchy:
    """Tests for the exception class hierarchy."""

    def test_agent_error_is_forge_error(self):
        assert issubclass(AgentError, ForgeError)

    def test_agent_subclasses(self):
        for exc_cls in [
            AgentNoInstructionError,
            AgentEventTypeError,
            AgentAlreadyRegisteredError,
            AgentNotRegisteredError,
            AgentStuckInLoopError,
        ]:
            assert issubclass(exc_cls, AgentError)

    def test_llm_errors_are_forge_errors(self):
        for exc_cls in [
            LLMMalformedActionError,
            LLMNoActionError,
            LLMResponseError,
            LLMNoResponseError,
            LLMContextWindowExceedError,
        ]:
            assert issubclass(exc_cls, ForgeError)

    def test_function_call_errors(self):
        for exc_cls in [
            FunctionCallConversionError,
            FunctionCallValidationError,
            FunctionCallNotExistsError,
        ]:
            assert issubclass(exc_cls, ForgeError)

    def test_playbook_errors(self):
        assert issubclass(PlaybookError, ForgeError)
        assert issubclass(PlaybookValidationError, PlaybookError)


# ---------------------------------------------------------------------------
# Individual exception creation tests
# ---------------------------------------------------------------------------

class TestExceptionCreation:
    """Tests for creating and inspecting exceptions."""

    def test_agent_no_instruction_default(self):
        err = AgentNoInstructionError()
        assert "Instruction must be provided" in str(err)

    def test_agent_no_instruction_custom(self):
        err = AgentNoInstructionError("custom msg")
        assert "custom msg" in str(err)

    def test_agent_event_type_default(self):
        err = AgentEventTypeError()
        assert "dictionary" in str(err)

    def test_already_registered_with_name(self):
        err = AgentAlreadyRegisteredError("MyAgent")
        assert "MyAgent" in str(err)

    def test_already_registered_without_name(self):
        err = AgentAlreadyRegisteredError()
        assert "already registered" in str(err)

    def test_not_registered_with_name(self):
        err = AgentNotRegisteredError("UnknownAgent")
        assert "UnknownAgent" in str(err)

    def test_not_registered_without_name(self):
        err = AgentNotRegisteredError()
        assert "No agent" in str(err)

    def test_stuck_in_loop(self):
        err = AgentStuckInLoopError("Repeated 5 times")
        assert "Repeated 5 times" in str(err)

    def test_task_invalid_state(self):
        err = TaskInvalidStateError("CRASHED")
        assert "CRASHED" in str(err)

    def test_task_invalid_state_default(self):
        err = TaskInvalidStateError()
        assert "Invalid state" in str(err)

    def test_malformed_action(self):
        err = LLMMalformedActionError("bad json")
        assert err.message == "bad json"
        assert str(err) == "bad json"

    def test_no_action_default(self):
        err = LLMNoActionError()
        assert "must return" in str(err)

    def test_llm_response_error(self):
        err = LLMResponseError("parse failed")
        assert "parse failed" in str(err)

    def test_llm_no_response(self):
        err = LLMNoResponseError()
        assert "Gemini" in str(err)

    def test_user_cancelled(self):
        err = UserCancelledError()
        assert "cancelled" in str(err)

    def test_operation_cancelled(self):
        err = OperationCancelled()
        assert "cancelled" in str(err)

    def test_context_window_exceed(self):
        err = LLMContextWindowExceedError()
        assert "context window" in str(err)

    def test_function_call_errors_with_message(self):
        for cls in [FunctionCallConversionError, FunctionCallValidationError, FunctionCallNotExistsError]:
            err = cls("test message")
            assert "test message" in str(err)

    def test_resource_limit_exceeded(self):
        err = ResourceLimitExceededError("Memory limit: 2GB")
        assert "Memory limit" in str(err)

    def test_path_validation_error(self):
        err = PathValidationError("traversal detected", "/etc/passwd")
        assert err.message == "traversal detected"
        assert err.path == "/etc/passwd"

    def test_path_validation_error_no_path(self):
        err = PathValidationError("bad")
        assert err.path is None

    def test_browser_init(self):
        err = BrowserInitException()
        assert "initialize" in str(err)

    def test_browser_unavailable(self):
        err = BrowserUnavailableException()
        assert "not available" in str(err)

    def test_playbook_validation(self):
        err = PlaybookValidationError("bad metadata")
        assert "bad metadata" in str(err)

    def test_playbook_validation_default(self):
        err = PlaybookValidationError()
        assert "validation failed" in str(err)


# ---------------------------------------------------------------------------
# Test that exceptions can be raised and caught
# ---------------------------------------------------------------------------

class TestExceptionRaiseAndCatch:
    """Tests that exceptions integrate with Python's try/except properly."""

    def test_catch_forge_error(self):
        with pytest.raises(ForgeError):
            raise AgentStuckInLoopError()

    def test_catch_agent_error(self):
        with pytest.raises(AgentError):
            raise AgentNoInstructionError()

    def test_catch_specific(self):
        with pytest.raises(LLMMalformedActionError):
            raise LLMMalformedActionError("bad")
