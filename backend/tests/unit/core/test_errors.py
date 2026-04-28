"""Tests for backend.core.errors — canonical error types and classification."""

import pytest

from backend.core.errors import (
    AgentRuntimeError,
    AppError,
    ConfigurationError,
    ContextLimitError,
    EventStreamError,
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
    ToolExecutionError,
    UserActionRequiredError,
    classify_error,
)


class TestAppErrorBaseClass:
    """Tests for AppError base class."""

    def test_app_error_is_runtime_error(self):
        """Test AppError inherits from RuntimeError."""
        assert issubclass(AppError, RuntimeError)

    def test_create_app_error(self):
        """Test creating AppError instance."""
        error = AppError('Test error')
        assert str(error) == 'Test error'

    def test_raise_app_error(self):
        """Test raising AppError."""
        with pytest.raises(AppError, match='Test error'):
            raise AppError('Test error')


class TestRetryableError:
    """Tests for RetryableError."""

    def test_inherits_from_app_error(self):
        """Test RetryableError inherits from AppError."""
        assert issubclass(RetryableError, AppError)

    def test_create_retryable_error(self):
        """Test creating RetryableError instance."""
        error = RetryableError('Operation may succeed if retried')
        assert 'retried' in str(error)

    def test_raise_retryable_error(self):
        """Test raising RetryableError."""
        with pytest.raises(RetryableError):
            raise RetryableError('Temporary failure')


class TestUserActionRequiredError:
    """Tests for UserActionRequiredError."""

    def test_inherits_from_app_error(self):
        """Test UserActionRequiredError inherits from AppError."""
        assert issubclass(UserActionRequiredError, AppError)

    def test_create_user_action_required_error(self):
        """Test creating UserActionRequiredError instance."""
        error = UserActionRequiredError('User must change config')
        assert 'config' in str(error)


class TestInvariantBrokenError:
    """Tests for InvariantBrokenError."""

    def test_inherits_from_app_error(self):
        """Test InvariantBrokenError inherits from AppError."""
        assert issubclass(InvariantBrokenError, AppError)

    def test_create_invariant_broken_error(self):
        """Test creating InvariantBrokenError instance."""
        error = InvariantBrokenError('System invariant violated')
        assert 'invariant' in str(error)


class TestClassifyError:
    """Tests for classify_error function."""

    def test_classify_app_error(self):
        """Test classifying AppError returns its type."""
        error = AppError('test')
        assert classify_error(error) == AppError

    def test_classify_retryable_error(self):
        """Test classifying RetryableError returns its type."""
        error = RetryableError('test')
        assert classify_error(error) == RetryableError

    def test_classify_value_error(self):
        """Test ValueError classified as UserActionRequiredError."""
        error = ValueError('invalid value')
        assert classify_error(error) == UserActionRequiredError

    def test_classify_type_error(self):
        """Test TypeError classified as UserActionRequiredError."""
        error = TypeError('wrong type')
        assert classify_error(error) == UserActionRequiredError

    def test_classify_key_error(self):
        """Test KeyError classified as UserActionRequiredError."""
        error = KeyError('missing key')
        assert classify_error(error) == UserActionRequiredError

    def test_classify_timeout_error(self):
        """Test TimeoutError classified as RetryableError."""
        error = TimeoutError('operation timed out')
        assert classify_error(error) == RetryableError

    def test_classify_connection_error(self):
        """Test ConnectionError classified as RetryableError."""
        error = ConnectionError('connection failed')
        assert classify_error(error) == RetryableError

    def test_classify_os_error(self):
        """Test OSError classified as RetryableError."""
        error = OSError('os error')
        assert classify_error(error) == RetryableError

    def test_classify_assertion_error(self):
        """Test AssertionError classified as InvariantBrokenError."""
        error = AssertionError('assertion failed')
        assert classify_error(error) == InvariantBrokenError

    def test_classify_runtime_error(self):
        """Test RuntimeError classified as InvariantBrokenError."""
        error = RuntimeError('runtime error')
        assert classify_error(error) == InvariantBrokenError

    def test_classify_generic_exception(self):
        """Test generic Exception classified as AppError."""
        error = Exception('generic error')
        assert classify_error(error) == AppError


class TestAgentRuntimeError:
    """Tests for AgentRuntimeError and context handling."""

    def test_inherits_from_app_error(self):
        """Test AgentRuntimeError inherits from AppError."""
        assert issubclass(AgentRuntimeError, AppError)

    def test_create_without_context(self):
        """Test creating AgentRuntimeError without context."""
        error = AgentRuntimeError('Runtime error')
        assert str(error) == 'Runtime error'
        assert error.context == {}

    def test_create_with_context(self):
        """Test creating AgentRuntimeError with context."""
        context = {'session_id': '123', 'iteration': 5}
        error = AgentRuntimeError('Error occurred', context=context)
        assert error.context == context
        assert error.context['session_id'] == '123'

    def test_context_defaults_to_empty_dict(self):
        """Test context defaults to empty dict."""
        error = AgentRuntimeError('Error')
        assert isinstance(error.context, dict)
        assert not error.context

    def test_context_is_mutable(self):
        """Test error context can be modified after creation."""
        error = AgentRuntimeError('Error')
        error.context['key'] = 'value'
        assert error.context['key'] == 'value'


class TestToolExecutionError:
    """Tests for ToolExecutionError."""

    def test_inherits_from_agent_runtime_error(self):
        """Test ToolExecutionError inherits from AgentRuntimeError."""
        assert issubclass(ToolExecutionError, AgentRuntimeError)

    def test_create_with_context(self):
        """Test creating ToolExecutionError with tool context."""
        context = {'tool': 'file_read', 'path': '/missing/file.txt'}
        error = ToolExecutionError('File not found', context=context)
        assert error.context['tool'] == 'file_read'


class TestContextLimitError:
    """Tests for ContextLimitError."""

    def test_inherits_from_agent_runtime_error(self):
        """Test ContextLimitError inherits from AgentRuntimeError."""
        assert issubclass(ContextLimitError, AgentRuntimeError)

    def test_create_context_limit_error(self):
        """Test creating ContextLimitError."""
        error = ContextLimitError('Context window exceeded')
        assert 'exceeded' in str(error)


class TestPlanningError:
    """Tests for PlanningError."""

    def test_inherits_from_agent_runtime_error(self):
        """Test PlanningError inherits from AgentRuntimeError."""
        assert issubclass(PlanningError, AgentRuntimeError)

    def test_create_planning_error(self):
        """Test creating PlanningError."""
        error = PlanningError('Failed to produce valid step')
        assert 'step' in str(error)


class TestModelProviderError:
    """Tests for ModelProviderError."""

    def test_inherits_from_agent_runtime_error(self):
        """Test ModelProviderError inherits from AgentRuntimeError."""
        assert issubclass(ModelProviderError, AgentRuntimeError)

    def test_create_with_provider_context(self):
        """Test creating ModelProviderError with provider details."""
        context = {'provider': 'openai', 'status_code': 429}
        error = ModelProviderError('Rate limited', context=context)
        assert error.context['status_code'] == 429


class TestConfigurationError:
    """Tests for ConfigurationError."""

    def test_inherits_from_agent_runtime_error(self):
        """Test ConfigurationError inherits from AgentRuntimeError."""
        assert issubclass(ConfigurationError, AgentRuntimeError)

    def test_create_configuration_error(self):
        """Test creating ConfigurationError."""
        error = ConfigurationError('Invalid configuration')
        assert 'configuration' in str(error)


class TestSessionError:
    """Tests for SessionError base class."""

    def test_inherits_from_app_error(self):
        """Test SessionError inherits from AppError."""
        assert issubclass(SessionError, AppError)

    def test_create_session_error(self):
        """Test creating SessionError instance."""
        error = SessionError('Session failed')
        assert str(error) == 'Session failed'


class TestSessionStartupError:
    """Tests for SessionStartupError."""

    def test_inherits_from_session_error(self):
        """Test SessionStartupError inherits from SessionError."""
        assert issubclass(SessionStartupError, SessionError)

    def test_create_startup_error(self):
        """Test creating SessionStartupError."""
        error = SessionStartupError('Startup failed')
        assert 'Startup' in str(error)


class TestSessionAlreadyActiveError:
    """Tests for SessionAlreadyActiveError."""

    def test_inherits_from_session_error(self):
        """Test SessionAlreadyActiveError inherits from SessionError."""
        assert issubclass(SessionAlreadyActiveError, SessionError)

    def test_create_already_active_error(self):
        """Test creating SessionAlreadyActiveError."""
        error = SessionAlreadyActiveError('Session already running')
        assert 'already' in str(error)


class TestRuntimeConnectError:
    """Tests for RuntimeConnectError."""

    def test_inherits_from_session_error_and_retryable(self):
        """Test RuntimeConnectError inherits from both SessionError and RetryableError."""
        assert issubclass(RuntimeConnectError, SessionError)
        assert issubclass(RuntimeConnectError, RetryableError)

    def test_create_runtime_connect_error(self):
        """Test creating RuntimeConnectError."""
        error = RuntimeConnectError('Runtime connection failed')
        assert 'Runtime' in str(error)


class TestSessionInvariantError:
    """Tests for SessionInvariantError."""

    def test_inherits_from_session_error(self):
        """Test SessionInvariantError inherits from SessionError."""
        assert issubclass(SessionInvariantError, SessionError)

    def test_create_session_invariant_error(self):
        """Test creating SessionInvariantError."""
        error = SessionInvariantError('Event ordering violated')
        assert str(error) == 'Event ordering violated'


class TestPersistenceError:
    """Tests for PersistenceError."""

    def test_inherits_from_session_error(self):
        """Test PersistenceError inherits from SessionError."""
        assert issubclass(PersistenceError, SessionError)

    def test_create_persistence_error(self):
        """Test creating PersistenceError."""
        error = PersistenceError('Failed to persist events')
        assert 'persist' in str(error)


class TestReplayError:
    """Tests for ReplayError."""

    def test_inherits_from_session_error(self):
        """Test ReplayError inherits from SessionError."""
        assert issubclass(ReplayError, SessionError)

    def test_create_replay_error(self):
        """Test creating ReplayError."""
        error = ReplayError('Trajectory replay failed')
        assert 'replay' in str(error)


class TestEventStreamError:
    """Tests for EventStreamError."""

    def test_inherits_from_app_error(self):
        """Test EventStreamError inherits from AppError."""
        assert issubclass(EventStreamError, AppError)

    def test_create_event_stream_error(self):
        """Test creating EventStreamError."""
        error = EventStreamError('Event stream corrupted')
        assert 'stream' in str(error)


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
            assert issubclass(error_cls, AppError)

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
            assert issubclass(error_cls, AppError)

    def test_all_errors_are_runtime_errors(self):
        """Test all app errors ultimately inherit from RuntimeError."""
        errors = [
            AppError,
            RetryableError,
            UserActionRequiredError,
            InvariantBrokenError,
            AgentRuntimeError,
            SessionError,
            EventStreamError,
        ]
        for error_cls in errors:
            assert issubclass(error_cls, RuntimeError)


from backend.core.errors import (
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

# ---------------------------------------------------------------------------
# Test that all exceptions are subclasses of AppError or AgentError
# ---------------------------------------------------------------------------


class TestExceptionHierarchy:
    """Tests for the exception class hierarchy."""

    def test_agent_error_is_app_error(self):
        assert issubclass(AgentError, AppError)

    def test_agent_subclasses(self):
        for exc_cls in [
            AgentNoInstructionError,
            AgentEventTypeError,
            AgentAlreadyRegisteredError,
            AgentNotRegisteredError,
            AgentStuckInLoopError,
        ]:
            assert issubclass(exc_cls, AgentError)

    def test_llm_errors_are_app_errors(self):
        for exc_cls in [
            LLMMalformedActionError,
            LLMNoActionError,
            LLMResponseError,
            LLMNoResponseError,
            LLMContextWindowExceedError,
        ]:
            assert issubclass(exc_cls, AppError)

    def test_function_call_errors(self):
        for exc_cls in [
            FunctionCallConversionError,
            FunctionCallValidationError,
            FunctionCallNotExistsError,
        ]:
            assert issubclass(exc_cls, AppError)

    def test_playbook_errors(self):
        assert issubclass(PlaybookError, AppError)
        assert issubclass(PlaybookValidationError, PlaybookError)


# ---------------------------------------------------------------------------
# Individual exception creation tests
# ---------------------------------------------------------------------------


class TestExceptionCreation:
    """Tests for creating and inspecting exceptions."""

    def test_agent_no_instruction_default(self):
        err = AgentNoInstructionError()
        assert 'Instruction must be provided' in str(err)

    def test_agent_no_instruction_custom(self):
        err = AgentNoInstructionError('custom msg')
        assert 'custom msg' in str(err)

    def test_agent_event_type_default(self):
        err = AgentEventTypeError()
        assert 'dictionary' in str(err)

    def test_already_registered_with_name(self):
        err = AgentAlreadyRegisteredError('MyAgent')
        assert 'MyAgent' in str(err)

    def test_already_registered_without_name(self):
        err = AgentAlreadyRegisteredError()
        assert 'already registered' in str(err)

    def test_not_registered_with_name(self):
        err = AgentNotRegisteredError('UnknownAgent')
        assert 'UnknownAgent' in str(err)

    def test_not_registered_without_name(self):
        err = AgentNotRegisteredError()
        assert 'No agent' in str(err)

    def test_stuck_in_loop(self):
        err = AgentStuckInLoopError('Repeated 5 times')
        assert 'Repeated 5 times' in str(err)

    def test_task_invalid_state(self):
        err = TaskInvalidStateError('CRASHED')
        assert 'CRASHED' in str(err)

    def test_task_invalid_state_default(self):
        err = TaskInvalidStateError()
        assert 'Invalid state' in str(err)

    def test_malformed_action(self):
        err = LLMMalformedActionError('bad json')
        assert err.message == 'bad json'
        assert str(err) == 'bad json'

    def test_no_action_default(self):
        err = LLMNoActionError()
        assert 'must return' in str(err)

    def test_llm_response_error(self):
        err = LLMResponseError('parse failed')
        assert 'parse failed' in str(err)

    def test_llm_no_response(self):
        err = LLMNoResponseError()
        assert 'Gemini' in str(err)

    def test_user_cancelled(self):
        err = UserCancelledError()
        assert 'cancelled' in str(err)

    def test_operation_cancelled(self):
        err = OperationCancelled()
        assert 'cancelled' in str(err)

    def test_context_window_exceed(self):
        err = LLMContextWindowExceedError()
        assert 'context window' in str(err)

    def test_function_call_errors_with_message(self):
        for cls in [
            FunctionCallConversionError,
            FunctionCallValidationError,
            FunctionCallNotExistsError,
        ]:
            err = cls('test message')
            assert 'test message' in str(err)

    def test_resource_limit_exceeded(self):
        err = ResourceLimitExceededError('Memory limit: 2GB')
        assert 'Memory limit' in str(err)

    def test_path_validation_error(self):
        err = PathValidationError('traversal detected', '/etc/passwd')
        assert err.message == 'traversal detected'
        assert err.path == '/etc/passwd'

    def test_path_validation_error_no_path(self):
        err = PathValidationError('bad')
        assert err.path is None

    def test_browser_init(self):
        err = BrowserInitException()
        assert 'initialize' in str(err)

    def test_browser_unavailable(self):
        err = BrowserUnavailableException()
        assert 'not available' in str(err)

    def test_playbook_validation(self):
        err = PlaybookValidationError('bad metadata')
        assert 'bad metadata' in str(err)

    def test_playbook_validation_default(self):
        err = PlaybookValidationError()
        assert 'validation failed' in str(err)


# ---------------------------------------------------------------------------
# Test that exceptions can be raised and caught
# ---------------------------------------------------------------------------


class TestExceptionRaiseAndCatch:
    """Tests that exceptions integrate with Python's try/except properly."""

    def test_catch_app_error(self):
        with pytest.raises(AppError):
            raise AgentStuckInLoopError()

    def test_catch_agent_error(self):
        with pytest.raises(AgentError):
            raise AgentNoInstructionError()

    def test_catch_specific(self):
        with pytest.raises(LLMMalformedActionError):
            raise LLMMalformedActionError('bad')
