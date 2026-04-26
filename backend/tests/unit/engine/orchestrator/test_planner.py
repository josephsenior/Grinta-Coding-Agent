"""Tests for backend.engine.planner."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from backend.engine.planner import (
    OrchestratorPlanner,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_config(**kwargs):
    cfg = MagicMock()
    cfg.enable_think = True
    cfg.enable_finish = True
    cfg.enable_condensation_request = False
    cfg.enable_browsing = False
    cfg.enable_native_browser = False
    cfg.enable_editor = True
    cfg.enable_first_turn_orientation_prompt = False
    cfg.merge_control_system_into_primary = False
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
    pass


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

    def test_action_returns_auto(self):
        """Actions now return 'auto' — LLM decides tool usage."""
        p = _make_planner()
        messages = [{"role": "user", "content": "create a file"}]
        assert p._determine_tool_choice(messages, self.state) == "auto"

    def test_plain_chat_returns_auto(self):
        p = _make_planner()
        messages = [{"role": "user", "content": "say hello back please"}]
        assert p._determine_tool_choice(messages, self.state) == "auto"

    def test_generic_message_returns_auto(self):
        """Messages that aren't plain chat default to 'auto'."""
        p = _make_planner()
        messages = [{"role": "user", "content": "go ahead"}]
        assert p._determine_tool_choice(messages, self.state) == "auto"


# ---------------------------------------------------------------------------
# build_toolset (integration-style with mocked internal builders)
# ---------------------------------------------------------------------------


class TestBuildToolset:
    def _mock_tool(self, name: str):
        t = MagicMock()
        cast(Any, t).__repr__ = lambda: name
        return t

    def test_cache_cleared_on_rebuild(self):
        p = _make_planner()
        cast(Any, p)._checked_tools_cache = ["old_cache"]

        with (
            patch("backend.engine.planner.OrchestratorPlanner._add_core_tools"),
            patch("backend.engine.planner.OrchestratorPlanner._add_browsing_tool"),
            patch("backend.engine.planner.OrchestratorPlanner._add_editor_tools"),
        ):
            p.build_toolset()

        assert p._checked_tools_cache is None

    def test_build_toolset_returns_list(self):
        p = _make_planner()
        with (
            patch("backend.engine.planner.OrchestratorPlanner._add_core_tools"),
            patch("backend.engine.planner.OrchestratorPlanner._add_browsing_tool"),
            patch("backend.engine.planner.OrchestratorPlanner._add_editor_tools"),
        ):
            result = p.build_toolset()
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# _add_browsing_tool — Windows skip path
# ---------------------------------------------------------------------------


class TestAddBrowsingTool:
    def test_windows_uses_web_reader_tool(self):
        # NOTE: Browsing implementation moved to MCP in recent versions.
        cfg = _make_config(enable_browsing=True)
        p = _make_planner(config=cfg)
        tools: list[Any] = []
        p._add_browsing_tool(tools)
        assert len(tools) == 0

    def test_browsing_disabled_adds_nothing(self):
        cfg = _make_config(enable_browsing=False)
        p = _make_planner(config=cfg)
        tools: list[Any] = []
        p._add_browsing_tool(tools)
        assert len(tools) == 0

    def test_native_browser_adds_browser_tool(self):
        cfg = _make_config(enable_browsing=True, enable_native_browser=True)
        p = _make_planner(config=cfg)
        tools: list[Any] = []
        p._add_browsing_tool(tools)
        names = [t.get("function", {}).get("name") for t in tools]
        assert "browser" in names


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
            "backend.engine.planner.check_tools", return_value=checked
        ) as mock_ct:
            params = p.build_llm_params(messages, state, tools)

        assert p._checked_tools_cache is checked
        assert isinstance(p._checked_tools_model, str)
        model = (p._llm.config.model or "").strip()
        assert p._checked_tools_model.startswith(f"{model}:")
        assert params["tools"] is checked
        mock_ct.assert_called_once()

    def test_check_tools_cache_reused_on_second_call(self):
        p = _make_planner()
        state = _make_state()
        messages = [{"role": "user", "content": "create it"}]
        tools = [MagicMock()]
        checked = [MagicMock(name="checked")]

        with patch(
            "backend.engine.planner.check_tools", return_value=checked
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
            "backend.engine.planner.check_tools", return_value=checked
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
        tools: list[Any] = []

        with patch("backend.engine.planner.check_tools", return_value=[]):
            params = p.build_llm_params(messages, state, tools)

        assert params["stream"] is True

    def test_result_includes_messages(self):
        p = _make_planner()
        state = _make_state()
        messages = [{"role": "user", "content": "test"}]
        with patch("backend.engine.planner.check_tools", return_value=[]):
            params = p.build_llm_params(messages, state, [])
        assert isinstance(params["messages"], list)
        # No planning_directive set → messages pass through unchanged.
        assert params["messages"] == messages
        assert params["messages"][-1]["role"] == "user"
        assert params["messages"][-1]["content"] == "test"

    def test_injects_control_message_before_last_user(self):
        p = _make_planner()
        state = _make_state()
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
        with patch("backend.engine.planner.check_tools", return_value=[]):
            params = p.build_llm_params(messages, state, [])

        out = params["messages"]
        assert out[-1]["role"] == "user"
        assert out[-1]["content"] == "task"
        # Control message is inserted immediately before the last user message.
        assert out[-2]["role"] == "system"
        assert "<APP_DIRECTIVE>" in out[-2]["content"]
        assert "[AUTO-PLAN] do planning" in out[-2]["content"]
        assert "<APP_CONTEXT_STATUS" not in out[-2]["content"]

    def test_merges_control_into_primary_system_when_configured(self):
        p = _make_planner(config=_make_config(merge_control_system_into_primary=True))
        state = _make_state()
        ts = MagicMock()
        ts.planning_directive = "[AUTO-PLAN] do planning"
        ts.memory_pressure = "WARNING"
        ts.repetition_score = 0.0
        state.turn_signals = ts

        messages = [
            {"role": "system", "content": "base sys"},
            {"role": "user", "content": "task"},
        ]
        with patch("backend.engine.planner.check_tools", return_value=[]):
            params = p.build_llm_params(messages, state, [])

        out = params["messages"]
        assert len(out) == 2
        assert out[0]["role"] == "system"
        assert out[0]["content"].startswith("base sys")
        assert "<APP_DIRECTIVE>" in out[0]["content"]
        assert "[AUTO-PLAN] do planning" in out[0]["content"]
        assert "<APP_CONTEXT_STATUS" not in out[0]["content"]
        assert out[-1]["role"] == "user"
        assert out[-1]["content"] == "task"

    def test_tool_choice_not_set_for_unsupported_model(self):
        p = _make_planner(llm=_make_llm("some-unknown-model"))
        state = _make_state()
        messages = [{"role": "user", "content": "create a file"}]
        with patch("backend.engine.planner.check_tools", return_value=[]):
            params = p.build_llm_params(messages, state, [])
        assert "tool_choice" not in params

    def test_tool_choice_set_for_supported_model(self):
        p = _make_planner(llm=_make_llm("gpt-4-turbo"))
        state = _make_state()
        messages = [{"role": "user", "content": "create a file"}]
        with patch("backend.engine.planner.check_tools", return_value=[]):
            params = p.build_llm_params(messages, state, [])
        assert "tool_choice" in params
        assert params["tool_choice"] == "auto"

    def test_plain_chat_disables_tools_for_turn(self):
        p = _make_planner(llm=_make_llm("google/gemini-3-flash"))
        state = _make_state()
        messages = [{"role": "user", "content": "say hello back please"}]
        tools = [{"type": "function", "function": {"name": "think"}}]

        with patch("backend.engine.planner.check_tools", return_value=[]):
            params = p.build_llm_params(messages, state, tools)

        assert params["tools"] == []

    def test_first_turn_orientation_disabled_by_default(self):
        p = _make_planner()
        state = _make_state()
        state.iteration_flag.current_value = 1
        messages = [{"role": "user", "content": "Please fix the failing backend test"}]

        with patch("backend.engine.planner.check_tools", return_value=[]):
            params = p.build_llm_params(messages, state, [])

        joined = "\n".join(
            m["content"] for m in params["messages"] if isinstance(m.get("content"), str)
        )
        assert "<FIRST_TURN_ORIENTATION>" not in joined

    def test_first_turn_orientation_is_not_injected_even_when_opted_in(self):
        p = _make_planner(
            config=_make_config(enable_first_turn_orientation_prompt=True)
        )
        state = _make_state()
        state.iteration_flag.current_value = 1
        messages = [{"role": "user", "content": "Please fix the failing backend test"}]

        with patch("backend.engine.planner.check_tools", return_value=[]):
            params = p.build_llm_params(messages, state, [])

        joined = "\n".join(
            m["content"] for m in params["messages"] if isinstance(m.get("content"), str)
        )
        assert "<FIRST_TURN_ORIENTATION>" not in joined

    def test_first_turn_orientation_never_appears_across_retries(self):
        p = _make_planner(
            config=_make_config(enable_first_turn_orientation_prompt=True)
        )
        state = _make_state()
        state.iteration_flag.current_value = 1
        messages = [{"role": "user", "content": "Please fix one failing test"}]

        with patch("backend.engine.planner.check_tools", return_value=[]):
            first = p.build_llm_params(messages, state, [])
            second = p.build_llm_params(messages, state, [])

        for params in (first, second):
            joined = "\n".join(
                m["content"] for m in params["messages"] if isinstance(m.get("content"), str)
            )
            assert "<FIRST_TURN_ORIENTATION>" not in joined


class TestMinimalTurnStatusDefault:
    """Verify that nothing is injected unless a guard sets planning_directive."""

    def _state_with_directive(self, directive: str | None):
        state = _make_state()
        it = MagicMock()
        it.current_value = 1
        it.max_value = 3
        state.iteration_flag = it
        ts = MagicMock()
        ts.planning_directive = directive
        ts.memory_pressure = "WARNING"
        ts.repetition_score = 0.8
        state.turn_signals = ts
        state.extra_data = {}
        return state

    def test_no_injection_when_directive_absent(self):
        p = _make_planner()
        state = self._state_with_directive(None)

        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "task"},
        ]
        with patch("backend.engine.planner.check_tools", return_value=[]):
            params = p.build_llm_params(messages, state, [])

        out = params["messages"]
        # No control system message inserted; no APP_CONTEXT_STATUS, no
        # repetition warning, no active plan, no directive.
        assert len(out) == 2
        joined = "\n".join(
            m["content"] for m in out if isinstance(m.get("content"), str)
        )
        assert "<APP_CONTEXT_STATUS" not in joined
        assert "<APP_DIRECTIVE>" not in joined
        assert "<ACTIVE_PLAN>" not in joined
        assert "REPETITION WARNING" not in joined
        assert "CONTEXT PRESSURE" not in joined

    def test_only_directive_injected_when_present(self):
        p = _make_planner()
        state = self._state_with_directive("[GUARD] take next concrete step")

        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "task"},
        ]
        with patch("backend.engine.planner.check_tools", return_value=[]):
            params = p.build_llm_params(messages, state, [])

        out = params["messages"]
        assert out[-1] == {"role": "user", "content": "task"}
        assert out[-2]["role"] == "system"
        content = out[-2]["content"]
        assert content.startswith("<APP_DIRECTIVE>")
        assert "[GUARD] take next concrete step" in content
        assert "<APP_CONTEXT_STATUS" not in content
        assert "<ACTIVE_PLAN>" not in content
        assert "REPETITION WARNING" not in content
        assert "CONTEXT PRESSURE" not in content


# ---------------------------------------------------------------------------
# Meta-cognition tools
# ---------------------------------------------------------------------------
