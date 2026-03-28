"""Tests for backend.utils.prompt module — data classes and PromptManager basics."""

from unittest.mock import MagicMock, patch

import pytest


class TestRuntimeInfo:
    def test_defaults(self):
        from backend.utils.prompt import RuntimeInfo

        ri = RuntimeInfo(date="2024-01-01")
        assert ri.date == "2024-01-01"
        assert ri.available_hosts == {}
        assert ri.additional_agent_instructions == ""
        assert ri.custom_secrets_descriptions == {}
        assert ri.working_dir == ""

    def test_with_values(self):
        from backend.utils.prompt import RuntimeInfo

        ri = RuntimeInfo(
            date="2024-06-15",
            available_hosts={"localhost": 3000},
            additional_agent_instructions="Be concise",
            working_dir="/workspace",
        )
        assert ri.available_hosts == {"localhost": 3000}
        assert ri.additional_agent_instructions == "Be concise"
        assert ri.working_dir == "/workspace"


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
            repo_name="forge", repo_directory="/repos/forge", branch_name="main"
        )
        assert ri.repo_name == "forge"
        assert ri.repo_directory == "/repos/forge"
        assert ri.branch_name == "main"


class TestConversationInstructions:
    def test_defaults(self):
        from backend.utils.prompt import ConversationInstructions

        ci = ConversationInstructions()
        assert ci.content == ""

    def test_with_content(self):
        from backend.utils.prompt import ConversationInstructions

        ci = ConversationInstructions(content="Respond to GitHub issue #1234")
        assert ci.content == "Respond to GitHub issue #1234"


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

        with pytest.raises(ValueError, match="Prompt directory is not set"):
            PromptManager(prompt_dir=None)

    def test_missing_template_raises(self, tmp_path):
        from backend.utils.prompt import PromptManager

        with pytest.raises(FileNotFoundError):
            PromptManager(prompt_dir=str(tmp_path))

    def test_valid_templates_load(self, tmp_path):
        from backend.utils.prompt import PromptManager

        # Create minimal template files
        for name in [
            "system_prompt.j2",
            "user_prompt.j2",
            "additional_info.j2",
            "playbook_info.j2",
            "knowledge_base_info.j2",
        ]:
            (tmp_path / name).write_text("{{ content }}", encoding="utf-8")

        pm = PromptManager(prompt_dir=str(tmp_path))
        assert pm.prompt_dir == str(tmp_path)
        assert pm.system_template is not None
        assert pm.user_template is not None

    @patch(
        "backend.engine.tools.prompt.refine_prompt",
        side_effect=lambda x: x,
    )
    def test_get_system_message(self, mock_refine, tmp_path):
        from backend.utils.prompt import PromptManager

        for name in [
            "system_prompt.j2",
            "user_prompt.j2",
            "additional_info.j2",
            "playbook_info.j2",
            "knowledge_base_info.j2",
        ]:
            (tmp_path / name).write_text("Hello {{ name }}", encoding="utf-8")

        pm = PromptManager(prompt_dir=str(tmp_path))
        result = pm.get_system_message(name="World")
        assert "Hello World" in result

    def test_get_example_user_message(self, tmp_path):
        from backend.utils.prompt import PromptManager

        for name in [
            "system_prompt.j2",
            "user_prompt.j2",
            "additional_info.j2",
            "playbook_info.j2",
            "knowledge_base_info.j2",
        ]:
            content = "User prompt content" if name == "user_prompt.j2" else "x"
            (tmp_path / name).write_text(content, encoding="utf-8")

        pm = PromptManager(prompt_dir=str(tmp_path))
        result = pm.get_example_user_message()
        assert result == "User prompt content"

    def test_build_workspace_context(self, tmp_path):
        from backend.utils.prompt import (
            ConversationInstructions,
            PromptManager,
            RepositoryInfo,
            RuntimeInfo,
        )

        for name in [
            "system_prompt.j2",
            "user_prompt.j2",
            "additional_info.j2",
            "playbook_info.j2",
            "knowledge_base_info.j2",
        ]:
            content = (
                "repo={{ repository_info.repo_name }}"
                if name == "additional_info.j2"
                else "x"
            )
            (tmp_path / name).write_text(content, encoding="utf-8")

        pm = PromptManager(prompt_dir=str(tmp_path))
        result = pm.build_workspace_context(
            repository_info=RepositoryInfo(repo_name="myrepo"),
            runtime_info=RuntimeInfo(date="2024-01-01"),
            conversation_instructions=ConversationInstructions(),
        )
        assert "myrepo" in result


class TestOrchestratorPromptManager:
    @patch(
        "backend.engine.tools.prompt.refine_prompt",
        side_effect=lambda x: x,
    )
    def test_identity_prefix_added(self, mock_refine, tmp_path):
        from backend.utils.prompt import OrchestratorPromptManager

        for name in [
            "system_prompt.j2",
            "user_prompt.j2",
            "additional_info.j2",
            "playbook_info.j2",
            "knowledge_base_info.j2",
        ]:
            (tmp_path / name).write_text("Prompt body", encoding="utf-8")

        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path))
        result = opm.get_system_message()
        assert result.startswith("You are Forge agent.")

    @patch(
        "backend.engine.tools.prompt.refine_prompt",
        side_effect=lambda x: x,
    )
    def test_identity_prefix_not_duplicated(self, mock_refine, tmp_path):
        from backend.utils.prompt import OrchestratorPromptManager

        for name in [
            "system_prompt.j2",
            "user_prompt.j2",
            "additional_info.j2",
            "playbook_info.j2",
            "knowledge_base_info.j2",
        ]:
            (tmp_path / name).write_text(
                "You are Forge agent.\nMore content", encoding="utf-8"
            )

        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path))
        result = opm.get_system_message()
        assert result.count("You are Forge agent.") == 1

    @patch(
        "backend.engine.tools.prompt.refine_prompt",
        side_effect=lambda x: x,
    )
    def test_config_injected(self, mock_refine, tmp_path):
        from backend.utils.prompt import OrchestratorPromptManager

        for name in [
            "system_prompt.j2",
            "user_prompt.j2",
            "additional_info.j2",
            "playbook_info.j2",
            "knowledge_base_info.j2",
        ]:
            (tmp_path / name).write_text("cli={{ cli_mode }}", encoding="utf-8")

        mock_config = MagicMock()
        mock_config.cli_mode = True
        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path), config=mock_config)
        result = opm.get_system_message()
        assert "cli=True" in result

    def test_build_playbook_info(self, tmp_path):
        from backend.utils.prompt import PromptManager

        for name in ["system_prompt.j2", "user_prompt.j2", "additional_info.j2",
                    "playbook_info.j2", "knowledge_base_info.j2"]:
            (tmp_path / name).write_text("playbook={{ triggered_agents[0].name }}", encoding="utf-8")

        pm = PromptManager(prompt_dir=str(tmp_path))
        mock_agent = MagicMock()
        mock_agent.name = "test_playbook"
        result = pm.build_playbook_info([mock_agent])
        assert "test_playbook" in result

    def test_build_knowledge_base_info(self, tmp_path):
        from backend.utils.prompt import PromptManager

        for name in ["system_prompt.j2", "user_prompt.j2", "additional_info.j2",
                    "playbook_info.j2", "knowledge_base_info.j2"]:
            (tmp_path / name).write_text("kb={{ kb_results[0].content }}", encoding="utf-8")

        pm = PromptManager(prompt_dir=str(tmp_path))
        mock_result = MagicMock()
        mock_result.content = "kb_content"
        result = pm.build_knowledge_base_info([mock_result])
        assert "kb_content" in result

    def test_add_turns_left_reminder(self, tmp_path):
        from backend.core.message import Message, TextContent
        from backend.utils.prompt import PromptManager

        # Need valid templates even if we don't render them for this specific test
        # because __init__ loads them.
        for name in ["system_prompt.j2", "user_prompt.j2", "additional_info.j2",
                    "playbook_info.j2", "knowledge_base_info.j2"]:
            (tmp_path / name).write_text("x", encoding="utf-8")

        pm = PromptManager(prompt_dir=str(tmp_path))
        msg = Message(role="user", content=[TextContent(text="Hello")])
        mock_state = MagicMock()
        mock_state.iteration_flag.max_value = 10
        mock_state.iteration_flag.current_value = 2

        pm.add_turns_left_reminder([msg], mock_state)

        last_content = msg.content[-1]
        assert isinstance(last_content, TextContent)
        assert "8 turns left" in last_content.text

    @patch("backend.engine.tools.prompt.refine_prompt", side_effect=lambda x: x)
    def test_inject_lessons_learned(self, mock_refine, tmp_path):
        from backend.utils.prompt import OrchestratorPromptManager

        for name in ["system_prompt.j2", "user_prompt.j2", "additional_info.j2",
                    "playbook_info.j2", "knowledge_base_info.j2"]:
            (tmp_path / name).write_text("body", encoding="utf-8")

        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path))
        opm.set_prompt_tier("debug")

        with patch(
            "backend.core.workspace_resolution.get_effective_workspace_root",
            return_value=tmp_path,
        ):
            # Test missing lessons file
            result = opm.get_system_message()
            assert "REPOSITORY_LESSONS_LEARNED" not in result

            # Test existing lessons file
            lessons_dir = tmp_path / ".Forge"
            lessons_dir.mkdir(exist_ok=True)
            lessons_file = lessons_dir / "lessons.md"
            lessons_file.write_text("Always test your code.", encoding="utf-8")

            result = opm.get_system_message()
            assert "REPOSITORY_LESSONS_LEARNED" in result
            assert "Always test your code." in result

    @patch("backend.engine.tools.prompt.refine_prompt", side_effect=lambda x: x)
    def test_inject_scratchpad(self, mock_refine, tmp_path):
        from backend.utils.prompt import OrchestratorPromptManager

        for name in ["system_prompt.j2", "user_prompt.j2", "additional_info.j2",
                    "playbook_info.j2", "knowledge_base_info.j2"]:
            (tmp_path / name).write_text("body", encoding="utf-8")

        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path))

        with patch(
            "backend.engine.tools.note.scratchpad_entries_for_prompt",
            return_value=[("key", "val")],
        ), patch(
            "backend.engine.tools.working_memory.get_working_memory_prompt_block",
            return_value="",
        ):
            result = opm.get_system_message()
            assert "WORKING_SCRATCHPAD" in result
            assert "[key]: val" in result
