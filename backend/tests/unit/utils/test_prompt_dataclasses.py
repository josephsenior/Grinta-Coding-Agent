"""Tests for backend.utils.prompt — Prompt-related dataclasses and PromptManager."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from backend.core.message import Message, TextContent
from backend.utils.prompt import (
    UNINITIALIZED_PROMPT_MANAGER,
    ConversationInstructions,
    OrchestratorPromptManager,
    PromptManager,
    RepositoryInfo,
    RuntimeInfo,
    _UninitializedPromptManager,
)


# ── RuntimeInfo dataclass ────────────────────────────────────────────


class TestRuntimeInfo:
    def test_defaults(self):
        info = RuntimeInfo(date="2024-01-01")
        assert info.date == "2024-01-01"
        assert info.available_hosts == {}
        assert info.additional_agent_instructions == ""
        assert info.custom_secrets_descriptions == {}
        assert info.working_dir == ""

    def test_custom_fields(self):
        info = RuntimeInfo(
            date="2024-06-15",
            available_hosts={"localhost": 3000},
            additional_agent_instructions="Be concise",
            custom_secrets_descriptions={"API_KEY": "Main API key"},
            working_dir="/workspace",
        )
        assert info.available_hosts == {"localhost": 3000}
        assert info.additional_agent_instructions == "Be concise"
        assert info.custom_secrets_descriptions == {"API_KEY": "Main API key"}
        assert info.working_dir == "/workspace"


# ── RepositoryInfo dataclass ─────────────────────────────────────────


class TestRepositoryInfo:
    def test_defaults(self):
        info = RepositoryInfo()
        assert info.repo_name is None
        assert info.repo_directory is None
        assert info.branch_name is None

    def test_custom_fields(self):
        info = RepositoryInfo(
            repo_name="my-repo",
            repo_directory="/home/user/my-repo",
            branch_name="feature-branch",
        )
        assert info.repo_name == "my-repo"
        assert info.branch_name == "feature-branch"


# ── ConversationInstructions dataclass ───────────────────────────────


class TestConversationInstructions:
    def test_defaults(self):
        ci = ConversationInstructions()
        assert ci.content == ""

    def test_custom(self):
        ci = ConversationInstructions(content="Follow GitHub issue #42")
        assert ci.content == "Follow GitHub issue #42"


# ── _UninitializedPromptManager sentinel ─────────────────────────────


class TestUninitializedPromptManager:
    def test_singleton(self):
        assert isinstance(UNINITIALIZED_PROMPT_MANAGER, _UninitializedPromptManager)

    def test_class_instantiation(self):
        sentinel = _UninitializedPromptManager()
        assert sentinel is not None


# ── PromptManager.__init__ ───────────────────────────────────────────


class TestPromptManagerInit:
    def test_none_dir_raises(self):
        with pytest.raises(ValueError, match="Prompt directory is not set"):
            PromptManager(prompt_dir=None)

    def test_missing_template_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(FileNotFoundError, match="not found"):
                PromptManager(prompt_dir=tmpdir)

    def test_valid_dir_loads(self):
        """PromptManager loads if all required templates exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in [
                "system_prompt.j2",
                "user_prompt.j2",
                "additional_info.j2",
                "playbook_info.j2",
                "knowledge_base_info.j2",
            ]:
                with open(os.path.join(tmpdir, name), "w", encoding="utf-8") as f:
                    f.write("{{ content }}")

            pm = PromptManager(prompt_dir=tmpdir)
            assert pm.prompt_dir == tmpdir
            assert pm.system_template is not None
            assert pm.user_template is not None

    def test_custom_system_prompt(self):
        """PromptManager loads a custom system_prompt filename."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in [
                "custom.j2",
                "user_prompt.j2",
                "additional_info.j2",
                "playbook_info.j2",
                "knowledge_base_info.j2",
            ]:
                with open(os.path.join(tmpdir, name), "w", encoding="utf-8") as f:
                    f.write("custom")

            pm = PromptManager(prompt_dir=tmpdir, system_prompt_filename="custom.j2")
            assert pm.system_template is not None


# ── PromptManager template rendering ─────────────────────────────────


class TestPromptManagerRendering:
    @pytest.fixture
    def pm(self, tmp_path):
        """Fixture providing a PromptManager with minimal templates."""
        (tmp_path / "system_prompt.j2").write_text("System: {{ msg }}")
        (tmp_path / "user_prompt.j2").write_text("User example")
        (tmp_path / "additional_info.j2").write_text(
            "Repo: {{ repository_info.repo_name if repository_info else 'none' }}"
        )
        (tmp_path / "playbook_info.j2").write_text(
            "Agents: {{ triggered_agents|length }}"
        )
        (tmp_path / "knowledge_base_info.j2").write_text("KB: {{ kb_results|length }}")
        return PromptManager(prompt_dir=str(tmp_path))

    def test_get_example_user_message(self, pm):
        assert pm.get_example_user_message() == "User example"

    def test_build_workspace_context(self, pm):
        repo = RepositoryInfo(repo_name="my-repo")
        result = pm.build_workspace_context(
            repository_info=repo,
            runtime_info=None,
            conversation_instructions=None,
        )
        assert "my-repo" in result

    def test_build_workspace_context_none(self, pm):
        result = pm.build_workspace_context(
            repository_info=None,
            runtime_info=None,
            conversation_instructions=None,
        )
        assert "none" in result

    def test_build_playbook_info(self, pm):
        result = pm.build_playbook_info(triggered_agents=["a", "b"])
        assert "2" in result

    def test_build_knowledge_base_info(self, pm):
        result = pm.build_knowledge_base_info(kb_results=[1, 2, 3])
        assert "3" in result


class TestPromptManagerTurnsReminder:
    def test_add_turns_left_reminder(self, tmp_path):
        """Test turns left reminder is appended to user message."""
        (tmp_path / "system_prompt.j2").write_text("S")
        (tmp_path / "user_prompt.j2").write_text("U")
        (tmp_path / "additional_info.j2").write_text("A")
        (tmp_path / "playbook_info.j2").write_text("P")
        (tmp_path / "knowledge_base_info.j2").write_text("K")
        pm = PromptManager(prompt_dir=str(tmp_path))

        msg = Message(role="user", content=[TextContent(text="Help me")])
        messages = [msg]

        state = MagicMock()
        state.iteration_flag.max_value = 10
        state.iteration_flag.current_value = 3

        pm.add_turns_left_reminder(messages, state)

        assert len(msg.content) == 2
        assert "7 turns left" in msg.content[1].text


class TestOrchestratorPromptManager:
    @pytest.fixture
    def pm(self, tmp_path):
        """Fixture providing OrchestratorPromptManager with minimal templates."""
        (tmp_path / "system_prompt.j2").write_text("System: {{ msg }}")
        (tmp_path / "user_prompt.j2").write_text("User")
        (tmp_path / "additional_info.j2").write_text("Info")
        (tmp_path / "playbook_info.j2").write_text("Playbook")
        (tmp_path / "knowledge_base_info.j2").write_text("KB")
        return OrchestratorPromptManager(prompt_dir=str(tmp_path))

    def test_get_system_message_injects_identity(self, pm):
        """Test system message has identity prefix."""
        with patch(
            "backend.utils.prompt.OrchestratorPromptManager._inject_scratchpad",
            side_effect=lambda x: x,
        ):
            result = pm.get_system_message(msg="hello")
            assert "You are Forge agent." in result
            assert "System: hello" in result

    def test_get_system_message_with_config(self, pm):
        """Test system message with config injects context."""
        config = MagicMock()
        config.cli_mode = True
        pm._config = config
        with patch(
            "backend.utils.prompt.OrchestratorPromptManager._inject_scratchpad",
            side_effect=lambda x: x,
        ):
            result = pm.get_system_message(msg="hi")
            assert "You are Forge agent." in result

    def test_inject_scratchpad_success(self, pm):
        """Test scratchpad injection when notes exist."""
        with patch("backend.engines.orchestrator.tools.note._load_notes") as mock_load:
            mock_load.return_value = {"todo": "buy milk"}
            content = "Original content"
            result = pm._inject_scratchpad(content)
            assert "Original content" in result
            assert "<WORKING_SCRATCHPAD>" in result
            assert "[todo]: buy milk" in result

    def test_inject_scratchpad_no_notes(self, pm):
        """Test scratchpad injection when no notes exist."""
        with patch("backend.engines.orchestrator.tools.note._load_notes") as mock_load:
            mock_load.return_value = {}
            content = "Original content"
            result = pm._inject_scratchpad(content)
            assert result == content

    def test_inject_scratchpad_exception(self, pm):
        """Test scratchpad injection handles exceptions."""
        with patch(
            "backend.engines.orchestrator.tools.note._load_notes",
            side_effect=Exception("Crash"),
        ):
            content = "Original content"
            result = pm._inject_scratchpad(content)
            assert result == content
