"""Tests for backend.memory.prompt_assembly."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.core.enums import RecallType
from backend.core.message import Message, TextContent
from backend.events.observation.agent import PlaybookKnowledge, RecallObservation
from backend.memory.prompt_assembly import (
    _create_repo_info,
    _create_runtime_info,
    _create_conversation_instructions,
    _has_workspace_content,
    filter_agents_in_playbook_obs,
    process_recall_observation,
)
from backend.utils.prompt import ConversationInstructions, RepositoryInfo, RuntimeInfo


# ── helpers ──────────────────────────────────────────────────────────

def _make_obs(**kw) -> RecallObservation:
    """Build a minimal RecallObservation with sensible defaults."""
    defaults = dict(
        recall_type=RecallType.WORKSPACE_CONTEXT,
        content="test",
        repo_name="",
        repo_directory="",
        repo_branch="",
        repo_instructions="",
        runtime_hosts={},
        additional_agent_instructions="",
        playbook_knowledge=[],
        date="2025-01-01",
        custom_secrets_descriptions={},
        conversation_instructions="",
        working_dir="/tmp",
    )
    defaults.update(kw)
    return RecallObservation(**defaults)


def _agent_config(**overrides):
    cfg = MagicMock()
    cfg.enable_prompt_extensions = overrides.get("enable_prompt_extensions", True)
    cfg.disabled_playbooks = overrides.get("disabled_playbooks", [])
    return cfg


def _prompt_manager():
    pm = MagicMock()
    pm.build_workspace_context.return_value = "workspace-ctx"
    pm.build_playbook_info.return_value = "playbook-info"
    pm.build_knowledge_base_info.return_value = "kb-info"
    return pm


# ── _create_repo_info ────────────────────────────────────────────────

class TestCreateRepoInfo:
    def test_with_repo_name(self):
        obs = _make_obs(repo_name="my-repo", repo_directory="/code")
        info = _create_repo_info(obs)
        assert isinstance(info, RepositoryInfo)
        assert info.repo_name == "my-repo"

    def test_both_empty(self):
        obs = _make_obs(repo_name="", repo_directory="")
        assert _create_repo_info(obs) is None


# ── _create_runtime_info ─────────────────────────────────────────────

class TestCreateRuntimeInfo:
    def test_with_hosts(self):
        obs = _make_obs(runtime_hosts={"localhost": 8080})
        info = _create_runtime_info(obs)
        assert isinstance(info, RuntimeInfo)
        assert info.available_hosts == {"localhost": 8080}

    def test_no_hosts(self):
        obs = _make_obs(runtime_hosts={}, additional_agent_instructions="")
        info = _create_runtime_info(obs)
        assert isinstance(info, RuntimeInfo)


# ── _create_conversation_instructions ────────────────────────────────

class TestCreateConversationInstructions:
    def test_with_content(self):
        obs = _make_obs(conversation_instructions="be nice")
        ci = _create_conversation_instructions(obs)
        assert isinstance(ci, ConversationInstructions)
        assert ci.content == "be nice"

    def test_empty(self):
        obs = _make_obs(conversation_instructions="")
        assert _create_conversation_instructions(obs) is None


# ── _has_workspace_content ───────────────────────────────────────────

class TestHasWorkspaceContent:
    def test_all_empty(self):
        assert not _has_workspace_content(None, RuntimeInfo(date=""), "", None, [])

    def test_repo_info(self):
        ri = RepositoryInfo(repo_name="r", repo_directory="/d")
        assert _has_workspace_content(ri, RuntimeInfo(date=""), "", None, [])

    def test_runtime_date(self):
        ri = RuntimeInfo(date="2025-01-01")
        assert _has_workspace_content(None, ri, "", None, [])

    def test_instructions(self):
        assert _has_workspace_content(
            None, RuntimeInfo(date=""), "do stuff", None, []
        )

    def test_agents(self):
        pk = PlaybookKnowledge(name="a", trigger="t", content="c")
        assert _has_workspace_content(None, RuntimeInfo(date=""), "", None, [pk])


# ── process_recall_observation ───────────────────────────────────────

class TestProcessRecallObservation:
    def test_disabled_returns_empty(self):
        obs = _make_obs()
        cfg = _agent_config(enable_prompt_extensions=False)
        assert process_recall_observation(obs, 0, [], cfg, _prompt_manager()) == []

    def test_workspace_context(self):
        obs = _make_obs(repo_name="r", repo_directory="/d", date="2025-01-01")
        cfg = _agent_config()
        pm = _prompt_manager()
        msgs = process_recall_observation(obs, 0, [], cfg, pm)
        assert len(msgs) >= 1
        assert msgs[0].role == "user"
        pm.build_workspace_context.assert_called_once()

    def test_knowledge_with_playbooks(self):
        pk = PlaybookKnowledge(name="p", trigger="t", content="c")
        obs = _make_obs(recall_type=RecallType.KNOWLEDGE, playbook_knowledge=[pk])
        cfg = _agent_config()
        pm = _prompt_manager()
        msgs = process_recall_observation(obs, 0, [], cfg, pm)
        assert len(msgs) >= 1
        pm.build_playbook_info.assert_called_once()

    def test_unknown_recall_type(self):
        obs = _make_obs()
        obs.recall_type = "UNKNOWN_TYPE"
        cfg = _agent_config()
        assert process_recall_observation(obs, 0, [], cfg, _prompt_manager()) == []

    def test_workspace_with_no_content_returns_empty(self):
        obs = _make_obs(
            repo_name="",
            repo_directory="",
            runtime_hosts={},
            date="",
            custom_secrets_descriptions={},
            repo_instructions="",
            conversation_instructions="",
            playbook_knowledge=[],
        )
        cfg = _agent_config()
        assert process_recall_observation(obs, 0, [], cfg, _prompt_manager()) == []


# ── filter_agents_in_playbook_obs ────────────────────────────────────

class TestFilterAgents:
    def test_no_overlap(self):
        pk = PlaybookKnowledge(name="unique", trigger="t", content="c")
        obs = _make_obs(recall_type=RecallType.KNOWLEDGE, playbook_knowledge=[pk])
        result = filter_agents_in_playbook_obs(obs, 1, [])
        assert len(result) == 1

    def test_overlapping_agent_removed(self):
        earlier_pk = PlaybookKnowledge(name="dup", trigger="t", content="c")
        earlier_obs = _make_obs(
            recall_type=RecallType.KNOWLEDGE, playbook_knowledge=[earlier_pk]
        )
        earlier_obs._id = 0

        current_pk = PlaybookKnowledge(name="dup", trigger="t2", content="c2")
        obs = _make_obs(recall_type=RecallType.KNOWLEDGE, playbook_knowledge=[current_pk])
        result = filter_agents_in_playbook_obs(obs, 1, [earlier_obs])
        assert len(result) == 0

    def test_non_knowledge_returns_all(self):
        pk = PlaybookKnowledge(name="a", trigger="t", content="c")
        obs = _make_obs(recall_type=RecallType.WORKSPACE_CONTEXT, playbook_knowledge=[pk])
        result = filter_agents_in_playbook_obs(obs, 0, [])
        assert len(result) == 1
