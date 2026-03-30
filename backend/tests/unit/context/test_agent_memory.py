"""Tests for backend.context.agent_memory.Memory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.core.enums import RecallType
from backend.ledger.action.agent import RecallAction
from backend.ledger.observation.agent import PlaybookKnowledge, RecallObservation
from pathlib import Path

from backend.context.agent_memory import Memory, USER_PLAYBOOKS_DIR


# ── helpers ──────────────────────────────────────────────────────────


@pytest.fixture
def mock_event_stream():
    es = MagicMock()
    es.subscribe = MagicMock()
    es.add_event = MagicMock()
    return es


@pytest.fixture
def memory(mock_event_stream):
    with (
        patch.object(Memory, "_load_global_playbooks"),
        patch.object(Memory, "_load_user_playbooks"),
        patch("backend.context.agent_memory.KnowledgeBaseManager"),
    ):
        return Memory(mock_event_stream, sid="test-sid")


# ── __init__ ─────────────────────────────────────────────────────────


class TestMemoryInit:
    def test_creates_with_defaults(self, memory: Memory):
        assert memory.sid == "test-sid"
        assert memory.repository_info is None
        assert memory.runtime_info is None
        assert memory.repo_playbooks == {}
        assert memory.knowledge_playbooks == {}

    def test_subscribes_to_event_stream(self, mock_event_stream):
        with (
            patch.object(Memory, "_load_global_playbooks"),
            patch.object(Memory, "_load_user_playbooks"),
            patch("backend.context.agent_memory.KnowledgeBaseManager"),
        ):
            Memory(mock_event_stream, sid="sub-test")
        mock_event_stream.subscribe.assert_called_once()

    def test_user_playbooks_dir_uses_app_path(self):
        assert USER_PLAYBOOKS_DIR == Path.home() / ".app" / "playbooks"


# ── set_repository_info ──────────────────────────────────────────────


class TestSetRepositoryInfo:
    def test_sets_info(self, memory):
        memory.set_repository_info("repo", "/dir", "main")
        assert memory.repository_info is not None
        assert memory.repository_info.repo_name == "repo"
        assert memory.repository_info.branch_name == "main"

    def test_clears_when_empty(self, memory):
        memory.set_repository_info("repo", "/dir")
        memory.set_repository_info("", "")
        assert memory.repository_info is None


# ── set_conversation_instructions ────────────────────────────────────


class TestSetConversationInstructions:
    def test_sets(self, memory):
        memory.set_conversation_instructions("be helpful")
        assert memory.conversation_instructions.content == "be helpful"

    def test_none_wraps_as_empty(self, memory):
        memory.set_conversation_instructions(None)
        assert memory.conversation_instructions.content == ""


# ── set_runtime_info ─────────────────────────────────────────────────


class TestSetRuntimeInfo:
    def test_with_web_hosts(self, memory):
        runtime = MagicMock()
        runtime.web_hosts = {"localhost": 3000}
        runtime.additional_agent_instructions = ""
        memory.set_runtime_info(runtime, {"KEY": "desc"}, "/work")
        assert memory.runtime_info is not None
        assert memory.runtime_info.available_hosts == {"localhost": 3000}

    def test_without_web_hosts(self, memory):
        runtime = MagicMock()
        runtime.web_hosts = {}
        runtime.additional_agent_instructions = None
        memory.set_runtime_info(runtime, {}, "/w")
        assert memory.runtime_info is not None
        assert memory.runtime_info.date  # should have today's date

    def test_runtime_info_fields_virtualize_app_workspace_dir(self, memory):
        runtime = MagicMock()
        runtime.web_hosts = {}
        runtime.additional_agent_instructions = None
        memory.set_runtime_info(runtime, {}, "/tmp/app_workspace_test_sid_123")

        fields = memory._get_runtime_info_fields()

        assert fields["working_dir"] == "/workspace"


# ── _is_transient_error ──────────────────────────────────────────────


class TestIsTransientError:
    def test_timeout(self):
        assert Memory._is_transient_error(TimeoutError("timed out"))

    def test_connection(self):
        assert Memory._is_transient_error(ConnectionError("reset"))

    def test_message_match(self):
        assert Memory._is_transient_error(RuntimeError("rate limit exceeded"))

    def test_permanent(self):
        assert not Memory._is_transient_error(ValueError("bad args"))


# ── _should_create_recall_observation ────────────────────────────────


class TestShouldCreateRecallObservation:
    def test_has_repo_info(self, memory):
        memory.set_repository_info("repo", "/dir")
        assert memory._should_create_recall_observation("", [])

    def test_has_instructions(self, memory):
        assert memory._should_create_recall_observation("do this", [])

    def test_has_playbooks(self, memory):
        pk = PlaybookKnowledge(name="p", trigger="t", content="c")
        assert memory._should_create_recall_observation("", [pk])

    def test_nothing(self, memory):
        assert not memory._should_create_recall_observation("", [])


# ── _find_playbook_knowledge ─────────────────────────────────────────


class TestFindPlaybookKnowledge:
    def test_empty_query(self, memory):
        assert memory._find_playbook_knowledge("") == []

    def test_matching_trigger(self, memory):
        mock_pb = MagicMock()
        mock_pb.name = "test_pb"
        mock_pb.match_trigger.return_value = "kw"
        mock_pb.content = "do stuff"
        memory.knowledge_playbooks["test_pb"] = mock_pb
        result = memory._find_playbook_knowledge("search kw here")
        assert len(result) == 1
        assert result[0].name == "test_pb"

    def test_no_match(self, memory):
        mock_pb = MagicMock()
        mock_pb.match_trigger.return_value = None
        memory.knowledge_playbooks["x"] = mock_pb
        assert memory._find_playbook_knowledge("nothing") == []


# ── _on_workspace_context_recall ─────────────────────────────────────


class TestOnWorkspaceContextRecall:
    def test_returns_observation(self, memory):
        memory.set_repository_info("r", "/d")
        action = MagicMock(spec=RecallAction)
        action.recall_type = RecallType.WORKSPACE_CONTEXT
        action.query = ""
        obs = memory._on_workspace_context_recall(action)
        assert isinstance(obs, RecallObservation)
        assert obs.recall_type == RecallType.WORKSPACE_CONTEXT

    def test_returns_empty_observation_when_nothing(self, memory):
        action = MagicMock(spec=RecallAction)
        action.recall_type = RecallType.WORKSPACE_CONTEXT
        action.query = ""
        result = memory._on_workspace_context_recall(action)
        assert isinstance(result, RecallObservation)
        assert result.recall_type == RecallType.WORKSPACE_CONTEXT
        assert result.repo_instructions == ""
        assert result.playbook_knowledge == []


# ── _on_playbook_recall ──────────────────────────────────────────────


class TestOnPlaybookRecall:
    def test_empty_query_returns_empty_success(self, memory):
        action = MagicMock(spec=RecallAction)
        action.recall_type = RecallType.KNOWLEDGE
        action.query = ""
        memory._kb_manager.search = MagicMock(return_value=[])
        obs = memory._on_playbook_recall(action)
        assert isinstance(obs, RecallObservation)
        assert obs.recall_type == RecallType.KNOWLEDGE
        assert obs.playbook_knowledge == []
        assert obs.knowledge_base_results == []

    def test_no_match_returns_empty_success(self, memory):
        action = MagicMock(spec=RecallAction)
        action.recall_type = RecallType.KNOWLEDGE
        action.query = "plain user question with no playbook trigger"
        memory._kb_manager.search = MagicMock(return_value=[])
        obs = memory._on_playbook_recall(action)
        assert isinstance(obs, RecallObservation)
        assert obs.playbook_knowledge == []


# ── get_playbook_mcp_tools ───────────────────────────────────────────


class TestGetPlaybookMcpTools:
    def test_empty(self, memory):
        assert memory.get_playbook_mcp_tools() == []

    def test_has_tools(self, memory):
        mock_pb = MagicMock()
        mock_pb.metadata.mcp_tools = MagicMock()
        mock_pb.name = "pb1"
        memory.repo_playbooks["pb1"] = mock_pb
        tools = memory.get_playbook_mcp_tools()
        assert len(tools) == 1


# ── load_user_workspace_playbooks ────────────────────────────────────


class TestLoadUserWorkspacePlaybooks:
    def test_loads_both_types(self, memory):
        from backend.playbooks.engine import KnowledgePlaybook, RepoPlaybook

        repo_pb = MagicMock(spec=RepoPlaybook)
        repo_pb.name = "repo_pb"
        knowledge_pb = MagicMock(spec=KnowledgePlaybook)
        knowledge_pb.name = "know_pb"

        # load_user_workspace_playbooks does isinstance checks using local imports
        memory.load_user_workspace_playbooks([repo_pb, knowledge_pb])

        assert "repo_pb" in memory.repo_playbooks
        assert "know_pb" in memory.knowledge_playbooks
