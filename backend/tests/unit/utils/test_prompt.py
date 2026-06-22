"""Unit tests for backend.utils.prompt — Prompt management and template rendering."""

from unittest.mock import MagicMock, patch

import pytest

from backend.core.message import Message, TextContent
from backend.utils.prompt import (
    UNINITIALIZED_PROMPT_MANAGER,
    OrchestratorPromptManager,
    PromptManager,
    _UninitializedPromptManager,
)
from backend.utils.terminal.terminal_contract import (
    build_python_exec_command,
    get_python_shell_command,
    get_shell_name,
    get_terminal_tool_name,
    uses_powershell_terminal,
)


@pytest.fixture
def prompt_dir(tmp_path):
    d = tmp_path / 'prompts'
    d.mkdir()
    return str(d)


class TestPromptManager:
    def test_init_raises_if_no_dir(self):
        with pytest.raises(ValueError, match='Prompt directory is not set'):
            PromptManager(None)

    def test_get_system_message(self, prompt_dir):
        pm = PromptManager(prompt_dir)
        msg = pm.get_system_message(name='App')
        assert 'You are Grinta' in msg

    def test_get_example_user_message(self, prompt_dir):
        pm = PromptManager(prompt_dir)
        assert pm.get_example_user_message() == ''

    def test_build_workspace_context(self, prompt_dir):
        pm = PromptManager(prompt_dir)
        ctx = pm.build_workspace_context(
            None, None, None, repo_instructions='test-repo'
        )
        assert 'test-repo' in ctx

    def test_build_workspace_context_includes_project_path_guidance(self, prompt_dir):
        from backend.utils.prompt import RuntimeInfo

        pm = PromptManager(prompt_dir)
        ctx = pm.build_workspace_context(
            None,
            RuntimeInfo(date='2026-01-01', working_dir='/tmp/grinta_project'),
            None,
        )
        assert 'The current working directory is /tmp/grinta_project' in ctx
        assert 'relative' in ctx.lower()

    def test_build_workspace_context_notes_bare_workspace(self, prompt_dir):
        from backend.utils.prompt import RuntimeInfo

        pm = PromptManager(prompt_dir)
        ctx = pm.build_workspace_context(
            None,
            RuntimeInfo(date='2026-01-01', working_dir='/tmp/grinta_project'),
            None,
        )
        assert 'plain local workspace' in ctx

    def test_build_workspace_context_omits_bare_note_with_repo_instructions(
        self, prompt_dir
    ):
        from backend.utils.prompt import RuntimeInfo

        pm = PromptManager(prompt_dir)
        ctx = pm.build_workspace_context(
            None,
            RuntimeInfo(date='2026-01-01', working_dir='/tmp/grinta_project'),
            None,
            repo_instructions='Follow the house style.',
        )
        assert 'plain local workspace' not in ctx
        assert 'does not list project files' in ctx
        assert 'glob' in ctx

    def test_build_playbook_info(self, prompt_dir):
        pm = PromptManager(prompt_dir)
        assert pm.build_playbook_info([]) == ''

    def test_build_knowledge_base_info(self, prompt_dir):
        pm = PromptManager(prompt_dir)
        assert pm.build_knowledge_base_info([]) == ''

    def test_add_turns_left_reminder(self, prompt_dir):
        pm = PromptManager(prompt_dir)
        msg = Message(role='user', content=[TextContent(text='Hello')])
        state = MagicMock()
        state.iteration_flag.max_value = 10
        state.iteration_flag.current_value = 2

        msgs = [msg]
        pm.add_turns_left_reminder(msgs, state)

        last_content = msgs[0].content[-1]
        assert isinstance(last_content, TextContent)
        assert '8 turns left' in last_content.text


class TestOrchestratorPromptManager:
    def test_active_llm_model_id_uses_resolved_when_set(self, prompt_dir):
        opm = OrchestratorPromptManager(
            prompt_dir, resolved_llm_model_id='openai/gpt-4o'
        )
        assert opm._active_llm_model_id() == 'openai/gpt-4o'

    def test_active_llm_model_id_fallback_from_app_config(self, prompt_dir):
        mock_llm_cfg = MagicMock()
        mock_llm_cfg.model = 'anthropic/claude-sonnet-4-6'
        mock_app_config = MagicMock()
        mock_app_config.get_llm_config_from_agent_config.return_value = mock_llm_cfg
        mock_agent_config = MagicMock()

        opm = OrchestratorPromptManager(
            prompt_dir,
            config=mock_agent_config,
            resolved_llm_model_id='',
            app_config=mock_app_config,
        )
        assert opm._active_llm_model_id() == 'anthropic/claude-sonnet-4-6'
        mock_app_config.get_llm_config_from_agent_config.assert_called_once_with(
            mock_agent_config
        )

    def test_get_system_message_injects_identity(self, prompt_dir):
        opm = OrchestratorPromptManager(prompt_dir)
        msg = opm.get_system_message(name='Test')
        assert 'You are Grinta' in msg
        assert 'You are App' not in msg

    def test_inject_lessons_learned_missing_file(self, prompt_dir, tmp_path):
        # Line 255: return content if file doesn't exist
        opm = OrchestratorPromptManager(prompt_dir)
        content = 'original'
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
            result = opm._inject_lessons_learned(content)
            assert result == content

    def test_inject_lessons_learned_success(self, prompt_dir, tmp_path):
        # Line 260-288 coverage
        opm = OrchestratorPromptManager(prompt_dir)
        content = 'base-prompt'
        lessons = tmp_path / 'lessons.md'
        lessons.write_text('lesson 1', encoding='utf-8')
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
            result = opm._inject_lessons_learned(content)
            assert 'lesson 1' in result
            assert '<REPOSITORY_LESSONS_LEARNED>' in result

    def test_inject_lessons_learned_truncation(self, prompt_dir, tmp_path):
        opm = OrchestratorPromptManager(prompt_dir)
        long_lessons = 'X' * 4000
        lessons = tmp_path / 'lessons.md'
        lessons.write_text(long_lessons, encoding='utf-8')
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
            result = opm._inject_lessons_learned('content')
            assert 'truncated' in result
            assert len(result) < 4000 + 150

    def test_inject_lessons_learned_empty_file(self, prompt_dir, tmp_path):
        opm = OrchestratorPromptManager(prompt_dir)
        lessons = tmp_path / 'lessons.md'
        lessons.write_text('  ', encoding='utf-8')
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
            result = opm._inject_lessons_learned('content')
            assert result == 'content'

    def test_inject_lessons_learned_exception(self, prompt_dir):
        # Line 287-288: except Exception: return content
        opm = OrchestratorPromptManager(prompt_dir)
        with patch(
            'backend.core.workspace_resolution.get_effective_workspace_root',
            side_effect=RuntimeError('disk fail'),
        ):
            result = opm._inject_lessons_learned('content')
            assert result == 'content'

    def test_set_prompt_tier(self, prompt_dir):
        # Line 244-245: self._prompt_tier = tier, and check if debug tier works
        opm = OrchestratorPromptManager(prompt_dir)
        opm.set_prompt_tier('debug')
        assert opm._prompt_tier == 'debug'

        with patch.object(
            opm, '_inject_workspace_memory', return_value='lessons-injected'
        ):
            msg = opm.get_system_message()
            assert 'lessons-injected' in msg

    def test_inject_workspace_memory_exception(self, prompt_dir):
        opm = OrchestratorPromptManager(prompt_dir)
        with patch(
            'backend.engine.tools.workspace_memory.format_prompt_block',
            side_effect=Exception('failed'),
        ):
            result = opm._inject_workspace_memory('content')
            assert result == 'content'

    def test_inject_workspace_memory_success(self, prompt_dir):
        opm = OrchestratorPromptManager(prompt_dir)
        with patch(
            'backend.engine.tools.workspace_memory.format_prompt_block',
            return_value='<WORKSPACE_MEMORY>\n- [lesson] key: note value\n</WORKSPACE_MEMORY>',
        ):
            result = opm._inject_workspace_memory('content')
            assert 'note value' in result
            assert '<WORKSPACE_MEMORY>' in result

    def test_inject_workspace_memory_falls_back_to_lessons_md(
        self, prompt_dir, tmp_path
    ):
        opm = OrchestratorPromptManager(prompt_dir)
        lessons = tmp_path / 'lessons.md'
        lessons.write_text('verified fix for auth', encoding='utf-8')
        with (
            patch(
                'backend.engine.tools.workspace_memory.format_prompt_block',
                return_value='',
            ),
            patch(
                'backend.core.workspace_resolution.get_effective_workspace_root',
                return_value=tmp_path,
            ),
            patch(
                'backend.core.workspace_resolution.workspace_agent_state_dir',
                return_value=tmp_path,
            ),
        ):
            result = opm._inject_workspace_memory('content')
            assert '<WORKSPACE_MEMORY>' in result
            assert 'verified fix for auth' in result


def test_sentinels():
    assert isinstance(UNINITIALIZED_PROMPT_MANAGER, _UninitializedPromptManager)


def test_terminal_helpers_prefer_powershell_when_available_on_windows():
    from backend.utils.terminal import terminal_contract as prompt_mod

    prompt_mod.set_active_tool_registry(None)
    prompt_mod._get_global_tool_registry.cache_clear()
    with (
        patch('backend.utils.terminal.terminal_contract.OS_CAPS') as mock_caps,
        patch(
            'backend.utils.terminal.terminal_contract._runtime_prefers_powershell',
            return_value=True,
        ),
    ):
        mock_caps.is_windows = True
        assert uses_powershell_terminal() is True
        assert get_shell_name() == 'powershell'
        assert get_terminal_tool_name() == 'execute_powershell'
    prompt_mod.set_active_tool_registry(None)
    prompt_mod._get_global_tool_registry.cache_clear()


def test_terminal_helpers_fall_back_to_bash_when_powershell_unavailable_on_windows():
    from backend.utils.terminal import terminal_contract as prompt_mod

    prompt_mod.set_active_tool_registry(None)
    prompt_mod._get_global_tool_registry.cache_clear()
    with (
        patch('backend.utils.terminal.terminal_contract.OS_CAPS') as mock_caps,
        patch(
            'backend.utils.terminal.terminal_contract._runtime_prefers_powershell',
            return_value=False,
        ),
    ):
        mock_caps.is_windows = True
        assert uses_powershell_terminal() is False
        assert get_shell_name() == 'bash'
        assert get_terminal_tool_name() == 'execute_bash'
    prompt_mod.set_active_tool_registry(None)
    prompt_mod._get_global_tool_registry.cache_clear()


def test_python_shell_command_prefers_python3_in_bash_mode():
    with patch(
        'backend.utils.terminal.terminal_contract.uses_powershell_terminal',
        return_value=False,
    ):
        assert get_python_shell_command() == 'python3'


def test_python_shell_command_prefers_python_on_windows():
    with patch(
        'backend.utils.terminal.terminal_contract.uses_powershell_terminal',
        return_value=False,
    ):
        assert get_python_shell_command() == 'python3'


def test_python_shell_command_prefers_python_in_powershell_mode():
    with patch(
        'backend.utils.terminal.terminal_contract.uses_powershell_terminal',
        return_value=True,
    ):
        assert get_python_shell_command() == 'python'


def test_build_python_exec_command_base64_encodes_script():
    with patch(
        'backend.utils.terminal.terminal_contract.uses_powershell_terminal',
        return_value=False,
    ):
        command = build_python_exec_command('print("hello")')

    assert 'python3 -c' in command
    assert 'b64decode' in command
    assert 'print("hello")' not in command


def test_build_python_exec_command_includes_shell_fallbacks_for_bash():
    with patch(
        'backend.utils.terminal.terminal_contract.uses_powershell_terminal',
        return_value=False,
    ):
        command = build_python_exec_command('print("hello")')

    assert 'command -v python3' in command
    assert 'command -v python' in command
    assert 'command -v py' in command
    assert '[MISSING_TOOL] python/python3/py not found in PATH' in command


def test_build_python_exec_command_includes_shell_fallbacks_for_powershell():
    with patch(
        'backend.utils.terminal.terminal_contract.uses_powershell_terminal',
        return_value=True,
    ):
        command = build_python_exec_command('print("hello")')

    assert command.startswith('python -c "import base64;exec')


def test_active_tool_registry_visible_from_worker_thread():
    """Regression: ThreadPoolExecutor workers must see the runtime ToolRegistry."""
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace
    from unittest.mock import MagicMock

    from backend.core.os_capabilities import OS_CAPS, override_os_capabilities
    from backend.utils.terminal import terminal_contract as prompt_mod

    prompt_mod.set_active_tool_registry(None)
    prompt_mod._get_global_tool_registry.cache_clear()
    mock_reg = MagicMock()
    mock_reg.has_bash = True
    mock_reg.has_powershell = True
    prompt_mod.set_active_tool_registry(mock_reg)
    try:

        def read_prefers_powershell():
            return prompt_mod._runtime_prefers_powershell()

        with override_os_capabilities(replace(OS_CAPS, is_windows=True)):
            with ThreadPoolExecutor(max_workers=1) as pool:
                assert pool.submit(read_prefers_powershell).result() is True
    finally:
        prompt_mod.set_active_tool_registry(None)
        prompt_mod._get_global_tool_registry.cache_clear()


def test_build_python_exec_command_matches_active_registry_git_bash_on_windows():
    """Regression: Git Bash-only Windows contract must emit POSIX shell."""
    from unittest.mock import MagicMock

    from backend.utils.terminal import terminal_contract as prompt_mod

    prompt_mod.set_active_tool_registry(None)
    prompt_mod._get_global_tool_registry.cache_clear()
    mock_reg = MagicMock()
    mock_reg.has_bash = True
    mock_reg.has_powershell = False
    prompt_mod.set_active_tool_registry(mock_reg)
    try:
        with patch('backend.utils.terminal.terminal_contract.OS_CAPS') as mock_caps:
            mock_caps.is_windows = True
            command = build_python_exec_command('print("hello")')
        assert 'command -v python3' in command
        assert 'Get-Command' not in command
    finally:
        prompt_mod.set_active_tool_registry(None)
        prompt_mod._get_global_tool_registry.cache_clear()
