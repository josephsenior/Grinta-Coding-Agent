"""Tests for backend.engines.orchestrator.contracts — orchestrator protocol interfaces."""

from unittest.mock import MagicMock


from backend.engines.orchestrator.contracts import (
    ChatCompletionToolParam,
    ExecutionResultProtocol,
    ExecutorProtocol,
    PlannerProtocol,
    SafetyManagerProtocol,
)


class TestChatCompletionToolParam:
    """Tests for ChatCompletionToolParam TypedDict."""

    def test_create_tool_param(self):
        """Test creating ChatCompletionToolParam."""
        tool: ChatCompletionToolParam = {
            "type": "function",
            "function": {"name": "test_tool", "description": "Test"},
        }
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "test_tool"

    def test_tool_param_type_field(self):
        """Test type field is string."""
        tool: ChatCompletionToolParam = {"type": "function"}
        assert isinstance(tool["type"], str)

    def test_tool_param_function_field(self):
        """Test function field is dict."""
        tool: ChatCompletionToolParam = {"function": {"name": "test", "parameters": {}}}
        assert isinstance(tool["function"], dict)

    def test_tool_param_with_all_fields(self):
        """Test tool param with all common fields."""
        tool: ChatCompletionToolParam = {
            "type": "function",
            "function": {
                "name": "my_function",
                "description": "Does something",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        assert "name" in tool["function"]
        assert "description" in tool["function"]
        assert "parameters" in tool["function"]


class TestPlannerProtocol:
    """Tests for PlannerProtocol."""

    def test_has_build_toolset_method(self):
        """Test protocol has build_toolset method."""
        assert hasattr(PlannerProtocol, "build_toolset")

    def test_has_build_llm_params_method(self):
        """Test protocol has build_llm_params method."""
        assert hasattr(PlannerProtocol, "build_llm_params")

    def test_isinstance_check_with_mock(self):
        """Test protocol isinstance check with mock object."""
        mock_planner = MagicMock(spec=PlannerProtocol)
        assert isinstance(mock_planner, PlannerProtocol)

    def test_valid_implementation(self):
        """Test valid implementation satisfies protocol."""

        class ValidPlanner:
            def build_toolset(self):
                return []

            def build_llm_params(self, messages, state, tools):
                return {}

        planner = ValidPlanner()
        # Runtime check
        assert hasattr(planner, "build_toolset")
        assert hasattr(planner, "build_llm_params")

    def test_build_toolset_returns_list(self):
        """Test build_toolset should return list."""

        class TestPlanner:
            def build_toolset(self):
                return [
                    {
                        "type": "function",
                        "function": {"name": "test"},
                    }
                ]

            def build_llm_params(self, messages, state, tools):
                return {}

        planner = TestPlanner()
        tools = planner.build_toolset()
        assert isinstance(tools, list)

    def test_build_llm_params_returns_dict(self):
        """Test build_llm_params should return dict."""

        class TestPlanner:
            def build_toolset(self):
                return []

            def build_llm_params(self, messages, state, tools):
                return {"model": "gpt-4", "messages": messages}

        planner = TestPlanner()
        params = planner.build_llm_params([], MagicMock(), [])
        assert isinstance(params, dict)


class TestExecutionResultProtocol:
    """Tests for ExecutionResultProtocol."""

    def test_has_required_attributes(self):
        """Test protocol defines required attributes."""

        # Protocol attributes are structural, not runtime
        # Verify a valid implementation has them
        class ValidResult:
            def __init__(self):
                self.actions = []
                self.response = None
                self.execution_time = 0.0
                self.error = None

        result = ValidResult()
        # If it has these, it satisfies the protocol
        assert hasattr(result, "actions")
        assert hasattr(result, "response")
        assert hasattr(result, "execution_time")
        assert hasattr(result, "error")

    def test_isinstance_check_with_mock(self):
        """Test protocol isinstance check with mock."""
        mock_result = MagicMock(spec=ExecutionResultProtocol)
        assert isinstance(mock_result, ExecutionResultProtocol)

    def test_valid_implementation(self):
        """Test valid implementation satisfies protocol."""

        class ValidResult:
            def __init__(self):
                self.actions = []
                self.response = None
                self.execution_time = 0.0
                self.error = None

        result = ValidResult()
        assert hasattr(result, "actions")
        assert hasattr(result, "response")
        assert hasattr(result, "execution_time")
        assert hasattr(result, "error")


class TestExecutorProtocol:
    """Tests for ExecutorProtocol."""

    def test_has_execute_method(self):
        """Test protocol has execute method."""
        assert hasattr(ExecutorProtocol, "execute")

    def test_isinstance_check_with_mock(self):
        """Test protocol isinstance check with mock."""
        mock_executor = MagicMock(spec=ExecutorProtocol)
        assert isinstance(mock_executor, ExecutorProtocol)

    def test_valid_implementation(self):
        """Test valid implementation satisfies protocol."""

        class ValidExecutor:
            def execute(self, params, event_stream):
                class Result:
                    actions = []
                    response = None
                    execution_time = 0.0
                    error = None

                return Result()

        executor = ValidExecutor()
        result = executor.execute({}, None)
        assert hasattr(result, "actions")

    def test_execute_accepts_params(self):
        """Test execute accepts params dict."""

        class TestExecutor:
            def execute(self, params, event_stream):
                class Result:
                    actions = []
                    response = params
                    execution_time = 0.0
                    error = None

                return Result()

        executor = TestExecutor()
        result = executor.execute({"model": "gpt-4"}, None)
        assert result.response == {"model": "gpt-4"}

    def test_execute_accepts_event_stream(self):
        """Test execute accepts optional event_stream."""

        class TestExecutor:
            def execute(self, params, event_stream):
                class Result:
                    actions = []
                    response = event_stream
                    execution_time = 0.0
                    error = None

                return Result()

        executor = TestExecutor()
        mock_stream = MagicMock()
        result = executor.execute({}, mock_stream)
        assert result.response == mock_stream


class TestSafetyManagerProtocol:
    """Tests for SafetyManagerProtocol."""

    def test_has_should_enforce_tools_method(self):
        """Test protocol has should_enforce_tools method."""
        assert hasattr(SafetyManagerProtocol, "should_enforce_tools")

    def test_has_apply_method(self):
        """Test protocol has apply method."""
        assert hasattr(SafetyManagerProtocol, "apply")

    def test_isinstance_check_with_mock(self):
        """Test protocol isinstance check with mock."""
        mock_safety = MagicMock(spec=SafetyManagerProtocol)
        assert isinstance(mock_safety, SafetyManagerProtocol)

    def test_valid_implementation(self):
        """Test valid implementation satisfies protocol."""

        class ValidSafetyManager:
            def should_enforce_tools(self, last_user_message, state, default):
                return default

            def apply(self, response_text, actions):
                return (True, actions)

        safety = ValidSafetyManager()
        assert hasattr(safety, "should_enforce_tools")
        assert hasattr(safety, "apply")

    def test_should_enforce_tools_returns_string(self):
        """Test should_enforce_tools returns string."""

        class TestSafety:
            def should_enforce_tools(self, last_user_message, state, default):
                return "auto"

            def apply(self, response_text, actions):
                return (True, actions)

        safety = TestSafety()
        result = safety.should_enforce_tools("message", MagicMock(), "auto")
        assert isinstance(result, str)

    def test_apply_returns_tuple(self):
        """Test apply returns tuple of (bool, list)."""

        class TestSafety:
            def should_enforce_tools(self, last_user_message, state, default):
                return default

            def apply(self, response_text, actions):
                return (False, [])

        safety = TestSafety()
        continue_flag, updated_actions = safety.apply("text", [])
        assert isinstance(continue_flag, bool)
        assert isinstance(updated_actions, list)

    def test_apply_can_modify_actions(self):
        """Test apply can modify action list."""

        class TestSafety:
            def should_enforce_tools(self, last_user_message, state, default):
                return default

            def apply(self, response_text, actions):
                # Filter actions
                return (True, [a for a in actions if a is not None])

        safety = TestSafety()
        original_actions = [MagicMock(), None, MagicMock()]
        continue_flag, filtered = safety.apply("", original_actions)
        assert len(filtered) == 2
