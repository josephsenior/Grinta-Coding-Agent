"""Tests for backend.core.errors — canonical error types and classification."""

import pytest

from backend.core.errors import (
    AgentRuntimeError,
    ConfigurationError,
    ContextLimitError,
    EventStreamError,
    ForgeError,
    InvariantBrokenError,
    ModelProviderError,
    PersistenceError,
    PlanningError,
    ReplayError,
    RetryableError,
    RuntimeConnectError,
    SessionAlreadyActiveError,
    SessionError,
    SessionInvariantError,
    SessionStartupError,
    SocketConnectionError,
    ToolExecutionError,
    UserActionRequiredError,
    classify_error,
)


class TestForgeErrorBaseClass:
    """Tests for ForgeError base class."""

    def test_forge_error_is_runtime_error(self):
        """Test ForgeError inherits from RuntimeError."""
        assert issubclass(ForgeError, RuntimeError)

    def test_create_forge_error(self):
        """Test creating ForgeError instance."""
        error = ForgeError("Test error")
        assert str(error) == "Test error"

    def test_raise_forge_error(self):
        """Test raising ForgeError."""
        with pytest.raises(ForgeError, match="Test error"):
            raise ForgeError("Test error")


class TestRetryableError:
    """Tests for RetryableError."""

    def test_inherits_from_forge_error(self):
        """Test RetryableError inherits from ForgeError."""
        assert issubclass(RetryableError, ForgeError)

    def test_create_retryable_error(self):
        """Test creating RetryableError instance."""
        error = RetryableError("Operation may succeed if retried")
        assert "retried" in str(error)

    def test_raise_retryable_error(self):
        """Test raising RetryableError."""
        with pytest.raises(RetryableError):
            raise RetryableError("Temporary failure")


class TestUserActionRequiredError:
    """Tests for UserActionRequiredError."""

    def test_inherits_from_forge_error(self):
        """Test UserActionRequiredError inherits from ForgeError."""
        assert issubclass(UserActionRequiredError, ForgeError)

    def test_create_user_action_required_error(self):
        """Test creating UserActionRequiredError instance."""
        error = UserActionRequiredError("User must change config")
        assert "config" in str(error)


class TestInvariantBrokenError:
    """Tests for InvariantBrokenError."""

    def test_inherits_from_forge_error(self):
        """Test InvariantBrokenError inherits from ForgeError."""
        assert issubclass(InvariantBrokenError, ForgeError)

    def test_create_invariant_broken_error(self):
        """Test creating InvariantBrokenError instance."""
        error = InvariantBrokenError("System invariant violated")
        assert "invariant" in str(error)


class TestClassifyError:
    """Tests for classify_error function."""

    def test_classify_forge_error(self):
        """Test classifying ForgeError returns its type."""
        error = ForgeError("test")
        assert classify_error(error) == ForgeError

    def test_classify_retryable_error(self):
        """Test classifying RetryableError returns its type."""
        error = RetryableError("test")
        assert classify_error(error) == RetryableError

    def test_classify_value_error(self):
        """Test ValueError classified as UserActionRequiredError."""
        error = ValueError("invalid value")
        assert classify_error(error) == UserActionRequiredError

    def test_classify_type_error(self):
        """Test TypeError classified as UserActionRequiredError."""
        error = TypeError("wrong type")
        assert classify_error(error) == UserActionRequiredError

    def test_classify_key_error(self):
        """Test KeyError classified as UserActionRequiredError."""
        error = KeyError("missing key")
        assert classify_error(error) == UserActionRequiredError

    def test_classify_timeout_error(self):
        """Test TimeoutError classified as RetryableError."""
        error = TimeoutError("operation timed out")
        assert classify_error(error) == RetryableError

    def test_classify_connection_error(self):
        """Test ConnectionError classified as RetryableError."""
        error = ConnectionError("connection failed")
        assert classify_error(error) == RetryableError

    def test_classify_os_error(self):
        """Test OSError classified as RetryableError."""
        error = OSError("os error")
        assert classify_error(error) == RetryableError

    def test_classify_assertion_error(self):
        """Test AssertionError classified as InvariantBrokenError."""
        error = AssertionError("assertion failed")
        assert classify_error(error) == InvariantBrokenError

    def test_classify_runtime_error(self):
        """Test RuntimeError classified as InvariantBrokenError."""
        error = RuntimeError("runtime error")
        assert classify_error(error) == InvariantBrokenError

    def test_classify_generic_exception(self):
        """Test generic Exception classified as ForgeError."""
        error = Exception("generic error")
        assert classify_error(error) == ForgeError


class TestAgentRuntimeError:
    """Tests for AgentRuntimeError and context handling."""

    def test_inherits_from_forge_error(self):
        """Test AgentRuntimeError inherits from ForgeError."""
        assert issubclass(AgentRuntimeError, ForgeError)

    def test_create_without_context(self):
        """Test creating AgentRuntimeError without context."""
        error = AgentRuntimeError("Runtime error")
        assert str(error) == "Runtime error"
        assert error.context == {}

    def test_create_with_context(self):
        """Test creating AgentRuntimeError with context."""
        context = {"session_id": "123", "iteration": 5}
        error = AgentRuntimeError("Error occurred", context=context)
        assert error.context == context
        assert error.context["session_id"] == "123"

    def test_context_defaults_to_empty_dict(self):
        """Test context defaults to empty dict."""
        error = AgentRuntimeError("Error")
        assert isinstance(error.context, dict)
        assert not error.context

    def test_context_is_mutable(self):
        """Test error context can be modified after creation."""
        error = AgentRuntimeError("Error")
        error.context["key"] = "value"
        assert error.context["key"] == "value"


class TestToolExecutionError:
    """Tests for ToolExecutionError."""

    def test_inherits_from_agent_runtime_error(self):
        """Test ToolExecutionError inherits from AgentRuntimeError."""
        assert issubclass(ToolExecutionError, AgentRuntimeError)

    def test_create_with_context(self):
        """Test creating ToolExecutionError with tool context."""
        context = {"tool": "file_read", "path": "/missing/file.txt"}
        error = ToolExecutionError("File not found", context=context)
        assert error.context["tool"] == "file_read"


class TestContextLimitError:
    """Tests for ContextLimitError."""

    def test_inherits_from_agent_runtime_error(self):
        """Test ContextLimitError inherits from AgentRuntimeError."""
        assert issubclass(ContextLimitError, AgentRuntimeError)

    def test_create_context_limit_error(self):
        """Test creating ContextLimitError."""
        error = ContextLimitError("Context window exceeded")
        assert "exceeded" in str(error)


class TestPlanningError:
    """Tests for PlanningError."""

    def test_inherits_from_agent_runtime_error(self):
        """Test PlanningError inherits from AgentRuntimeError."""
        assert issubclass(PlanningError, AgentRuntimeError)

    def test_create_planning_error(self):
        """Test creating PlanningError."""
        error = PlanningError("Failed to produce valid step")
        assert "step" in str(error)


class TestModelProviderError:
    """Tests for ModelProviderError."""

    def test_inherits_from_agent_runtime_error(self):
        """Test ModelProviderError inherits from AgentRuntimeError."""
        assert issubclass(ModelProviderError, AgentRuntimeError)

    def test_create_with_provider_context(self):
        """Test creating ModelProviderError with provider details."""
        context = {"provider": "openai", "status_code": 429}
        error = ModelProviderError("Rate limited", context=context)
        assert error.context["status_code"] == 429


class TestConfigurationError:
    """Tests for ConfigurationError."""

    def test_inherits_from_agent_runtime_error(self):
        """Test ConfigurationError inherits from AgentRuntimeError."""
        assert issubclass(ConfigurationError, AgentRuntimeError)

    def test_create_configuration_error(self):
        """Test creating ConfigurationError."""
        error = ConfigurationError("Invalid configuration")
        assert "configuration" in str(error)


class TestSessionError:
    """Tests for SessionError base class."""

    def test_inherits_from_forge_error(self):
        """Test SessionError inherits from ForgeError."""
        assert issubclass(SessionError, ForgeError)

    def test_create_session_error(self):
        """Test creating SessionError instance."""
        error = SessionError("Session failed")
        assert str(error) == "Session failed"


class TestSessionStartupError:
    """Tests for SessionStartupError."""

    def test_inherits_from_session_error(self):
        """Test SessionStartupError inherits from SessionError."""
        assert issubclass(SessionStartupError, SessionError)

    def test_create_startup_error(self):
        """Test creating SessionStartupError."""
        error = SessionStartupError("Startup failed")
        assert "Startup" in str(error)


class TestSessionAlreadyActiveError:
    """Tests for SessionAlreadyActiveError."""

    def test_inherits_from_session_error(self):
        """Test SessionAlreadyActiveError inherits from SessionError."""
        assert issubclass(SessionAlreadyActiveError, SessionError)

    def test_create_already_active_error(self):
        """Test creating SessionAlreadyActiveError."""
        error = SessionAlreadyActiveError("Session already running")
        assert "already" in str(error)


class TestRuntimeConnectError:
    """Tests for RuntimeConnectError."""

    def test_inherits_from_session_error_and_retryable(self):
        """Test RuntimeConnectError inherits from both SessionError and RetryableError."""
        assert issubclass(RuntimeConnectError, SessionError)
        assert issubclass(RuntimeConnectError, RetryableError)

    def test_create_runtime_connect_error(self):
        """Test creating RuntimeConnectError."""
        error = RuntimeConnectError("Runtime connection failed")
        assert "Runtime" in str(error)


class TestSessionInvariantError:
    """Tests for SessionInvariantError."""

    def test_inherits_from_session_error(self):
        """Test SessionInvariantError inherits from SessionError."""
        assert issubclass(SessionInvariantError, SessionError)

    def test_create_session_invariant_error(self):
        """Test creating SessionInvariantError."""
        error = SessionInvariantError("Event ordering violated")
        assert str(error) == "Event ordering violated"


class TestPersistenceError:
    """Tests for PersistenceError."""

    def test_inherits_from_session_error(self):
        """Test PersistenceError inherits from SessionError."""
        assert issubclass(PersistenceError, SessionError)

    def test_create_persistence_error(self):
        """Test creating PersistenceError."""
        error = PersistenceError("Failed to persist events")
        assert "persist" in str(error)


class TestReplayError:
    """Tests for ReplayError."""

    def test_inherits_from_session_error(self):
        """Test ReplayError inherits from SessionError."""
        assert issubclass(ReplayError, SessionError)

    def test_create_replay_error(self):
        """Test creating ReplayError."""
        error = ReplayError("Trajectory replay failed")
        assert "replay" in str(error)


class TestSocketConnectionError:
    """Tests for SocketConnectionError."""

    def test_inherits_from_forge_error(self):
        """Test SocketConnectionError inherits from ForgeError."""
        assert issubclass(SocketConnectionError, ForgeError)

    def test_create_socket_connection_error(self):
        """Test creating SocketConnectionError."""
        error = SocketConnectionError("Connection failed")
        assert "Connection" in str(error)


class TestEventStreamError:
    """Tests for EventStreamError."""

    def test_inherits_from_forge_error(self):
        """Test EventStreamError inherits from ForgeError."""
        assert issubclass(EventStreamError, ForgeError)

    def test_create_event_stream_error(self):
        """Test creating EventStreamError."""
        error = EventStreamError("Event stream corrupted")
        assert "stream" in str(error)


class TestErrorHierarchy:
    """Tests for overall error hierarchy."""

    def test_all_agent_runtime_errors_inherit_correctly(self):
        """Test all agent runtime errors inherit from AgentRuntimeError."""
        errors = [
            ToolExecutionError,
            ContextLimitError,
            PlanningError,
            ModelProviderError,
            ConfigurationError,
        ]
        for error_cls in errors:
            assert issubclass(error_cls, AgentRuntimeError)
            assert issubclass(error_cls, ForgeError)

    def test_all_session_errors_inherit_correctly(self):
        """Test all session errors inherit from SessionError."""
        errors = [
            SessionStartupError,
            SessionAlreadyActiveError,
            RuntimeConnectError,
            SessionInvariantError,
            PersistenceError,
            ReplayError,
        ]
        for error_cls in errors:
            assert issubclass(error_cls, SessionError)
            assert issubclass(error_cls, ForgeError)

    def test_all_errors_are_runtime_errors(self):
        """Test all Forge errors ultimately inherit from RuntimeError."""
        errors = [
            ForgeError,
            RetryableError,
            UserActionRequiredError,
            InvariantBrokenError,
            AgentRuntimeError,
            SessionError,
            SocketConnectionError,
            EventStreamError,
        ]
        for error_cls in errors:
            assert issubclass(error_cls, RuntimeError)
