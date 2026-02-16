"""Tests for backend.instruction.types — Playbook types, enums, and metadata models."""

from __future__ import annotations

from datetime import datetime

from backend.instruction.types import (
    InputMetadata,
    PlaybookContentResponse,
    PlaybookMetadata,
    PlaybookResponse,
    PlaybookType,
)


# ── PlaybookType ─────────────────────────────────────────────────────


class TestPlaybookType:
    def test_values(self):
        assert PlaybookType.KNOWLEDGE.value == "knowledge"
        assert PlaybookType.REPO_KNOWLEDGE.value == "repo"
        assert PlaybookType.TASK.value == "task"

    def test_count(self):
        assert len(PlaybookType) == 3

    def test_str_subclass(self):
        assert isinstance(PlaybookType.TASK, str)
        assert PlaybookType.TASK == "task"


# ── InputMetadata ────────────────────────────────────────────────────


class TestInputMetadata:
    def test_valid(self):
        m = InputMetadata(name="url", description="Repo URL")
        assert m.name == "url"
        assert m.description == "Repo URL"

    def test_roundtrip(self):
        m = InputMetadata(name="x", description="d")
        data = m.model_dump()
        m2 = InputMetadata(**data)
        assert m2.name == m.name
        assert m2.description == m.description


# ── PlaybookMetadata ─────────────────────────────────────────────────


class TestPlaybookMetadata:
    def test_defaults(self):
        m = PlaybookMetadata()
        assert m.name == "default"
        assert m.type == PlaybookType.REPO_KNOWLEDGE
        assert m.version == "1.0.0"
        assert m.agent == "Orchestrator"
        assert m.triggers == []
        assert m.inputs == []
        assert m.mcp_tools is None

    def test_custom(self):
        m = PlaybookMetadata(
            name="debug",
            type=PlaybookType.TASK,
            version="2.0.0",
            agent="CodeAct",
            triggers=["/debug"],
            inputs=[InputMetadata(name="file", description="File path")],
        )
        assert m.name == "debug"
        assert m.type == PlaybookType.TASK
        assert len(m.inputs) == 1
        assert m.triggers == ["/debug"]

    def test_roundtrip(self):
        m = PlaybookMetadata(name="test", triggers=["hello"])
        data = m.model_dump()
        m2 = PlaybookMetadata(**data)
        assert m2.name == m.name
        assert m2.triggers == m.triggers


# ── PlaybookResponse ─────────────────────────────────────────────────


class TestPlaybookResponse:
    def test_valid(self):
        now = datetime.now()
        r = PlaybookResponse(name="test", path="/playbooks/test.md", created_at=now)
        assert r.name == "test"
        assert r.path == "/playbooks/test.md"
        assert r.created_at == now


# ── PlaybookContentResponse ──────────────────────────────────────────


class TestPlaybookContentResponse:
    def test_defaults(self):
        r = PlaybookContentResponse(content="Hello", path="/p.md")
        assert r.triggers == []
        assert r.vcs_provider is None

    def test_with_triggers(self):
        r = PlaybookContentResponse(
            content="Content",
            path="/p.md",
            triggers=["review", "test"],
            vcs_provider="github",
        )
        assert len(r.triggers) == 2
        assert r.vcs_provider == "github"
