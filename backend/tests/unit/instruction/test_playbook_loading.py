"""Tests for backend.instruction.playbook — Playbook loading logic."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.exceptions import PlaybookValidationError
from backend.instruction.playbook import (
    BasePlaybook,
    KnowledgePlaybook,
    RepoPlaybook,
    TaskPlaybook,
    _collect_markdown_files,
    _collect_special_files,
    _finalize_loaded_playbook,
    _infer_playbook_type,
)
from backend.instruction.types import InputMetadata, PlaybookMetadata, PlaybookType


# ── _finalize_loaded_playbook ────────────────────────────────────────


class TestFinalizeLoadedPlaybook:
    def test_valid_metadata(self):
        m = _finalize_loaded_playbook({"name": "test"}, Path("test.md"))
        assert isinstance(m, PlaybookMetadata)
        assert m.name == "test"

    def test_version_coerced_to_string(self):
        m = _finalize_loaded_playbook({"version": 1.0}, Path("t.md"))
        assert m.version == "1.0"

    def test_invalid_type_raises(self):
        with pytest.raises(PlaybookValidationError, match="Invalid"):
            _finalize_loaded_playbook({"type": "bad_type"}, Path("t.md"))


# ── _infer_playbook_type ────────────────────────────────────────────


class TestInferPlaybookType:
    def test_task_when_inputs(self):
        meta = PlaybookMetadata(
            name="build",
            inputs=[InputMetadata(name="x", description="d")],
        )
        result = _infer_playbook_type(meta)
        assert result == PlaybookType.TASK
        assert f"/{meta.name}" in meta.triggers

    def test_knowledge_when_triggers(self):
        meta = PlaybookMetadata(triggers=["review"])
        result = _infer_playbook_type(meta)
        assert result == PlaybookType.KNOWLEDGE

    def test_repo_when_neither(self):
        meta = PlaybookMetadata()
        result = _infer_playbook_type(meta)
        assert result == PlaybookType.REPO_KNOWLEDGE

    def test_task_trigger_not_duplicated(self):
        meta = PlaybookMetadata(
            name="build",
            triggers=["/build"],
            inputs=[InputMetadata(name="x", description="d")],
        )
        _infer_playbook_type(meta)
        assert meta.triggers.count("/build") == 1

    def test_task_trigger_appended_when_different(self):
        meta = PlaybookMetadata(
            name="build",
            triggers=["other"],
            inputs=[InputMetadata(name="x", description="d")],
        )
        _infer_playbook_type(meta)
        assert "/build" in meta.triggers
        assert "other" in meta.triggers


# ── BasePlaybook._handle_third_party ─────────────────────────────────


class TestHandleThirdParty:
    def test_cursorrules(self):
        result = BasePlaybook._handle_third_party(Path(".cursorrules"), "content")
        assert result is not None
        assert isinstance(result, RepoPlaybook)
        assert result.name == "cursorrules"

    def test_agents_md(self):
        result = BasePlaybook._handle_third_party(Path("agents.md"), "content")
        assert result is not None
        assert result.name == "agents"

    def test_agent_md(self):
        result = BasePlaybook._handle_third_party(Path("agent.md"), "content")
        assert result is not None
        assert result.name == "agents"

    def test_unknown_returns_none(self):
        result = BasePlaybook._handle_third_party(Path("readme.md"), "content")
        assert result is None


# ── BasePlaybook._derive_playbook_name ───────────────────────────────


class TestDerivePlaybookName:
    def test_relative_path(self, tmp_path):
        pb_dir = tmp_path / "playbooks"
        pb_dir.mkdir()
        pb_file = pb_dir / "sub" / "test.md"
        pb_file.parent.mkdir()
        pb_file.touch()
        name = BasePlaybook._derive_playbook_name(pb_file, pb_dir)
        assert name == "sub/test"

    def test_third_party_name(self):
        name = BasePlaybook._derive_playbook_name(
            Path(".cursorrules"), Path("/playbooks")
        )
        assert name == "cursorrules"

    def test_unrelated_path_fallback(self):
        name = BasePlaybook._derive_playbook_name(
            Path("/a/b/c.md"), Path("/x/y/z")
        )
        # Should return something via os.path.relpath fallback
        assert name is not None


# ── BasePlaybook._create_playbook_instance ───────────────────────────


class TestCreatePlaybookInstance:
    def test_knowledge(self):
        meta = PlaybookMetadata(triggers=["t1"])
        inst = BasePlaybook._create_playbook_instance(
            "kb", "content", meta, Path("t.md"), PlaybookType.KNOWLEDGE
        )
        assert isinstance(inst, KnowledgePlaybook)

    def test_repo(self):
        meta = PlaybookMetadata()
        inst = BasePlaybook._create_playbook_instance(
            "rp", "content", meta, Path("t.md"), PlaybookType.REPO_KNOWLEDGE
        )
        assert isinstance(inst, RepoPlaybook)

    def test_task(self):
        meta = PlaybookMetadata(
            inputs=[InputMetadata(name="x", description="d")]
        )
        inst = BasePlaybook._create_playbook_instance(
            "tp", "content", meta, Path("t.md"), PlaybookType.TASK
        )
        assert isinstance(inst, TaskPlaybook)


# ── BasePlaybook.load ────────────────────────────────────────────────


class TestBasePlaybookLoad:
    def test_load_repo_playbook(self, tmp_path):
        pb_dir = tmp_path / "playbooks"
        pb_dir.mkdir()
        pb_file = pb_dir / "guide.md"
        pb_file.write_text("---\nname: guide\n---\nRepo guidelines here.")
        result = BasePlaybook.load(pb_file, playbook_dir=pb_dir)
        assert isinstance(result, RepoPlaybook)
        assert "guidelines" in result.content

    def test_load_knowledge_playbook(self, tmp_path):
        pb_dir = tmp_path / "playbooks"
        pb_dir.mkdir()
        pb_file = pb_dir / "review.md"
        pb_file.write_text("---\nname: review\ntriggers:\n  - review\n---\nReview content.")
        result = BasePlaybook.load(pb_file, playbook_dir=pb_dir)
        assert isinstance(result, KnowledgePlaybook)
        assert result.metadata.triggers == ["review"]

    def test_load_task_playbook(self, tmp_path):
        pb_dir = tmp_path / "playbooks"
        pb_dir.mkdir()
        pb_file = pb_dir / "build.md"
        pb_file.write_text(
            "---\nname: build\ninputs:\n  - name: target\n    description: Build target\n---\nBuild ${target}."
        )
        result = BasePlaybook.load(pb_file, playbook_dir=pb_dir)
        assert isinstance(result, TaskPlaybook)
        assert result.type == PlaybookType.TASK

    def test_load_third_party(self, tmp_path):
        f = tmp_path / ".cursorrules"
        f.write_text("Custom rules here.")
        result = BasePlaybook.load(f)
        assert isinstance(result, RepoPlaybook)
        assert result.name == "cursorrules"

    def test_load_from_string_content(self, tmp_path):
        pb_dir = tmp_path / "playbooks"
        pb_dir.mkdir()
        pb_file = pb_dir / "inline.md"
        pb_file.touch()
        content = "---\nname: inline\n---\nInline content."
        result = BasePlaybook.load(pb_file, playbook_dir=pb_dir, file_content=content)
        assert "Inline content" in result.content

    def test_load_invalid_type(self, tmp_path):
        pb_dir = tmp_path / "playbooks"
        pb_dir.mkdir()
        pb_file = pb_dir / "bad.md"
        pb_file.write_text("---\ntype: invalid_type\n---\nBad.")
        with pytest.raises(PlaybookValidationError):
            BasePlaybook.load(pb_file, playbook_dir=pb_dir)


# ── KnowledgePlaybook ───────────────────────────────────────────────


class TestKnowledgePlaybook:
    def test_match_trigger_found(self):
        kb = KnowledgePlaybook(
            name="review",
            content="Review code",
            metadata=PlaybookMetadata(triggers=["review", "audit"]),
            source="test.md",
            type=PlaybookType.KNOWLEDGE,
        )
        assert kb.match_trigger("Please review this") == "review"

    def test_match_trigger_not_found(self):
        kb = KnowledgePlaybook(
            name="review",
            content="Review code",
            metadata=PlaybookMetadata(triggers=["review"]),
            source="test.md",
            type=PlaybookType.KNOWLEDGE,
        )
        assert kb.match_trigger("build the project") is None

    def test_wrong_type_rejected(self):
        with pytest.raises(ValueError, match="KNOWLEDGE or TASK"):
            KnowledgePlaybook(
                name="x",
                content="c",
                metadata=PlaybookMetadata(),
                source="s",
                type=PlaybookType.REPO_KNOWLEDGE,
            )


# ── RepoPlaybook ────────────────────────────────────────────────────


class TestRepoPlaybook:
    def test_valid(self):
        rp = RepoPlaybook(
            name="repo",
            content="Guidelines",
            metadata=PlaybookMetadata(),
            source="s.md",
            type=PlaybookType.REPO_KNOWLEDGE,
        )
        assert rp.type == PlaybookType.REPO_KNOWLEDGE

    def test_wrong_type_rejected(self):
        with pytest.raises(ValueError, match="incorrect type"):
            RepoPlaybook(
                name="x",
                content="c",
                metadata=PlaybookMetadata(),
                source="s",
                type=PlaybookType.KNOWLEDGE,
            )


# ── TaskPlaybook ────────────────────────────────────────────────────


class TestTaskPlaybook:
    def test_extract_variables(self):
        tp = TaskPlaybook(
            name="build",
            content="Build ${target} on ${env}",
            metadata=PlaybookMetadata(
                inputs=[InputMetadata(name="target", description="T")]
            ),
            source="s.md",
            type=PlaybookType.TASK,
        )
        variables = tp.extract_variables(tp.content)
        assert "target" in variables
        assert "env" in variables

    def test_requires_user_input(self):
        tp = TaskPlaybook(
            name="build",
            content="Build ${target}",
            metadata=PlaybookMetadata(
                inputs=[InputMetadata(name="target", description="T")]
            ),
            source="s.md",
            type=PlaybookType.TASK,
        )
        assert tp.requires_user_input() is True

    def test_no_variables_with_inputs(self):
        tp = TaskPlaybook(
            name="build",
            content="Static content",
            metadata=PlaybookMetadata(
                inputs=[InputMetadata(name="target", description="T")]
            ),
            source="s.md",
            type=PlaybookType.TASK,
        )
        # Has inputs metadata, so prompt is appended
        assert "provide" in tp.content.lower() or "variables" in tp.content.lower()

    def test_wrong_type_rejected(self):
        with pytest.raises(ValueError):
            TaskPlaybook(
                name="x",
                content="c",
                metadata=PlaybookMetadata(),
                source="s",
                type=PlaybookType.REPO_KNOWLEDGE,
            )


# ── _collect_special_files / _collect_markdown_files ─────────────────


class TestCollectFiles:
    def test_collect_special_cursorrules(self, tmp_path):
        (tmp_path / ".cursorrules").touch()
        files = _collect_special_files(tmp_path)
        assert any(f.name == ".cursorrules" for f in files)

    def test_collect_special_agents_md(self, tmp_path):
        # _collect_special_files checks AGENTS.md, agents.md, AGENT.md, agent.md in order
        (tmp_path / "AGENTS.md").touch()
        files = _collect_special_files(tmp_path)
        assert any("agents" in f.name.lower() for f in files)

    def test_collect_special_none(self, tmp_path):
        files = _collect_special_files(tmp_path)
        assert len(files) == 0

    def test_collect_markdown(self, tmp_path):
        pb_dir = tmp_path / "playbooks"
        pb_dir.mkdir()
        (pb_dir / "guide.md").touch()
        (pb_dir / "README.md").touch()  # Should be excluded
        files = _collect_markdown_files(pb_dir)
        assert len(files) == 1
        assert files[0].name == "guide.md"

    def test_collect_markdown_nonexistent(self, tmp_path):
        files = _collect_markdown_files(tmp_path / "nonexistent")
        assert files == []
