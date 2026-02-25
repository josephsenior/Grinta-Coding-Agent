"""Tests for backend.engines.orchestrator.planner."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.engines.orchestrator.planner import (
    ACTION_PATTERNS,
    QUESTION_PATTERNS,
    OrchestratorPlanner,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_config(**kwargs):
    cfg = MagicMock()
    cfg.enable_cmd = True
    cfg.enable_think = True
    cfg.enable_finish = True
    cfg.enable_condensation_request = False
    cfg.enable_browsing = False
    cfg.enable_editor = True
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


def _make_llm(model: str = "gpt-4-turbo") -> MagicMock:
    llm = MagicMock()
    llm.config.model = model
    return llm


def _make_safety() -> MagicMock:
    safety = MagicMock()
    safety.should_enforce_tools.return_value = "required"
    return safety


def _make_planner(**kwargs) -> OrchestratorPlanner:
    config = kwargs.get("config", _make_config())
    llm = kwargs.get("llm", _make_llm())
    safety = kwargs.get("safety", _make_safety())
    return OrchestratorPlanner(config=config, llm=llm, safety_manager=safety)


def _make_state() -> MagicMock:
    state = MagicMock()
    state.to_llm_metadata.return_value = {}
    state.agent_name = "Orchestrator"
    state.plan = None
    state.history = []
    state.extra_data = {}
    # Properly configure turn_signals so float comparisons don't get MagicMock
    ts = MagicMock()
    ts.planning_directive = None
    ts.memory_pressure = None
    ts.repetition_score = 0.0
    state.turn_signals = ts
    # Properly configure iteration_flag
    it = MagicMock()
    it.current_value = 2
    it.max_value = 30
    state.iteration_flag = it
    # Properly configure metrics
    metrics = MagicMock()
    atu = MagicMock()
    atu.prompt_tokens = 0
    atu.completion_tokens = 0
    atu.context_window = 0
    metrics.accumulated_token_usage = atu
    metrics.accumulated_cost = 0.0
    metrics.max_budget_per_task = None
    state.metrics = metrics
    return state


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


class TestPatternConstants:
    def test_question_patterns_not_empty(self):
        assert len(QUESTION_PATTERNS) > 0

    def test_action_patterns_not_empty(self):
        assert len(ACTION_PATTERNS) > 0

    def test_question_patterns_are_strings(self):
        assert all(isinstance(p, str) for p in QUESTION_PATTERNS)

    def test_action_patterns_are_strings(self):
        assert all(isinstance(p, str) for p in ACTION_PATTERNS)


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestOrchestratorPlannerInit:
    def test_initial_cache_is_none(self):
        p = _make_planner()
        assert p._checked_tools_cache is None
        assert p._checked_tools_model is None

    def test_config_and_llm_stored(self):
        cfg = _make_config()
        llm = _make_llm("claude-3-opus")
        p = _make_planner(config=cfg, llm=llm)
        assert p._config is cfg
        assert p._llm is llm


# ---------------------------------------------------------------------------
# _should_use_short_tool_descriptions
# ---------------------------------------------------------------------------


class TestShouldUseShortToolDescriptions:
    def test_gpt4_uses_short(self):
        p = _make_planner(llm=_make_llm("gpt-4-turbo"))
        assert p._should_use_short_tool_descriptions() is True

    def test_o3_uses_short(self):
        p = _make_planner(llm=_make_llm("o3-mini"))
        assert p._should_use_short_tool_descriptions() is True

    def test_o1_uses_short(self):
        p = _make_planner(llm=_make_llm("o1"))
        assert p._should_use_short_tool_descriptions() is True

    def test_o4_uses_short(self):
        p = _make_planner(llm=_make_llm("o4-mini"))
        assert p._should_use_short_tool_descriptions() is True

    def test_claude_does_not_use_short(self):
        p = _make_planner(llm=_make_llm("claude-3-sonnet"))
        assert p._should_use_short_tool_descriptions() is False

    def test_no_llm_returns_false(self):
        p = _make_planner(llm=_make_llm())
        p._llm = None
        assert p._should_use_short_tool_descriptions() is False


# ---------------------------------------------------------------------------
# _llm_supports_tool_choice
# ---------------------------------------------------------------------------


class TestLlmSupportsToolChoice:
    @pytest.mark.parametrize(
        "model",
        [
            "gpt-4o",
            "gpt-4-turbo",
            "claude-opus-4",
            "claude-4-sonnet",
            "o3-mini",
            "o4-mini",
        ],
    )
    def test_supported_models(self, model):
        p = _make_planner(llm=_make_llm(model))
        assert p._llm_supports_tool_choice() is True

    def test_gemini_not_supported_for_tool_choice(self):
        p = _make_planner(llm=_make_llm("google/gemini-3-flash"))
        assert p._llm_supports_tool_choice() is False

    def test_unknown_model_not_supported(self):
        p = _make_planner(llm=_make_llm("some-obscure-model"))
        assert p._llm_supports_tool_choice() is False


# ---------------------------------------------------------------------------
# _get_last_user_message
# ---------------------------------------------------------------------------


class TestGetLastUserMessage:
    def setup_method(self):
        self.p = _make_planner()

    def test_returns_last_user_message(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
            {"role": "user", "content": "last user"},
        ]
        assert self.p._get_last_user_message(messages) == "last user"

    def test_returns_none_when_no_user_messages(self):
        messages = [{"role": "assistant", "content": "only asst"}]
        assert self.p._get_last_user_message(messages) is None

    def test_returns_none_on_empty_list(self):
        assert self.p._get_last_user_message([]) is None

    def test_returns_first_if_only_one_user(self):
        messages = [{"role": "user", "content": "single"}]
        assert self.p._get_last_user_message(messages) == "single"

    def test_non_dict_items_skipped(self):
        messages = ["not-a-dict", {"role": "user", "content": "valid"}]
        assert self.p._get_last_user_message(messages) == "valid"


# ---------------------------------------------------------------------------
# _is_question / _is_action
# ---------------------------------------------------------------------------


class TestIsQuestion:
    def setup_method(self):
        self.p = _make_planner()

    def test_why_is_question(self):
        assert self.p._is_question("why does this happen?") is True

    def test_how_does_is_question(self):
        assert self.p._is_question("how does the caching work?") is True

    def test_what_is_is_question(self):
        assert self.p._is_question("what is the timeout?") is True

    def test_what_are_is_question(self):
        assert self.p._is_question("what are the supported models?") is True

    def test_explain_is_question(self):
        assert self.p._is_question("explain what this does") is True

    def test_tell_me_is_question(self):
        assert self.p._is_question("tell me about it") is True

    def test_trailing_question_mark(self):
        assert self.p._is_question("do you understand?") is True

    def test_action_not_question(self):
        assert self.p._is_question("create a new file") is False

    def test_plain_statement_not_question(self):
        assert self.p._is_question("go ahead with the plan") is False


class TestIsAction:
    def setup_method(self):
        self.p = _make_planner()

    def test_create_is_action(self):
        assert self.p._is_action("create a file") is True

    def test_make_is_action(self):
        assert self.p._is_action("make a script") is True

    def test_fix_is_action(self):
        assert self.p._is_action("fix the bug") is True

    def test_implement_is_action(self):
        assert self.p._is_action("implement the feature") is True

    def test_delete_is_action(self):
        assert self.p._is_action("delete this module") is True

    def test_update_is_action(self):
        assert self.p._is_action("update the config") is True

    def test_install_is_action(self):
        assert self.p._is_action("install dependencies") is True

    def test_build_is_action(self):
        assert self.p._is_action("build the project") is True

    def test_question_not_action(self):
        assert self.p._is_action("how does this work?") is False


# ---------------------------------------------------------------------------
# _determine_tool_choice
# ---------------------------------------------------------------------------


class TestDetermineToolChoice:
    def setup_method(self):
        self.state = _make_state()

    def test_no_user_message_returns_auto(self):
        p = _make_planner()
        messages = [{"role": "system", "content": "sys"}]
        assert p._determine_tool_choice(messages, self.state) == "auto"

    def test_question_returns_auto(self):
        p = _make_planner()
        messages = [{"role": "user", "content": "what is this?"}]
        assert p._determine_tool_choice(messages, self.state) == "auto"

    def test_action_returns_required(self):
        p = _make_planner()
        messages = [{"role": "user", "content": "create a file"}]
        assert p._determine_tool_choice(messages, self.state) == "required"

    def test_plain_chat_returns_none(self):
        p = _make_planner()
        messages = [{"role": "user", "content": "say hello back please"}]
        assert p._determine_tool_choice(messages, self.state) == "none"

    def test_unknown_message_delegates_to_safety(self):
        safety = _make_safety()
        safety.should_enforce_tools.return_value = "none"
        p = _make_planner(safety=safety)
        messages = [{"role": "user", "content": "go ahead"}]
        result = p._determine_tool_choice(messages, self.state)
        assert result == "none"
        safety.should_enforce_tools.assert_called_once()


# ---------------------------------------------------------------------------
# build_toolset (integration-style with mocked internal builders)
# ---------------------------------------------------------------------------


class TestBuildToolset:
    def _mock_tool(self, name: str):
        t = MagicMock()
        t.__repr__ = lambda self: name
        return t

    def test_cache_cleared_on_rebuild(self):
        p = _make_planner()
        p._checked_tools_cache = ["old_cache"]

        with (
            patch(
                "backend.engines.orchestrator.planner.OrchestratorPlanner._add_core_tools"
            ),
            patch(
                "backend.engines.orchestrator.planner.OrchestratorPlanner._add_browsing_tool"
            ),
            patch(
                "backend.engines.orchestrator.planner.OrchestratorPlanner._add_editor_tools"
            ),
        ):
            p.build_toolset()

        assert p._checked_tools_cache is None

    def test_build_toolset_returns_list(self):
        p = _make_planner()
        with (
            patch(
                "backend.engines.orchestrator.planner.OrchestratorPlanner._add_core_tools"
            ),
            patch(
                "backend.engines.orchestrator.planner.OrchestratorPlanner._add_browsing_tool"
            ),
            patch(
                "backend.engines.orchestrator.planner.OrchestratorPlanner._add_editor_tools"
            ),
        ):
            result = p.build_toolset()
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# _add_browsing_tool — Windows skip path
# ---------------------------------------------------------------------------


class TestAddBrowsingTool:
    def test_windows_uses_web_reader_tool(self):
        # NOTE: Browsing implementation moved to MCP in recent versions.
        # This test is kept to verify that no legacy browsing tools are
        # inadvertently added when enable_browsing=True.
        cfg = _make_config(enable_browsing=True)
        p = _make_planner(config=cfg)
        tools = []
        p._add_browsing_tool(tools)
        assert tools == []

    def test_browsing_disabled_adds_nothing(self):
        cfg = _make_config(enable_browsing=False)
        p = _make_planner(config=cfg)
        tools = []
        p._add_browsing_tool(tools)
        assert tools == []


# ---------------------------------------------------------------------------
# build_llm_params — cache logic
# ---------------------------------------------------------------------------


class TestBuildLlmParams:
    def test_check_tools_cache_populated_on_first_call(self):
        p = _make_planner()
        state = _make_state()
        messages = [{"role": "user", "content": "create it"}]
        tools = [MagicMock()]
        checked = [MagicMock(name="checked")]

        with patch(
            "backend.engines.orchestrator.planner.check_tools", return_value=checked
        ) as mock_ct:
            params = p.build_llm_params(messages, state, tools)

        assert p._checked_tools_cache is checked
        assert isinstance(p._checked_tools_model, str)
        assert p._checked_tools_model.startswith(p._llm.config.model + ":")
        assert params["tools"] is checked
        mock_ct.assert_called_once()

    def test_check_tools_cache_reused_on_second_call(self):
        p = _make_planner()
        state = _make_state()
        messages = [{"role": "user", "content": "create it"}]
        tools = [MagicMock()]
        checked = [MagicMock(name="checked")]

        with patch(
            "backend.engines.orchestrator.planner.check_tools", return_value=checked
        ) as mock_ct:
            p.build_llm_params(messages, state, tools)
            p.build_llm_params(messages, state, tools)

        # Should only call check_tools once (cache hit on second call)
        mock_ct.assert_called_once()

    def test_cache_invalidated_when_model_changes(self):
        p = _make_planner()
        state = _make_state()
        messages = [{"role": "user", "content": "go"}]
        tools = [MagicMock()]
        checked = [MagicMock(name="checked")]

        with patch(
            "backend.engines.orchestrator.planner.check_tools", return_value=checked
        ) as mock_ct:
            p.build_llm_params(messages, state, tools)
            # Simulate model change
            p._llm.config.model = "new-model-x"
            p.build_llm_params(messages, state, tools)

        assert mock_ct.call_count == 2

    def test_result_includes_stream_true(self):
        p = _make_planner()
        state = _make_state()
        messages = [{"role": "user", "content": "add function"}]
        tools = []

        with patch("backend.engines.orchestrator.planner.check_tools", return_value=[]):
            params = p.build_llm_params(messages, state, tools)

        assert params["stream"] is True

    def test_result_includes_messages(self):
        p = _make_planner()
        state = _make_state()
        messages = [{"role": "user", "content": "test"}]
        with patch("backend.engines.orchestrator.planner.check_tools", return_value=[]):
            params = p.build_llm_params(messages, state, [])
        assert isinstance(params["messages"], list)
        # Planner injects a dedicated system control message.
        assert params["messages"] != messages
        assert params["messages"][-1]["role"] == "user"
        assert params["messages"][-1]["content"] == "test"

    def test_injects_control_message_before_last_user(self):
        p = _make_planner()
        state = _make_state()
        # Minimal iteration flag required for injection
        it = MagicMock()
        it.current_value = 1
        it.max_value = 3
        state.iteration_flag = it
        # Provide typed turn signals
        ts = MagicMock()
        ts.planning_directive = "[AUTO-PLAN] do planning"
        ts.memory_pressure = "WARNING"
        ts.repetition_score = 0.0
        state.turn_signals = ts
        state.extra_data = {}

        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "task"},
        ]
        with patch("backend.engines.orchestrator.planner.check_tools", return_value=[]):
            params = p.build_llm_params(messages, state, [])

        out = params["messages"]
        assert out[-1]["role"] == "user"
        assert out[-1]["content"] == "task"
        # Control message is inserted immediately before the last user message.
        assert out[-2]["role"] == "system"
        assert "<FORGE_CONTEXT_STATUS" in out[-2]["content"]
        assert "memory_pressure=WARNING" in out[-2]["content"]
        assert "<FORGE_DIRECTIVE>" in out[-2]["content"]

    def test_tool_choice_not_set_for_unsupported_model(self):
        p = _make_planner(llm=_make_llm("some-unknown-model"))
        state = _make_state()
        messages = [{"role": "user", "content": "create a file"}]
        with patch("backend.engines.orchestrator.planner.check_tools", return_value=[]):
            params = p.build_llm_params(messages, state, [])
        assert "tool_choice" not in params

    def test_tool_choice_set_for_supported_model(self):
        p = _make_planner(llm=_make_llm("gpt-4-turbo"))
        state = _make_state()
        messages = [{"role": "user", "content": "create a file"}]
        with patch("backend.engines.orchestrator.planner.check_tools", return_value=[]):
            params = p.build_llm_params(messages, state, [])
        assert "tool_choice" in params
        assert params["tool_choice"] == "required"

    def test_plain_chat_disables_tools_for_turn(self):
        p = _make_planner(llm=_make_llm("google/gemini-3-flash"))
        state = _make_state()
        messages = [{"role": "user", "content": "say hello back please"}]
        tools = [{"type": "function", "function": {"name": "think"}}]

        with patch("backend.engines.orchestrator.planner.check_tools", return_value=[]):
            params = p.build_llm_params(messages, state, tools)

        assert params["tools"] == []


# ---------------------------------------------------------------------------
# Meta-cognition tools
# ---------------------------------------------------------------------------


class TestMetaCognitionTools:
    def test_meta_cognition_tools_added_by_default(self):
        p = _make_planner()
        tools = []
        p._add_core_tools(tools, use_short_tool_desc=True)
        names = [t.get("function", {}).get("name") for t in tools]
        assert "uncertainty" in names
        assert "clarification" in names
        assert "escalate_to_human" in names
        assert "proposal" in names

    def test_meta_cognition_tools_can_be_disabled(self):
        cfg = _make_config(enable_meta_cognition=False)
        p = _make_planner(config=cfg)
        tools = []
        p._add_core_tools(tools, use_short_tool_desc=True)
        names = [t.get("function", {}).get("name") for t in tools]
        assert "uncertainty" not in names
        assert "clarification" not in names
        assert "escalate_to_human" not in names
        assert "proposal" not in names
