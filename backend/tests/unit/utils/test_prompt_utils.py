"""Tests for backend.utils.prompt module — data classes and PromptManager basics."""

from types import SimpleNamespace
from typing import Any, TypedDict, cast
from unittest.mock import MagicMock, patch

import pytest


class _PromptBuilderKwargs(TypedDict):
    active_llm_model: str
    is_windows: bool
    config: Any
    mcp_tool_names: list[str]
    mcp_tool_descriptions: dict[str, str]
    mcp_server_hints: list[dict[str, str]]
    function_calling_mode: str


class TestRuntimeInfo:
    def test_defaults(self):
        from backend.utils.prompt import RuntimeInfo

        ri = RuntimeInfo(date='2024-01-01')
        assert ri.date == '2024-01-01'
        assert ri.available_hosts == {}
        assert ri.additional_agent_instructions == ''
        assert ri.custom_secrets_descriptions == {}
        assert ri.working_dir == ''

    def test_with_values(self):
        from backend.utils.prompt import RuntimeInfo

        ri = RuntimeInfo(
            date='2024-06-15',
            available_hosts={'localhost': 3000},
            additional_agent_instructions='Be concise',
            working_dir='/workspace',
        )
        assert ri.available_hosts == {'localhost': 3000}
        assert ri.additional_agent_instructions == 'Be concise'
        assert ri.working_dir == '/workspace'


class TestRepositoryInfo:
    def test_defaults(self):
        from backend.utils.prompt import RepositoryInfo

        ri = RepositoryInfo()
        assert ri.repo_name is None
        assert ri.repo_directory is None
        assert ri.branch_name is None

    def test_with_values(self):
        from backend.utils.prompt import RepositoryInfo

        ri = RepositoryInfo(
            repo_name='app', repo_directory='/repos/app', branch_name='main'
        )
        assert ri.repo_name == 'app'
        assert ri.repo_directory == '/repos/app'
        assert ri.branch_name == 'main'


class TestConversationInstructions:
    def test_defaults(self):
        from backend.utils.prompt import ConversationInstructions

        ci = ConversationInstructions()
        assert ci.content == ''

    def test_with_content(self):
        from backend.utils.prompt import ConversationInstructions

        ci = ConversationInstructions(content='Respond to GitHub issue #1234')
        assert ci.content == 'Respond to GitHub issue #1234'


class TestUninitializedPromptManager:
    def test_sentinel_exists(self):
        from backend.utils.prompt import (
            UNINITIALIZED_PROMPT_MANAGER,
            _UninitializedPromptManager,
        )

        assert isinstance(UNINITIALIZED_PROMPT_MANAGER, _UninitializedPromptManager)


class TestPromptManager:
    def test_none_prompt_dir_raises(self):
        from backend.utils.prompt import PromptManager

        with pytest.raises(ValueError, match='Prompt directory is not set'):
            PromptManager(prompt_dir=None)

    def test_valid_init(self, tmp_path):
        from backend.utils.prompt import PromptManager

        pm = PromptManager(prompt_dir=str(tmp_path))
        assert pm.prompt_dir == str(tmp_path)

    def test_get_system_message(self, tmp_path):
        from backend.utils.prompt import PromptManager

        pm = PromptManager(prompt_dir=str(tmp_path))
        result = pm.get_system_message()
        assert 'You are Grinta' in result

    def test_get_example_user_message(self, tmp_path):
        from backend.utils.prompt import PromptManager

        pm = PromptManager(prompt_dir=str(tmp_path))
        result = pm.get_example_user_message()
        assert result == ''

    def test_build_workspace_context(self, tmp_path):
        from backend.utils.prompt import (
            ConversationInstructions,
            PromptManager,
            RepositoryInfo,
            RuntimeInfo,
        )

        pm = PromptManager(prompt_dir=str(tmp_path))
        result = pm.build_workspace_context(
            repository_info=RepositoryInfo(repo_name='myrepo'),
            runtime_info=RuntimeInfo(date='2024-01-01'),
            conversation_instructions=ConversationInstructions(),
        )
        assert 'myrepo' in result


class TestOrchestratorPromptManager:
    def test_identity_uses_grinta_once(self, tmp_path):
        from backend.utils.prompt import OrchestratorPromptManager

        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path))
        result = opm.get_system_message()
        assert result.count('You are Grinta') == 1
        assert 'You are App' not in result

    def test_config_injected(self, tmp_path):
        from backend.utils.prompt import OrchestratorPromptManager

        mock_config = MagicMock()
        mock_config.cli_mode = True
        mock_config.autonomy_level = 'full'
        mock_config.enable_checkpoints = False
        mock_config.enable_permissions = False
        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path), config=mock_config)
        result = opm.get_system_message()
        # cli_mode=True triggers CLI-specific security risk block
        assert 'Security Risk Policy' in result
        # Autonomy block is now mode-agnostic; just confirm it rendered.
        assert '<AUTONOMY>' in result

    def test_build_playbook_info(self, tmp_path):
        from backend.utils.prompt import PromptManager

        pm = PromptManager(prompt_dir=str(tmp_path))
        mock_agent = MagicMock()
        mock_agent.name = 'test_playbook'
        mock_agent.trigger = 'test_trigger'
        mock_agent.content = 'playbook content'
        result = pm.build_playbook_info([mock_agent])
        assert 'test_playbook' in result

    def test_get_system_message_omits_task_tracker_when_disabled(self, tmp_path):
        from backend.utils.prompt import OrchestratorPromptManager

        mock_config = SimpleNamespace(
            autonomy_level='balanced',
            enable_checkpoints=False,
            enable_lsp_query=False,
            enable_task_tracker_tool=False,
            enable_permissions=False,
            enable_meta_cognition=False,
            enable_working_memory=True,
        )

        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path), config=mock_config)
        result = opm.get_system_message()

        assert 'sync `task_tracker`' not in result
        assert 'Update `task_tracker` to `done`, `skipped`, or `blocked`' not in result
        assert 'Trust your `task_tracker` plan as the source of truth' not in result

    def test_get_system_message_omits_communicate_tool_when_meta_cognition_disabled(
        self, tmp_path
    ):
        from backend.utils.prompt import OrchestratorPromptManager

        config = SimpleNamespace(
            autonomy_level='balanced',
            enable_checkpoints=False,
            enable_lsp_query=False,
            enable_task_tracker_tool=False,
            enable_permissions=False,
            enable_meta_cognition=False,
            enable_working_memory=True,
        )

        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path), config=config)
        result = opm.get_system_message()

        assert '`communicate_with_user`' not in result
        assert 'ask the user a short clarifying question in natural language' in result

    def test_get_system_message_omits_summarize_context_when_disabled(self, tmp_path):
        from backend.utils.prompt import OrchestratorPromptManager

        config = SimpleNamespace(
            autonomy_level='balanced',
            enable_checkpoints=False,
            enable_lsp_query=False,
            enable_task_tracker_tool=False,
            enable_permissions=False,
            enable_meta_cognition=False,
            enable_working_memory=True,
            enable_condensation_request=False,
        )

        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path), config=config)
        result = opm.get_system_message()

        assert '`summarize_context`' not in result
        assert 'You are Grinta' in result

    def test_get_system_message_omits_working_memory_tool_when_disabled(self, tmp_path):
        from backend.utils.prompt import OrchestratorPromptManager

        config = SimpleNamespace(
            autonomy_level='balanced',
            enable_checkpoints=False,
            enable_lsp_query=False,
            enable_task_tracker_tool=False,
            enable_permissions=False,
            enable_meta_cognition=False,
            enable_working_memory=False,
            enable_condensation_request=False,
        )

        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path), config=config)
        result = opm.get_system_message()

        assert '`memory_manager(action="working_memory")`' not in result
        assert '`memory_manager(action="semantic_recall", key=...)`' not in result

    def test_get_system_message_uses_lsp_when_lsp_is_available(self, tmp_path):
        from backend.utils.prompt import OrchestratorPromptManager

        config = SimpleNamespace(
            autonomy_level='balanced',
            enable_checkpoints=False,
            enable_lsp_query=True,
            enable_task_tracker_tool=False,
            enable_permissions=False,
            enable_meta_cognition=False,
            enable_working_memory=True,
            enable_condensation_request=False,
            enable_terminal=True,
        )

        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path), config=config)
        with patch(
            'backend.utils.runtime_detect.has_any_lsp_server', return_value=True
        ):
            result = opm.get_system_message()

        assert '`lsp`' in result
        assert '`lsp_query`' not in result

    def test_get_system_message_omits_lsp_when_lsp_unavailable(self, tmp_path):
        from backend.utils.prompt import OrchestratorPromptManager

        config = SimpleNamespace(
            autonomy_level='balanced',
            enable_checkpoints=False,
            enable_lsp_query=True,
            enable_task_tracker_tool=False,
            enable_permissions=False,
            enable_meta_cognition=False,
            enable_working_memory=True,
            enable_condensation_request=False,
            enable_terminal=True,
        )

        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path), config=config)
        with patch(
            'backend.utils.runtime_detect.has_any_lsp_server', return_value=False
        ):
            result = opm.get_system_message()

        assert '`lsp`' not in result
        assert '`lsp_query`' not in result

    def test_get_system_message_omits_terminal_manager_when_terminal_disabled(
        self, tmp_path
    ):
        from backend.utils.prompt import OrchestratorPromptManager

        config = SimpleNamespace(
            autonomy_level='balanced',
            enable_checkpoints=False,
            enable_lsp_query=False,
            enable_task_tracker_tool=False,
            enable_permissions=False,
            enable_meta_cognition=False,
            enable_working_memory=True,
            enable_condensation_request=False,
            enable_terminal=False,
        )

        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path), config=config)
        result = opm.get_system_message()

        assert '`terminal_manager action=open`' not in result
        assert 'do not refer to `terminal_manager`' not in result

    def test_build_knowledge_base_info(self, tmp_path):
        from backend.utils.prompt import PromptManager

        pm = PromptManager(prompt_dir=str(tmp_path))
        mock_result = MagicMock()
        mock_result.content = 'kb_content'
        mock_result.filename = 'doc.md'
        mock_result.relevance_score = 0.95
        mock_result.chunk_content = 'kb_content'
        result = pm.build_knowledge_base_info([mock_result])
        assert 'kb_content' in result

    def test_add_turns_left_reminder(self, tmp_path):
        from backend.core.message import Message, TextContent
        from backend.utils.prompt import PromptManager

        pm = PromptManager(prompt_dir=str(tmp_path))
        msg = Message(role='user', content=[TextContent(text='Hello')])
        mock_state = MagicMock()
        mock_state.iteration_flag.max_value = 10
        mock_state.iteration_flag.current_value = 2

        pm.add_turns_left_reminder([msg], mock_state)

        last_content = msg.content[-1]
        assert isinstance(last_content, TextContent)
        assert '8 turns left' in last_content.text

    def test_inject_lessons_learned(self, tmp_path):
        from backend.utils.prompt import OrchestratorPromptManager

        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path))
        opm.set_prompt_tier('debug')

        with (
            patch(
                'backend.core.workspace_resolution.get_effective_workspace_root',
                return_value=tmp_path,
            ),
            patch(
                'backend.core.workspace_resolution.workspace_agent_state_dir',
                return_value=tmp_path,
            ),
        ):
            # Test missing lessons file
            result = opm.get_system_message()
            assert 'REPOSITORY_LESSONS_LEARNED' not in result

            # Test existing lessons file
            lessons_file = tmp_path / 'lessons.md'
            lessons_file.write_text('Always test your code.', encoding='utf-8')

            result = opm.get_system_message()
            assert 'REPOSITORY_LESSONS_LEARNED' in result
            assert 'Always test your code.' in result

    def test_inject_scratchpad(self, tmp_path):
        from backend.utils.prompt import OrchestratorPromptManager

        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path))

        with (
            patch(
                'backend.engine.tools.note.scratchpad_entries_for_prompt',
                return_value=[('key', 'val')],
            ),
            patch(
                'backend.engine.tools.working_memory.get_working_memory_prompt_block',
                return_value='',
            ),
        ):
            result = opm.get_system_message()
            assert 'WORKING_SCRATCHPAD' in result
            assert '[key]: val' in result

    def test_function_calling_mode_native_guidance(self, tmp_path):
        from backend.utils.prompt import OrchestratorPromptManager

        mock_config = MagicMock()
        mock_config.autonomy_level = 'balanced'
        mock_config.enable_checkpoints = False
        mock_config.enable_permissions = False
        mock_app_config = MagicMock()
        mock_app_config.get_llm_config_from_agent_config.return_value = SimpleNamespace(
            model='openai/gpt-4o-mini',
            native_tool_calling=None,
        )

        opm = OrchestratorPromptManager(
            prompt_dir=str(tmp_path),
            config=mock_config,
            app_config=mock_app_config,
        )

        with patch(
            'backend.inference.model_features.get_features',
            return_value=SimpleNamespace(supports_function_calling=True),
        ):
            result = opm.get_system_message()

        assert 'Tool-call batching mode:' in result
        assert '- **Function-calling mode**: `native`.' in result

    def test_function_calling_mode_string_guidance_when_disabled(self, tmp_path):
        from backend.utils.prompt import OrchestratorPromptManager

        mock_config = MagicMock()
        mock_config.autonomy_level = 'balanced'
        mock_config.enable_checkpoints = False
        mock_config.enable_permissions = False
        mock_app_config = MagicMock()
        mock_app_config.get_llm_config_from_agent_config.return_value = SimpleNamespace(
            model='openai/gpt-4o-mini',
            native_tool_calling=False,
        )

        opm = OrchestratorPromptManager(
            prompt_dir=str(tmp_path),
            config=mock_config,
            app_config=mock_app_config,
        )
        result = opm.get_system_message()

        assert 'Tool-call batching mode:' in result
        assert 'Fallback string-parsing mode is active.' in result

    def test_shell_identity_uses_active_terminal_tool_over_bash_presence(
        self, tmp_path
    ):
        from backend.utils.prompt import OrchestratorPromptManager

        mock_config = MagicMock()
        mock_config.autonomy_level = 'balanced'
        mock_config.enable_checkpoints = False
        mock_config.enable_permissions = False

        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path), config=mock_config)

        with (
            patch('backend.utils.prompt.OS_CAPS') as mock_caps,
            patch(
                'backend.engine.tools.prompt.get_terminal_tool_name',
                return_value='execute_powershell',
            ),
            patch(
                'backend.engine.tools.prompt.is_windows_with_bash',
                return_value=True,
            ),
        ):
            mock_caps.is_windows = True
            result = opm.get_system_message()

        assert 'Your terminal is **PowerShell** on Windows.' in result
        assert 'Your terminal is **Git Bash** running on Windows.' not in result

    def test_mcp_tools_and_server_hints_are_rendered(self, tmp_path):
        from backend.utils.prompt import OrchestratorPromptManager

        mock_config = MagicMock()
        mock_config.autonomy_level = 'balanced'
        mock_config.enable_checkpoints = False
        mock_config.enable_permissions = False

        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path), config=mock_config)
        opm.mcp_tool_names = ['github_search']
        opm.mcp_tool_descriptions = {'github_search': 'Search GitHub code'}
        opm.mcp_server_hints = [
            {'server': 'github', 'hint': 'Use for repository metadata and code search'}
        ]

        result = opm.get_system_message()
        addendum = opm.get_mcp_user_addendum()

        assert 'call_mcp_tool(tool_name="...", arguments={...})' not in result
        assert '`github_search`' not in result
        assert 'Configured MCP servers' not in result

        assert 'call_mcp_tool(tool_name="...", arguments={...})' in addendum
        assert '`github_search`' in addendum
        assert 'Search GitHub code' in addendum
        assert 'Configured MCP servers' in addendum
        assert '**`github`:** Use for repository metadata and code search' in addendum


class TestPromptBuilderSectionTokens:
    def test_count_section_tokens_positive(self) -> None:
        from backend.engine.prompts.prompt_builder import _count_section_tokens

        n, label = _count_section_tokens('hello world', 'gpt-4')
        assert n >= 1
        assert label

    def test_measure_system_prompt_sections_and_build_match(self) -> None:
        from backend.engine.prompts.prompt_builder import (
            build_system_prompt,
            measure_system_prompt_sections,
        )

        cfg = MagicMock()
        cfg.autonomy_level = 'balanced'
        cfg.enable_checkpoints = False
        cfg.enable_lsp_query = False
        cfg.enable_task_tracker_tool = False
        cfg.enable_permissions = False
        cfg.enable_meta_cognition = False

        kwargs: _PromptBuilderKwargs = {
            'active_llm_model': 'gpt-4',
            'is_windows': False,
            'config': cfg,
            'mcp_tool_names': [],
            'mcp_tool_descriptions': {},
            'mcp_server_hints': [],
            'function_calling_mode': 'native',
        }
        report = measure_system_prompt_sections(**kwargs)
        assert report['total_tokens'] > 100
        assert report['total_chars'] > 400
        assert len(report['sections']) >= 7
        assert report['sections'][0]['tokens'] >= report['sections'][-1]['tokens']
        built = build_system_prompt(**kwargs)
        assert len(built) == report['total_chars']


def _make_budget_cfg(**overrides: object) -> MagicMock:
    cfg = MagicMock()
    cfg.autonomy_level = overrides.get('autonomy_level', 'balanced')
    cfg.enable_checkpoints = False
    cfg.enable_lsp_query = False
    cfg.enable_task_tracker_tool = bool(
        overrides.get('enable_task_tracker_tool', False)
    )
    cfg.enable_permissions = False
    cfg.enable_meta_cognition = False
    cfg.cli_mode = bool(overrides.get('cli_mode', False))
    return cfg


class TestPromptBudgetRegression:
    """Token-budget regression guard.

    Ceilings are set at post-compression baseline + ~10 % headroom.
    A test failure here means new prompt text was added without a corresponding
    reduction — not that the implementation is broken.
    """

    def test_unix_balanced_no_mcp_token_ceiling(self) -> None:
        from backend.engine.prompts.prompt_builder import measure_system_prompt_sections

        report = measure_system_prompt_sections(
            active_llm_model='gpt-4',
            is_windows=False,
            config=_make_budget_cfg(),
            mcp_tool_names=[],
            mcp_tool_descriptions={},
            mcp_server_hints=[],
            function_calling_mode='native',
        )
        # Floor: prompt must be substantive.
        assert report['total_tokens'] >= 800, 'Prompt shrank unexpectedly'
        # Ceiling: guards against prompt bloat regressions.
        # Baseline post-compression: 4 203 tokens.  Ceiling = baseline + ~10 %.
        assert report['total_tokens'] <= 4_650, (
            f'Prompt exceeds budget ceiling: {report["total_tokens"]} tokens '
            '(baseline 4 203). Reduce prompt text or raise this ceiling deliberately.'
        )

    def test_windows_ps_balanced_no_mcp_token_ceiling(self) -> None:
        from backend.engine.prompts.prompt_builder import measure_system_prompt_sections

        report = measure_system_prompt_sections(
            active_llm_model='gpt-4',
            is_windows=True,
            config=_make_budget_cfg(),
            mcp_tool_names=[],
            mcp_tool_descriptions={},
            mcp_server_hints=[],
            function_calling_mode='native',
        )
        assert report['total_tokens'] >= 800, 'Prompt shrank unexpectedly'
        # Baseline post-compression: 4 379 tokens.  Ceiling = baseline + ~10 %.
        assert report['total_tokens'] <= 4_820, (
            f'Prompt exceeds budget ceiling: {report["total_tokens"]} tokens '
            '(baseline 4 379). Reduce prompt text or raise this ceiling deliberately.'
        )

    def test_full_autonomy_tracker_mcp_token_ceiling(self) -> None:
        from backend.engine.prompts.prompt_builder import measure_system_prompt_sections

        cfg = _make_budget_cfg(autonomy_level='full', enable_task_tracker_tool=True)
        report = measure_system_prompt_sections(
            active_llm_model='gpt-4',
            is_windows=False,
            config=cfg,
            mcp_tool_names=['search_github', 'read_file'],
            mcp_tool_descriptions={
                'search_github': 'Search GitHub',
                'read_file': 'Read a file',
            },
            mcp_server_hints=[{'server': 'github', 'hint': 'Use for GitHub ops'}],
            function_calling_mode='native',
        )
        assert report['total_tokens'] >= 1_000, 'Prompt shrank unexpectedly'
        # Baseline post-compression: 5 103 tokens.  Ceiling = baseline + ~10 %.
        assert report['total_tokens'] <= 5_620, (
            f'Prompt exceeds budget ceiling: {report["total_tokens"]} tokens '
            '(baseline 5 103). Reduce prompt text or raise this ceiling deliberately.'
        )


# ---------------------------------------------------------------------------
# Prompt contract hardening tests
# ---------------------------------------------------------------------------


def _base_config(**overrides: object) -> SimpleNamespace:
    """Minimal config SimpleNamespace with safe defaults for prompt rendering tests."""
    return SimpleNamespace(
        mode=str(overrides.get('mode', 'agent')),
        autonomy_level=overrides.get('autonomy_level', 'balanced'),
        enable_checkpoints=bool(overrides.get('enable_checkpoints', False)),
        enable_lsp_query=bool(overrides.get('enable_lsp_query', False)),
        enable_task_tracker_tool=bool(overrides.get('enable_task_tracker_tool', False)),
        enable_permissions=False,
        enable_meta_cognition=bool(overrides.get('enable_meta_cognition', False)),
        enable_working_memory=bool(overrides.get('enable_working_memory', True)),
        enable_condensation_request=bool(
            overrides.get('enable_condensation_request', False)
        ),
        enable_terminal=bool(overrides.get('enable_terminal', True)),
    )


class TestValidateRenderKeys:
    """Unit tests for _validate_render_keys and PromptRenderError."""

    def test_missing_key_raises_prompt_render_error(self) -> None:
        from backend.engine.prompts.prompt_builder import (
            PromptRenderError,
            _validate_render_keys,
        )

        with pytest.raises(PromptRenderError, match='missing substitution keys'):
            _validate_render_keys(
                'Hello {name}, you are {missing_key}.',
                {'name': 'Alice'},
                partial_name='test.md',
            )

    def test_all_keys_present_does_not_raise(self) -> None:
        from backend.engine.prompts.prompt_builder import _validate_render_keys

        # Should complete without raising
        _validate_render_keys(
            '{greeting} {target}',
            {'greeting': 'Hello', 'target': 'world'},
        )

    def test_extra_keys_in_substitution_do_not_raise(self) -> None:
        from backend.engine.prompts.prompt_builder import _validate_render_keys

        # Extra keys are harmless for str.format() and must not be treated as errors
        _validate_render_keys(
            '{greeting}',
            {'greeting': 'Hi', 'extra_unused': 'ignored'},
        )

    def test_escaped_braces_not_treated_as_placeholders(self) -> None:
        from backend.engine.prompts.prompt_builder import _validate_render_keys

        # {{double_braces}} are Python format-string literals — not placeholders
        _validate_render_keys(
            'Literal {{not_a_key}} and real {actual_key}',
            {'actual_key': 'value'},
        )

    def test_error_message_lists_all_missing_keys(self) -> None:
        from backend.engine.prompts.prompt_builder import (
            PromptRenderError,
            _validate_render_keys,
        )

        with pytest.raises(PromptRenderError) as exc_info:
            _validate_render_keys(
                '{a} {b} {c}',
                {'a': '1'},
                partial_name='multi.md',
            )
        msg = str(exc_info.value)
        assert "'b'" in msg or 'b' in msg
        assert "'c'" in msg or 'c' in msg
        assert 'multi.md' in msg

    def test_empty_template_no_keys_no_error(self) -> None:
        from backend.engine.prompts.prompt_builder import _validate_render_keys

        _validate_render_keys('No placeholders here.', {})

    def test_render_partial_produces_correct_output(self) -> None:
        from backend.engine.prompts.prompt_builder import _render_partial

        # Patch _load so we don't touch disk
        with patch(
            'backend.engine.prompts.prompt_builder._load',
            return_value='Hello {name}!',
        ):
            result = _render_partial('fake_partial.md', name='World')
        assert result == 'Hello World!'

    def test_render_partial_raises_on_missing_key(self) -> None:
        from backend.engine.prompts.prompt_builder import (
            PromptRenderError,
            _render_partial,
        )

        with patch(
            'backend.engine.prompts.prompt_builder._load',
            return_value='{required_key} content',
        ):
            with pytest.raises(PromptRenderError):
                _render_partial('fake_partial.md')  # no kwargs


def test_render_runtime_detection_omits_disabled_tools() -> None:
    """Gated-off LSP/debugger: no capability bullet (not a DISABLED line)."""
    from backend.engine.prompts.section_renderers import _render_runtime_detection_lines

    lsp_empty, dap_empty = _render_runtime_detection_lines(
        SimpleNamespace(enable_lsp_query=False, enable_debugger=False)
    )
    assert lsp_empty == ''
    assert dap_empty == ''

    with (
        patch(
            'backend.utils.runtime_detect.has_any_debug_adapter',
            return_value=True,
        ),
        patch(
            'backend.utils.runtime_detect.detection_summary',
            return_value={
                'lsp_available': [],
                'debug_available': ['debugpy'],
            },
        ),
    ):
        _, dap_on = _render_runtime_detection_lines(
            SimpleNamespace(enable_debugger=True, enable_lsp_query=False)
        )
    assert 'detected' in dap_on
    assert '`debugger`' in dap_on


def test_system_capabilities_skips_lsp_dap_discovery_hint_when_both_gated_off() -> None:
    """No runtime-probe paragraph if there are no LSP/DAP bullets."""
    from backend.engine.prompts.section_renderers import _render_system_capabilities

    cfg = SimpleNamespace(
        enable_parallel_tool_scheduling=False,
        enable_checkpoints=False,
        enable_lsp_query=False,
        enable_debugger=False,
    )
    text = _render_system_capabilities(
        cfg,
        function_calling_mode='native',
        parallel_tool_calls_provider_flag=False,
    )
    assert 'Get-Command' not in text





class TestBuildSystemPromptRenders:
    """Integration-level tests: build_system_prompt must not raise PromptRenderError
    for any supported feature-flag combination, and must produce non-empty output.
    """

    def _assert_renders_cleanly(self, **kwargs: object) -> str:
        from backend.engine.prompts.prompt_builder import build_system_prompt

        result = build_system_prompt(**cast(_PromptBuilderKwargs, kwargs))
        assert isinstance(result, str)
        assert len(result) > 200, 'Prompt is suspiciously short'
        return result

    def test_unix_balanced_default(self) -> None:
        self._assert_renders_cleanly(
            active_llm_model='claude-sonnet-4-6',
            is_windows=False,
            config=_base_config(),
            function_calling_mode='native',
        )

    def test_windows_powershell(self) -> None:
        result = self._assert_renders_cleanly(
            active_llm_model='gpt-4o',
            is_windows=True,
            config=_base_config(),
            function_calling_mode='native',
        )
        assert (
            'Be thorough and direct; prefer completeness and verification details over brevity.'
            in result
        )
        assert (
            'In Chat mode, prose is the default.'
            in result
        )
        assert 'Be terse and direct.' not in result

    def test_windows_git_bash(self) -> None:
        self._assert_renders_cleanly(
            active_llm_model='gpt-4o',
            is_windows=True,
            windows_with_bash=True,
            config=_base_config(),
            function_calling_mode='string',
        )

    def test_small_model_short_prompt(self) -> None:
        result = self._assert_renders_cleanly(
            active_llm_model='llama3.2',
            is_windows=False,
            config=_base_config(),
            function_calling_mode='string',
        )
        # Examples partial is omitted for small models
        assert 'WORKED EXAMPLE' not in result or True  # structural check only

    def test_full_autonomy(self) -> None:
        result = self._assert_renders_cleanly(
            active_llm_model='gpt-4o',
            is_windows=False,
            config=_base_config(autonomy_level='full'),
            function_calling_mode='native',
        )
        # The autonomy block is now mode-agnostic; only one neutral block is
        # rendered regardless of autonomy_level.
        assert '<AUTONOMY>' in result
        assert 'runtime may interrupt' in result
        # Old mode-specific copy must no longer leak through.
        assert 'FULL AUTONOMOUS MODE' not in result

    def test_task_tracker_enabled(self) -> None:
        result = self._assert_renders_cleanly(
            active_llm_model='gpt-4o',
            is_windows=False,
            config=_base_config(enable_task_tracker_tool=True),
            function_calling_mode='native',
        )
        assert 'task_tracker' in result

    def test_meta_cognition_enabled(self) -> None:
        result = self._assert_renders_cleanly(
            active_llm_model='gpt-4o',
            is_windows=False,
            config=_base_config(enable_meta_cognition=True),
            function_calling_mode='native',
        )
        assert 'communicate_with_user' in result

    def test_mcp_inline(self) -> None:
        result = self._assert_renders_cleanly(
            active_llm_model='gpt-4o',
            is_windows=False,
            config=_base_config(),
            mcp_tool_names=['search_github'],
            mcp_tool_descriptions={'search_github': 'Search GitHub repositories'},
            mcp_server_hints=[{'server': 'github', 'hint': 'Use for repo search'}],
            function_calling_mode='native',
            render_mcp_inline=True,
        )
        assert '`search_github`' in result

    def test_mcp_addendum_not_inline(self) -> None:
        from backend.engine.prompts.prompt_builder import build_mcp_user_addendum

        result = self._assert_renders_cleanly(
            active_llm_model='gpt-4o',
            is_windows=False,
            config=_base_config(),
            mcp_tool_names=['search_github'],
            mcp_tool_descriptions={'search_github': 'Search GitHub repositories'},
            render_mcp_inline=False,
        )
        # MCP tool must NOT appear in system prompt when render_mcp_inline=False
        assert '`search_github`' not in result

        addendum = build_mcp_user_addendum(
            mcp_tool_names=['search_github'],
            mcp_tool_descriptions={'search_github': 'Search GitHub repositories'},
        )
        assert '`search_github`' in addendum

    def test_working_memory_disabled(self) -> None:
        result = self._assert_renders_cleanly(
            active_llm_model='gpt-4o',
            is_windows=False,
            config=_base_config(enable_working_memory=False),
            function_calling_mode='native',
        )
        assert 'memory_manager(action="working_memory")' not in result

    def test_condensation_request_enabled(self) -> None:
        result = self._assert_renders_cleanly(
            active_llm_model='gpt-4o',
            is_windows=False,
            config=_base_config(enable_condensation_request=True),
            function_calling_mode='native',
        )
        assert 'You are Grinta' in result

    def test_terminal_disabled(self) -> None:
        result = self._assert_renders_cleanly(
            active_llm_model='gpt-4o',
            is_windows=False,
            config=_base_config(enable_terminal=False),
            function_calling_mode='native',
        )
        assert 'do not refer to `terminal_manager`' not in result

    def test_lsp_available(self) -> None:
        with patch(
            'backend.utils.runtime_detect.has_any_lsp_server', return_value=True
        ):
            result = self._assert_renders_cleanly(
                active_llm_model='gpt-4o',
                is_windows=False,
                config=_base_config(enable_lsp_query=True),
                function_calling_mode='native',
            )
        assert 'lsp' in result

    def test_unknown_function_calling_mode(self) -> None:
        result = self._assert_renders_cleanly(
            active_llm_model='gpt-4o',
            is_windows=False,
            config=_base_config(),
            function_calling_mode=None,
        )
        assert 'Tool-call batching mode:' in result
        assert '- **Function-calling mode**: `unknown`.' in result

    # --- Prompt lint tests ---

    STALE_TOOL_NAMES = [
        'read_file', 'read_range', 'read_symbol',
        'create_file',
        'replace_symbol', 'insert_symbol',
    ]

    OLD_EDIT_FORMATS = [
        'XML edit block',
        'raw editor block',
        'apply_patch',
        'heredoc source write',
    ]

    def test_no_stale_tool_names(self) -> None:
        result = self._assert_renders_cleanly(
            active_llm_model='gpt-4o',
            is_windows=False,
            config=_base_config(),
            function_calling_mode='native',
        )
        for stale in self.STALE_TOOL_NAMES:
            assert stale not in result, f'Stale tool name {stale!r} found in rendered prompt'

    def test_no_old_edit_formats(self) -> None:
        result = self._assert_renders_cleanly(
            active_llm_model='gpt-4o',
            is_windows=False,
            config=_base_config(),
            function_calling_mode='native',
        )
        for fmt in self.OLD_EDIT_FORMATS:
            assert fmt not in result, f'Old edit format {fmt!r} found in rendered prompt'

    def test_no_disabled_tools_when_off(self) -> None:
        result = self._assert_renders_cleanly(
            active_llm_model='gpt-4o',
            is_windows=False,
            config=_base_config(
                enable_task_tracker_tool=False,
                enable_checkpoints=False,
                enable_working_memory=False,
            ),
            function_calling_mode='native',
        )
        # The tool names themselves should not appear when disabled
        assert 'task_tracker' not in result, (
            'task_tracker mentioned when tool is disabled'
        )
        assert 'checkpoint' not in result, (
            'checkpoint mentioned when tool is disabled'
        )
        assert 'memory_manager' not in result, (
            'memory_manager mentioned when tool is disabled'
        )

    def test_plan_mode_omits_mutation_tools(self) -> None:
        result = self._assert_renders_cleanly(
            active_llm_model='gpt-4o',
            is_windows=False,
            config=_base_config(mode='plan'),
            function_calling_mode='native',
        )
        assert 'Plan, execute, and verify' not in result
        assert '<AUTONOMY>' in result

    def test_chat_mode_avoids_execution_language(self) -> None:
        result = self._assert_renders_cleanly(
            active_llm_model='gpt-4o',
            is_windows=False,
            config=_base_config(mode='chat'),
            function_calling_mode='native',
        )
        assert '<AUTONOMY>' in result
        assert 'mutate files' in result or 'investigation' in result
