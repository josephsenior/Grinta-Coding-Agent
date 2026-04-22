"""Tests for backend.utils.prompt module — data classes and PromptManager basics."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


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
    def test_identity_prefix_added(self, tmp_path):
        from backend.utils.prompt import OrchestratorPromptManager

        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path))
        result = opm.get_system_message()
        # prompt_builder always starts with "You are App" so OrchestratorPromptManager
        # should not duplicate the prefix but the result should contain it.
        assert 'You are App' in result

    def test_identity_prefix_not_duplicated(self, tmp_path):
        from backend.utils.prompt import OrchestratorPromptManager

        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path))
        result = opm.get_system_message()
        # prompt_builder starts with "You are App" so the OrchestratorPromptManager
        # should skip its own prefix. Only one occurrence of "You are App" expected.
        assert result.count('You are App') == 1

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
        # Full autonomy should be reflected
        assert 'FULL AUTONOMOUS MODE' in result

    def test_build_playbook_info(self, tmp_path):
        from backend.utils.prompt import PromptManager

        pm = PromptManager(prompt_dir=str(tmp_path))
        mock_agent = MagicMock()
        mock_agent.name = 'test_playbook'
        mock_agent.trigger = 'test_trigger'
        mock_agent.content = 'playbook content'
        result = pm.build_playbook_info([mock_agent])
        assert 'test_playbook' in result

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
        assert 'Native function-calling mode is active.' in result

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
            patch('backend.utils.prompt.sys.platform', 'win32'),
            patch(
                'backend.engine.tools.prompt.get_terminal_tool_name',
                return_value='execute_powershell',
            ),
            patch(
                'backend.engine.tools.prompt.is_windows_with_bash',
                return_value=True,
            ),
        ):
            result = opm.get_system_message()

        assert 'Your terminal is **PowerShell** on Windows.' in result
        assert 'Your terminal is **Git Bash** running on Windows.' not in result


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
        cfg.enable_internal_task_tracker = False
        cfg.enable_signal_progress = False
        cfg.enable_permissions = False
        cfg.enable_meta_cognition = False

        kwargs = dict(
            active_llm_model='gpt-4',
            is_windows=False,
            config=cfg,
            mcp_tool_names=[],
            mcp_tool_descriptions={},
            mcp_server_hints=[],
            function_calling_mode='native',
        )
        report = measure_system_prompt_sections(**kwargs)
        assert report['total_tokens'] > 100
        assert report['total_chars'] > 400
        assert len(report['sections']) >= 7
        assert report['sections'][0]['tokens'] >= report['sections'][-1]['tokens']
        built = build_system_prompt(**kwargs)
        assert len(built) == report['total_chars']
