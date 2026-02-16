"""Tests for backend.core.errors — canonical error hierarchy."""

from __future__ import annotations


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
    SocketAuthError,
    ToolExecutionError,
    UserActionRequiredError,
    classify_error,
)


# ===================================================================
# classify_error
# ===================================================================

class TestClassifyError:

    def test_forge_error_returns_own_type(self):
        err = RetryableError("retryable")
        assert classify_error(err) is RetryableError

    def test_value_error_maps_to_user_action(self):
        assert classify_error(ValueError("bad")) is UserActionRequiredError

    def test_type_error_maps_to_user_action(self):
        assert classify_error(TypeError("wrong")) is UserActionRequiredError

    def test_key_error_maps_to_user_action(self):
        assert classify_error(KeyError("missing")) is UserActionRequiredError

    def test_timeout_maps_to_retryable(self):
        assert classify_error(TimeoutError()) is RetryableError

    def test_connection_error_maps_to_retryable(self):
        assert classify_error(ConnectionError()) is RetryableError

    def test_os_error_maps_to_retryable(self):
        assert classify_error(OSError("disk")) is RetryableError

    def test_assertion_error_maps_to_invariant(self):
        assert classify_error(AssertionError("bad")) is InvariantBrokenError

    def test_runtime_error_maps_to_invariant(self):
        assert classify_error(RuntimeError("crash")) is InvariantBrokenError

    def test_unknown_exception_maps_to_forge_error(self):
        assert classify_error(Exception("?")) is ForgeError

    def test_import_error_maps_to_forge_error(self):
        assert classify_error(ImportError("no mod")) is ForgeError

    def test_already_forge_error_subtype(self):
        err = InvariantBrokenError("inv")
        assert classify_error(err) is InvariantBrokenError


# ===================================================================
# Hierarchy
# ===================================================================

class TestErrorHierarchy:

    def test_forge_error_is_runtime_error(self):
        assert issubclass(ForgeError, RuntimeError)

    def test_retryable_is_forge(self):
        assert issubclass(RetryableError, ForgeError)

    def test_user_action_is_forge(self):
        assert issubclass(UserActionRequiredError, ForgeError)

    def test_invariant_is_forge(self):
        assert issubclass(InvariantBrokenError, ForgeError)

    def test_agent_runtime_error_is_forge(self):
        assert issubclass(AgentRuntimeError, ForgeError)

    def test_tool_execution_is_agent_runtime(self):
        assert issubclass(ToolExecutionError, AgentRuntimeError)

    def test_context_limit_is_agent_runtime(self):
        assert issubclass(ContextLimitError, AgentRuntimeError)

    def test_planning_is_agent_runtime(self):
        assert issubclass(PlanningError, AgentRuntimeError)

    def test_model_provider_is_agent_runtime(self):
        assert issubclass(ModelProviderError, AgentRuntimeError)

    def test_configuration_is_agent_runtime(self):
        assert issubclass(ConfigurationError, AgentRuntimeError)

    def test_session_error_is_forge(self):
        assert issubclass(SessionError, ForgeError)

    def test_session_startup_is_session(self):
        assert issubclass(SessionStartupError, SessionError)

    def test_session_already_active_is_session(self):
        assert issubclass(SessionAlreadyActiveError, SessionError)

    def test_runtime_connect_is_session_and_retryable(self):
        assert issubclass(RuntimeConnectError, SessionError)
        assert issubclass(RuntimeConnectError, RetryableError)

    def test_session_invariant_is_session(self):
        assert issubclass(SessionInvariantError, SessionError)

    def test_persistence_is_session(self):
        assert issubclass(PersistenceError, SessionError)

    def test_replay_is_session(self):
        assert issubclass(ReplayError, SessionError)

    def test_socket_auth_is_forge(self):
        assert issubclass(SocketAuthError, ForgeError)

    def test_event_stream_is_forge(self):
        assert issubclass(EventStreamError, ForgeError)


# ===================================================================
# Context in AgentRuntimeError
# ===================================================================

class TestAgentRuntimeErrorContext:

    def test_default_context_empty(self):
        err = AgentRuntimeError("msg")
        assert err.context == {}

    def test_custom_context(self):
        ctx = {"tool": "cmd_run", "code": 1}
        err = AgentRuntimeError("msg", context=ctx)
        assert err.context == ctx
        assert str(err) == "msg"

    def test_subclass_preserves_context(self):
        err = ToolExecutionError("bad tool", context={"file": "/x.py"})
        assert err.context["file"] == "/x.py"
        assert isinstance(err, AgentRuntimeError)
