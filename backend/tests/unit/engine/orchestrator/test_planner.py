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
    cfg.enable_condensation_request = False
    cfg.enable_browsing = False
    cfg.enable_editor = True
    cfg.enable_debugger = True
    cfg.enable_first_turn_orientation_prompt = False
    cfg.merge_control_system_into_primary = False
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


def _make_llm(model: str = 'openai/gpt-4-turbo') -> MagicMock:
    llm = MagicMock()
    llm.config.model = model
    return llm


def _make_safety() -> MagicMock:
    safety = MagicMock()
    safety.should_enforce_tools.return_value = 'required'
    return safety


def _make_planner(**kwargs) -> OrchestratorPlanner:
    config = kwargs.get('config', _make_config())
    llm = kwargs.get('llm', _make_llm())
    safety = kwargs.get('safety', _make_safety())
    return OrchestratorPlanner(config=config, llm=llm, safety_manager=safety)


def _make_state() -> MagicMock:
    state = MagicMock()
    state.to_llm_metadata.return_value = {}
    state.agent_name = 'Orchestrator'
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
        llm = _make_llm('claude-3-opus')
        p = _make_planner(config=cfg, llm=llm)
        assert p._config is cfg
        assert p._llm is llm


# ---------------------------------------------------------------------------
# _llm_supports_tool_choice
# ---------------------------------------------------------------------------


class TestLlmSupportsToolChoice:
    @pytest.mark.parametrize(
        'model',
        [
            'openai/gpt-4o',
            'openai/gpt-4-turbo',
            'anthropic/claude-opus-4-7',
            'anthropic/claude-sonnet-4-6',
            'openai/gpt-5.2',
            'openai/gpt-4.1-mini',
        ],
    )
    def test_supported_models(self, model):
        p = _make_planner(llm=_make_llm(model))
        assert p._llm_supports_tool_choice() is True

    def test_gemini_not_supported_for_tool_choice(self):
        p = _make_planner(llm=_make_llm('google/gemini-3-flash'))
        assert p._llm_supports_tool_choice() is False

    def test_unknown_model_not_supported(self):
        p = _make_planner(llm=_make_llm('some-obscure-model'))
        assert p._llm_supports_tool_choice() is False


# ---------------------------------------------------------------------------
# _get_last_user_message
# ---------------------------------------------------------------------------


class TestGetLastUserMessage:
    def setup_method(self):
        self.p = _make_planner()

    def test_returns_last_user_message(self):
        messages = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': 'hello'},
            {'role': 'assistant', 'content': 'world'},
            {'role': 'user', 'content': 'last user'},
        ]
        assert self.p._get_last_user_message(messages) == 'last user'

    def test_returns_none_when_no_user_messages(self):
        messages = [{'role': 'assistant', 'content': 'only asst'}]
        assert self.p._get_last_user_message(messages) is None

    def test_returns_none_on_empty_list(self):
        assert self.p._get_last_user_message([]) is None

    def test_returns_first_if_only_one_user(self):
        messages = [{'role': 'user', 'content': 'single'}]
        assert self.p._get_last_user_message(messages) == 'single'

    def test_non_dict_items_skipped(self):
        messages = ['not-a-dict', {'role': 'user', 'content': 'valid'}]
        assert self.p._get_last_user_message(messages) == 'valid'


# ---------------------------------------------------------------------------
# _determine_tool_choice
# ---------------------------------------------------------------------------


class TestDetermineToolChoice:
    def setup_method(self):
        self.state = _make_state()

    def test_no_user_message_returns_auto(self):
        p = _make_planner()
        messages = [{'role': 'system', 'content': 'sys'}]
        assert p._determine_tool_choice(messages, self.state) == 'auto'

    def test_question_returns_auto(self):
        p = _make_planner()
        messages = [{'role': 'user', 'content': 'what is this?'}]
        assert p._determine_tool_choice(messages, self.state) == 'auto'

    def test_action_returns_auto(self):
        """Actions now return 'auto' — LLM decides tool usage."""
        p = _make_planner()
        messages = [{'role': 'user', 'content': 'create a file'}]
        assert p._determine_tool_choice(messages, self.state) == 'auto'

    def test_plain_chat_returns_auto(self):
        p = _make_planner()
        messages = [{'role': 'user', 'content': 'say hello back please'}]
        assert p._determine_tool_choice(messages, self.state) == 'auto'

    def test_generic_message_returns_auto(self):
        """Messages that aren't plain chat default to 'auto'."""
        p = _make_planner()
        messages = [{'role': 'user', 'content': 'go ahead'}]
        assert p._determine_tool_choice(messages, self.state) == 'auto'


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
        cast(Any, p)._checked_tools_cache = ['old_cache']

        with (
            patch('backend.engine.planner.OrchestratorPlanner._add_core_tools'),
            patch('backend.engine.planner.OrchestratorPlanner._add_browsing_tool'),
            patch('backend.engine.planner.OrchestratorPlanner._add_editor_tools'),
        ):
            p.build_toolset()

        assert p._checked_tools_cache is None

    def test_build_toolset_returns_list(self):
        p = _make_planner()
        with (
            patch('backend.engine.planner.OrchestratorPlanner._add_core_tools'),
            patch('backend.engine.planner.OrchestratorPlanner._add_browsing_tool'),
            patch('backend.engine.planner.OrchestratorPlanner._add_editor_tools'),
        ):
            result = p.build_toolset()
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# _add_browsing_tool — Windows skip path
# ---------------------------------------------------------------------------


class TestAddBrowsingTool:
    def test_browsing_enabled_adds_browser_tool(self, monkeypatch):
        from backend.utils import optional_extras as oe

        monkeypatch.setattr(oe, 'browser_tool_enabled', lambda _cfg: True)
        cfg = _make_config(enable_browsing=True)
        p = _make_planner(config=cfg)
        tools: list[Any] = []
        p._add_browsing_tool(tools)
        assert len(tools) == 1
        assert tools[0]['function']['name'] == 'browser'

    def test_browsing_disabled_adds_nothing(self, monkeypatch):
        from backend.utils import optional_extras as oe

        monkeypatch.setattr(oe, 'browser_tool_enabled', lambda _cfg: False)
        cfg = _make_config(enable_browsing=False)
        p = _make_planner(config=cfg)
        tools: list[Any] = []
        p._add_browsing_tool(tools)
        assert len(tools) == 0


class TestAddWebTools:
    def test_adds_web_search_and_web_fetch(self):
        p = _make_planner()
        tools: list[Any] = []
        p._add_web_tools(tools)
        names = {t['function']['name'] for t in tools}
        assert names == {'web_search', 'web_fetch'}

    def test_web_disabled_adds_nothing(self):
        p = _make_planner(config=_make_config(enable_web=False))
        tools: list[Any] = []
        p._add_web_tools(tools)
        assert tools == []


class TestAddDocsTools:
    def test_adds_docs_resolve_and_docs_query(self):
        p = _make_planner()
        tools: list[Any] = []
        p._add_docs_tools(tools)
        names = {t['function']['name'] for t in tools}
        assert names == {'docs_resolve', 'docs_query'}

    def test_docs_disabled_adds_nothing(self):
        p = _make_planner(config=_make_config(enable_docs=False))
        tools: list[Any] = []
        p._add_docs_tools(tools)
        assert tools == []


# ---------------------------------------------------------------------------
# build_llm_params — cache logic
# ---------------------------------------------------------------------------


class TestBuildLlmParams:
    def test_check_tools_cache_populated_on_first_call(self):
        p = _make_planner()
        state = _make_state()
        messages = [{'role': 'user', 'content': 'create it'}]
        tools = [
            {'type': 'function', 'function': {'name': 'test', 'description': 'desc'}}
        ]
        checked = [MagicMock(name='checked')]

        with patch(
            'backend.engine.planner.check_tools', return_value=checked
        ) as mock_ct:
            params = p.build_llm_params(messages, state, tools)

        assert p._checked_tools_cache is checked
        assert isinstance(p._checked_tools_model, str)
        model = (p._llm.config.model or '').strip()
        assert p._checked_tools_model.startswith(f'{model}:')
        assert params['tools'] is checked
        mock_ct.assert_called_once()

    def test_check_tools_cache_reused_on_second_call(self):
        p = _make_planner()
        state = _make_state()
        messages = [{'role': 'user', 'content': 'create it'}]
        tools = [
            {'type': 'function', 'function': {'name': 'test', 'description': 'desc'}}
        ]
        checked = [MagicMock(name='checked')]

        with patch(
            'backend.engine.planner.check_tools', return_value=checked
        ) as mock_ct:
            p.build_llm_params(messages, state, tools)
            p.build_llm_params(messages, state, tools)

        # Should only call check_tools once (cache hit on second call)
        mock_ct.assert_called_once()

    def test_cache_invalidated_when_model_changes(self):
        p = _make_planner()
        state = _make_state()
        messages = [{'role': 'user', 'content': 'go'}]
        tools = [
            {'type': 'function', 'function': {'name': 'test', 'description': 'desc'}}
        ]
        checked = [MagicMock(name='checked')]

        with patch(
            'backend.engine.planner.check_tools', return_value=checked
        ) as mock_ct:
            p.build_llm_params(messages, state, tools)
            # Simulate model change
            p._llm.config.model = 'openai/gpt-4o'
            p.build_llm_params(messages, state, tools)

        assert mock_ct.call_count == 2

    def test_result_includes_stream_true(self):
        p = _make_planner()
        state = _make_state()
        messages = [{'role': 'user', 'content': 'add function'}]
        tools: list[Any] = []

        with patch('backend.engine.planner.check_tools', return_value=[]):
            params = p.build_llm_params(messages, state, tools)

        assert params['stream'] is True

    def test_result_includes_messages(self):
        p = _make_planner()
        state = _make_state()
        messages = [{'role': 'user', 'content': 'test'}]
        with patch('backend.engine.planner.check_tools', return_value=[]):
            params = p.build_llm_params(messages, state, [])
        assert isinstance(params['messages'], list)
        assert params['messages'][-1]['role'] == 'user'
        assert params['messages'][-1]['content'] == 'test'
        joined = '\n'.join(
            m['content']
            for m in params['messages']
            if isinstance(m.get('content'), str)
        )
        assert 'Current mode: AGENT' in joined
        assert joined.count('Current mode:') == 1
        assert 'File API mental model' not in joined
        assert 'read_file' not in joined
        assert 'read_range' not in joined
        assert 'read_symbol' not in joined
        assert 'create_file' not in joined
        assert 'replace_symbol' not in joined
        assert 'insert_symbol' not in joined
        assert 'append_text' not in joined
        assert 'section_edit' not in joined
        assert 'raw editor' not in joined
        assert 'XML file-edit' not in joined

    def test_coding_preflight_injected_for_first_coding_turn(self, tmp_path):
        p = _make_planner()
        state = _make_state()
        source = tmp_path / 'backend' / 'auth.py'
        source.parent.mkdir()
        source.write_text('def refresh_token():\n    return "ok"\n', encoding='utf-8')
        messages = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': 'implement retry function in auth.py'},
        ]

        with (
            patch('backend.engine.planner.check_tools', return_value=[]),
            patch(
                'backend.context.coding_preflight.resolve_cli_workspace_directory',
                return_value=tmp_path,
            ),
        ):
            params = p.build_llm_params(messages, state, [])

        joined = '\n'.join(
            m['content']
            for m in params['messages']
            if isinstance(m.get('content'), str)
        )
        assert '<CODING_PREFLIGHT>' in joined
        assert 'backend/auth.py' in joined
        assert 'Ranked candidates' in joined
        assert 'Treat candidates as hints' in joined
        assert 'Prefer grep/glob/find_symbols' not in joined

    def test_coding_preflight_can_be_disabled(self, tmp_path):
        p = _make_planner(config=_make_config(enable_coding_preflight=False))
        state = _make_state()
        messages = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': 'implement retry function in auth.py'},
        ]

        with (
            patch('backend.engine.planner.check_tools', return_value=[]),
            patch(
                'backend.context.coding_preflight.resolve_cli_workspace_directory',
                return_value=tmp_path,
            ),
        ):
            params = p.build_llm_params(messages, state, [])

        joined = '\n'.join(
            m['content']
            for m in params['messages']
            if isinstance(m.get('content'), str)
        )
        assert '<CODING_PREFLIGHT>' not in joined

    def test_prompt_accounting_splits_static_tools_context_and_dynamic_history(self):
        p = _make_planner()
        p._llm.config.custom_tokenizer = None
        p._llm.config.max_input_tokens = 120_000
        p._llm.config.max_output_tokens = 4_000
        p._llm.config.context_window_tokens = 124_000
        params = {
            'messages': [
                {'role': 'system', 'content': 'system prompt'},
                {
                    'role': 'user',
                    'content': '<RUNTIME_INFORMATION>repo</RUNTIME_INFORMATION>',
                },
                {'role': 'user', 'content': '<CONTEXT_PACKET>state</CONTEXT_PACKET>'},
                {'role': 'user', 'content': 'latest user task'},
            ],
            'tools': [
                {
                    'type': 'function',
                    'function': {
                        'name': 'read',
                        'description': 'Read files',
                        'parameters': {'type': 'object'},
                    },
                }
            ],
        }

        accounting = p._build_prompt_accounting(params)

        assert accounting['static_prompt_tokens'] > 0
        assert accounting['tool_schema_tokens'] > 0
        assert accounting['context_packet_tokens'] > 0
        assert accounting['dynamic_history_tokens'] > 0
        assert 100_000 < accounting['usable_input_tokens'] <= 120_000
        assert accounting['full_request_tokens'] > accounting['dynamic_history_tokens']

    def test_injects_control_message_before_last_user(self):
        p = _make_planner()
        state = _make_state()
        ts = MagicMock()
        ts.planning_directive = '[AUTO-PLAN] do planning'
        ts.memory_pressure = 'WARNING'
        ts.repetition_score = 0.0
        state.turn_signals = ts
        state.extra_data = {}

        messages = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': 'task'},
        ]
        with patch('backend.engine.planner.check_tools', return_value=[]):
            params = p.build_llm_params(messages, state, [])

        out = params['messages']
        assert out[-1]['role'] == 'user'
        assert out[-1]['content'] == 'task'
        joined = '\n'.join(
            m['content'] for m in out if isinstance(m.get('content'), str)
        )
        assert '<APP_DIRECTIVE>' in joined
        assert '[AUTO-PLAN] do planning' in joined
        assert '<APP_CONTEXT_STATUS' not in joined

    def test_merges_control_into_primary_system_when_configured(self):
        p = _make_planner(config=_make_config(merge_control_system_into_primary=True))
        state = _make_state()
        ts = MagicMock()
        ts.planning_directive = '[AUTO-PLAN] do planning'
        ts.memory_pressure = 'WARNING'
        ts.repetition_score = 0.0
        state.turn_signals = ts

        messages = [
            {'role': 'system', 'content': 'base sys'},
            {'role': 'user', 'content': 'task'},
        ]
        with patch('backend.engine.planner.check_tools', return_value=[]):
            params = p.build_llm_params(messages, state, [])

        out = params['messages']
        assert len(out) == 2
        assert out[0]['role'] == 'system'
        assert out[0]['content'].startswith('base sys')
        assert '<APP_DIRECTIVE>' in out[0]['content']
        assert '[AUTO-PLAN] do planning' in out[0]['content']
        assert '<APP_CONTEXT_STATUS' not in out[0]['content']
        assert out[-1]['role'] == 'user'
        assert out[-1]['content'] == 'task'

    def test_tool_choice_not_set_for_unsupported_model(self):
        p = _make_planner(llm=_make_llm('some-unknown-model'))
        state = _make_state()
        messages = [{'role': 'user', 'content': 'create a file'}]
        with patch('backend.engine.planner.check_tools', return_value=[]):
            params = p.build_llm_params(messages, state, [])
        assert 'tool_choice' not in params

    def test_tool_choice_set_for_supported_model(self):
        p = _make_planner(llm=_make_llm('openai/gpt-4-turbo'))
        state = _make_state()
        messages = [{'role': 'user', 'content': 'create a file'}]
        with patch('backend.engine.planner.check_tools', return_value=[]):
            params = p.build_llm_params(messages, state, [])
        assert 'tool_choice' in params
        assert params['tool_choice'] == 'auto'

    def test_plain_chat_disables_tools_for_turn(self):
        p = _make_planner(llm=_make_llm('google/gemini-3-flash'))
        state = _make_state()
        messages = [{'role': 'user', 'content': 'say hello back please'}]
        tools = [{'type': 'function', 'function': {'name': 'think'}}]

        with patch('backend.engine.planner.check_tools', return_value=[]):
            params = p.build_llm_params(messages, state, tools)

        assert params['tools'] == []

    def test_native_tools_included_for_opencode_go_minimax(self):
        p = _make_planner(llm=_make_llm('opencode-go/minimax-m2.7'))
        state = _make_state()
        messages = [{'role': 'user', 'content': 'create a file'}]
        tools = [{'type': 'function', 'function': {'name': 'think'}}]
        checked = [{'type': 'function', 'function': {'name': 'think'}}]

        with patch(
            'backend.engine.planner.check_tools', return_value=checked
        ) as mock_ct:
            params = p.build_llm_params(messages, state, tools)

        assert params['tools'] is checked
        assert params['tool_choice'] == 'auto'
        mock_ct.assert_called_once()

    def test_first_turn_orientation_disabled_by_default(self):
        p = _make_planner()
        state = _make_state()
        state.iteration_flag.current_value = 1
        messages = [{'role': 'user', 'content': 'Please fix the failing backend test'}]

        with patch('backend.engine.planner.check_tools', return_value=[]):
            params = p.build_llm_params(messages, state, [])

        joined = '\n'.join(
            m['content']
            for m in params['messages']
            if isinstance(m.get('content'), str)
        )
        assert '<FIRST_TURN_ORIENTATION>' not in joined

    def test_first_turn_orientation_is_not_injected_even_when_opted_in(self):
        p = _make_planner(
            config=_make_config(enable_first_turn_orientation_prompt=True)
        )
        state = _make_state()
        state.iteration_flag.current_value = 1
        messages = [{'role': 'user', 'content': 'Please fix the failing backend test'}]

        with patch('backend.engine.planner.check_tools', return_value=[]):
            params = p.build_llm_params(messages, state, [])

        joined = '\n'.join(
            m['content']
            for m in params['messages']
            if isinstance(m.get('content'), str)
        )
        assert '<FIRST_TURN_ORIENTATION>' not in joined

    def test_first_turn_orientation_never_appears_across_retries(self):
        p = _make_planner(
            config=_make_config(enable_first_turn_orientation_prompt=True)
        )
        state = _make_state()
        state.iteration_flag.current_value = 1
        messages = [{'role': 'user', 'content': 'Please fix one failing test'}]

        with patch('backend.engine.planner.check_tools', return_value=[]):
            first = p.build_llm_params(messages, state, [])
            second = p.build_llm_params(messages, state, [])

        for params in (first, second):
            joined = '\n'.join(
                m['content']
                for m in params['messages']
                if isinstance(m.get('content'), str)
            )
            assert '<FIRST_TURN_ORIENTATION>' not in joined

    def test_plan_mode_prompt_policy_uses_simplified_protocol(self):
        p = _make_planner(config=_make_config(mode='plan'))
        state = _make_state()
        messages = [{'role': 'user', 'content': 'Plan a refactor'}]

        with patch('backend.engine.planner.check_tools', return_value=[]):
            params = p.build_llm_params(messages, state, [])

        joined = '\n'.join(
            m['content']
            for m in params['messages']
            if isinstance(m.get('content'), str)
        )
        assert 'CURRENT MODE: PLAN' in joined
        assert 'Current mode: PLAN' in joined
        assert joined.count('Current mode:') == 1
        assert 'Use `ask_user` only when user input is required to continue.' in joined
        assert 'Do not edit files or run shell commands.' in joined
        assert 'Write the final plan in plain text when complete' in joined
        assert 'Read-only mode' not in joined
        assert 'communicate_with_user' not in joined
        assert '`finish`' not in joined
        assert 'status, response, summary, sections, evidence' not in joined
        assert 'open_items, next_step' not in joined
        assert 'Recommended Plan' not in joined
        assert 'Verification Strategy' not in joined
        assert 'open_questions_or_blockers' not in joined
        assert 'Current mode: AGENT' not in joined

    def test_plan_mode_instructions_do_not_require_audit(self):
        p = _make_planner(config=_make_config(mode='plan'))
        state = _make_state()
        messages = [{'role': 'user', 'content': 'Plan a refactor'}]
        result = p._inject_plan_mode_instructions(messages, state)
        plan_blocks = [
            m['content']
            for m in result
            if isinstance(m.get('content'), str)
            and 'CURRENT MODE: PLAN' in m['content']
        ]
        assert plan_blocks
        plan_text = plan_blocks[0]
        assert 'do not audit in Plan mode' in plan_text
        assert 'acceptance_criteria(audit)' not in plan_text

    @pytest.mark.parametrize(
        ('mode', 'label'),
        [('chat', 'CHAT'), ('plan', 'PLAN'), ('agent', 'AGENT')],
    )
    def test_mode_protocol_injects_exactly_one_current_mode(self, mode, label):
        p = _make_planner(config=_make_config(mode=mode))
        state = _make_state()
        messages = [{'role': 'user', 'content': 'What mode are you in?'}]

        with patch('backend.engine.planner.check_tools', return_value=[]):
            params = p.build_llm_params(messages, state, [])

        joined = '\n'.join(
            m['content']
            for m in params['messages']
            if isinstance(m.get('content'), str)
        )
        assert joined.count('Current mode:') == 1
        assert f'Current mode: {label}' in joined


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
        ts.memory_pressure = 'WARNING'
        ts.repetition_score = 0.8
        state.turn_signals = ts
        state.extra_data = {}
        return state

    def test_no_injection_when_directive_absent(self):
        p = _make_planner()
        state = self._state_with_directive(None)

        messages = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': 'task'},
        ]
        with patch('backend.engine.planner.check_tools', return_value=[]):
            params = p.build_llm_params(messages, state, [])

        out = params['messages']
        joined = '\n'.join(
            m['content'] for m in out if isinstance(m.get('content'), str)
        )
        assert '<APP_CONTEXT_STATUS' not in joined
        assert '<APP_DIRECTIVE>' not in joined
        assert '<ACTIVE_PLAN>' not in joined
        assert 'REPETITION WARNING' not in joined
        assert 'CONTEXT PRESSURE' not in joined

    def test_only_directive_injected_when_present(self):
        p = _make_planner()
        state = self._state_with_directive('[GUARD] take next concrete step')

        messages = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': 'task'},
        ]
        with patch('backend.engine.planner.check_tools', return_value=[]):
            params = p.build_llm_params(messages, state, [])

        out = params['messages']
        assert out[-1] == {'role': 'user', 'content': 'task'}
        content = '\n'.join(
            m['content'] for m in out if isinstance(m.get('content'), str)
        )
        assert '<APP_DIRECTIVE>' in content
        assert '[GUARD] take next concrete step' in content
        assert '<APP_CONTEXT_STATUS' not in content
        assert '<ACTIVE_PLAN>' not in content
        assert 'REPETITION WARNING' not in content
        assert 'CONTEXT PRESSURE' not in content


# ---------------------------------------------------------------------------
# Meta-cognition tools
# ---------------------------------------------------------------------------
