"""Unit tests for backend.utils.prompt — Prompt management and template rendering."""

import pytest
from unittest.mock import MagicMock, patch

from backend.utils.prompt import (
    PromptManager,
    OrchestratorPromptManager,
    UNINITIALIZED_PROMPT_MANAGER,
    _UninitializedPromptManager
)
from backend.core.message import Message, TextContent

@pytest.fixture
def prompt_dir(tmp_path):
    d = tmp_path / "prompts"
    d.mkdir()
    (d / "system_prompt.j2").write_text("System: {{ name }}", encoding="utf-8")
    (d / "user_prompt.j2").write_text("User prompt", encoding="utf-8")
    (d / "additional_info.j2").write_text("Addon: {{ repository_instructions }}", encoding="utf-8")
    (d / "playbook_info.j2").write_text("Playbook", encoding="utf-8")
    (d / "knowledge_base_info.j2").write_text("KB", encoding="utf-8")
    return str(d)

class TestPromptManager:
    def test_init_raises_if_no_dir(self):
        with pytest.raises(ValueError, match="Prompt directory is not set"):
            PromptManager(None)

    def test_load_template_missing_raises(self, prompt_dir):
        pm = PromptManager(prompt_dir)
        # Line 141 coverage: raise FileNotFoundError(msg) from e
        with pytest.raises(FileNotFoundError, match="not found"):
            pm._load_template("nonexistent.j2")

    def test_get_system_message(self, prompt_dir):
        with patch("backend.engines.orchestrator.tools.prompt.refine_prompt", side_effect=lambda x: x):
            pm = PromptManager(prompt_dir)
            msg = pm.get_system_message(name="Forge")
            assert msg == "System: Forge"

    def test_get_example_user_message(self, prompt_dir):
        pm = PromptManager(prompt_dir)
        assert pm.get_example_user_message() == "User prompt"

    def test_build_workspace_context(self, prompt_dir):
        pm = PromptManager(prompt_dir)
        ctx = pm.build_workspace_context(None, None, None, repo_instructions="test-repo")
        assert ctx == "Addon: test-repo"

    def test_build_playbook_info(self, prompt_dir):
        pm = PromptManager(prompt_dir)
        assert pm.build_playbook_info([]) == "Playbook"

    def test_build_knowledge_base_info(self, prompt_dir):
        pm = PromptManager(prompt_dir)
        assert pm.build_knowledge_base_info([]) == "KB"

    def test_add_turns_left_reminder(self, prompt_dir):
        pm = PromptManager(prompt_dir)
        msg = Message(role="user", content=[TextContent(text="Hello")])
        state = MagicMock()
        state.iteration_flag.max_value = 10
        state.iteration_flag.current_value = 2
        
        msgs = [msg]
        pm.add_turns_left_reminder(msgs, state)
        
        last_content = msgs[0].content[-1]
        assert isinstance(last_content, TextContent)
        assert "8 turns left" in last_content.text

class TestOrchestratorPromptManager:
    def test_get_system_message_injects_identity(self, prompt_dir):
        with patch("backend.engines.orchestrator.tools.prompt.refine_prompt", side_effect=lambda x: x):
            opm = OrchestratorPromptManager(prompt_dir)
            # Should have "You are Forge agent." prefix
            msg = opm.get_system_message(name="Test")
            assert msg.startswith("You are Forge agent.\nSystem: Test")

    def test_inject_lessons_learned_missing_file(self, prompt_dir):
        # Line 255: return content if file doesn't exist
        opm = OrchestratorPromptManager(prompt_dir)
        content = "original"
        with patch("os.path.exists", return_value=False):
            result = opm._inject_lessons_learned(content)
            assert result == content

    def test_inject_lessons_learned_success(self, prompt_dir):
        # Line 260-288 coverage
        opm = OrchestratorPromptManager(prompt_dir)
        content = "base-prompt"
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", MagicMock()) as mock_file:
            # Setup the context manager behavior for open()
            mock_file.return_value.__enter__.return_value.read.return_value = "lesson 1"
            result = opm._inject_lessons_learned(content)
            assert "lesson 1" in result
            assert "<REPOSITORY_LESSONS_LEARNED>" in result

    def test_inject_lessons_learned_truncation(self, prompt_dir):
        opm = OrchestratorPromptManager(prompt_dir)
        long_lessons = "X" * 4000
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", MagicMock()) as mock_file:
            mock_file.return_value.__enter__.return_value.read.return_value = long_lessons
            result = opm._inject_lessons_learned("content")
            assert "truncated" in result
            assert len(result) < 4000 + 150

    def test_inject_lessons_learned_empty_file(self, prompt_dir):
        opm = OrchestratorPromptManager(prompt_dir)
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", MagicMock()) as mock_file:
            mock_file.return_value.__enter__.return_value.read.return_value = "  "
            result = opm._inject_lessons_learned("content")
            assert result == "content"

    def test_inject_lessons_learned_exception(self, prompt_dir):
        # Line 287-288: except Exception: return content
        opm = OrchestratorPromptManager(prompt_dir)
        with patch("os.path.exists", side_effect=RuntimeError("disk fail")):
            result = opm._inject_lessons_learned("content")
            assert result == "content"

    def test_set_prompt_tier(self, prompt_dir):
        # Line 244-245: self._prompt_tier = tier, and check if debug tier works
        with patch("backend.engines.orchestrator.tools.prompt.refine_prompt", side_effect=lambda x: x):
            opm = OrchestratorPromptManager(prompt_dir)
            opm.set_prompt_tier("debug")
            assert opm._prompt_tier == "debug"
            
            with patch.object(opm, "_inject_lessons_learned", return_value="lessons-injected"):
                msg = opm.get_system_message()
                assert "lessons-injected" in msg

    def test_inject_scratchpad_exception(self, prompt_dir):
        # Line 303-304: except Exception: return content
        opm = OrchestratorPromptManager(prompt_dir)
        with patch("backend.engines.orchestrator.tools.note._load_notes", side_effect=Exception("failed")):
            result = opm._inject_scratchpad("content")
            assert result == "content"

    def test_inject_scratchpad_success(self, prompt_dir):
        opm = OrchestratorPromptManager(prompt_dir)
        with patch("backend.engines.orchestrator.tools.note._load_notes", return_value={"key": "note value"}):
            result = opm._inject_scratchpad("content")
            assert "[key]: note value" in result
            assert "<WORKING_SCRATCHPAD>" in result

def test_sentinels():
    assert isinstance(UNINITIALIZED_PROMPT_MANAGER, _UninitializedPromptManager)
