"""Unit tests for backend.telemetry.audit_logger — AuditLogger."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from backend.events.action import ActionSecurityRisk
from backend.telemetry.audit_logger import AuditLogger


# ── helpers ──────────────────────────────────────────────────────────


def _make_validation_result(
    *,
    allowed: bool = True,
    risk_level: ActionSecurityRisk = ActionSecurityRisk.LOW,
    requires_review: bool = False,
    blocked_reason: str | None = None,
    matched_patterns: list[str] | None = None,
) -> MagicMock:
    vr = MagicMock()
    vr.allowed = allowed
    vr.risk_level = risk_level
    vr.requires_review = requires_review
    vr.blocked_reason = blocked_reason
    vr.matched_patterns = matched_patterns or []
    return vr


def _make_cmd_action(command: str = "echo hello") -> MagicMock:
    from backend.events.action import CmdRunAction

    action = MagicMock(spec=CmdRunAction)
    action.command = command
    type(action).__name__ = "CmdRunAction"
    return action


def _make_file_edit_action(path: str = "file.py") -> MagicMock:
    from backend.events.action import FileEditAction

    action = MagicMock(spec=FileEditAction)
    action.path = path
    type(action).__name__ = "FileEditAction"
    return action


# ── AuditLogger init ────────────────────────────────────────────────


class TestAuditLoggerInit:
    def test_creates_directory(self, tmp_path):
        audit_dir = str(tmp_path / "audit" / "logs")
        logger = AuditLogger(audit_dir)
        assert logger.audit_base_path.exists()

    def test_existing_directory(self, tmp_path):
        audit_dir = str(tmp_path / "existing")
        (tmp_path / "existing").mkdir()
        logger = AuditLogger(audit_dir)
        assert logger.audit_base_path.exists()


# ── _extract_action_content ──────────────────────────────────────────


class TestExtractActionContent:
    def test_cmd_action(self, tmp_path):
        al = AuditLogger(str(tmp_path))
        action = _make_cmd_action("ls -la")
        content = al._extract_action_content(action)
        assert content == "ls -la"

    def test_file_edit_action(self, tmp_path):
        al = AuditLogger(str(tmp_path))
        action = _make_file_edit_action("src/main.py")
        content = al._extract_action_content(action)
        assert "src/main.py" in content

    def test_truncation(self, tmp_path):
        al = AuditLogger(str(tmp_path))
        action = _make_cmd_action("x" * 2000)
        content = al._extract_action_content(action)
        assert len(content) < 2000
        assert "truncated" in content

    def test_fallback_str(self, tmp_path):
        al = AuditLogger(str(tmp_path))
        action = MagicMock()
        action.__str__ = MagicMock(return_value="some-action")
        # Remove CmdRunAction and FileEditAction spec
        type(action).__name__ = "OtherAction"
        content = al._extract_action_content(action)
        assert isinstance(content, str)


# ── _get_session_log_file ────────────────────────────────────────────


class TestGetSessionLogFile:
    def test_creates_file(self, tmp_path):
        al = AuditLogger(str(tmp_path))
        log_file = al._get_session_log_file("session-1")
        assert log_file.exists()
        assert "session_session-1.jsonl" in log_file.name

    def test_sanitizes_path_separators(self, tmp_path):
        al = AuditLogger(str(tmp_path))
        log_file = al._get_session_log_file("path/to\\session")
        assert "/" not in log_file.name.replace("session_", "")
        assert "\\" not in log_file.name

    def test_idempotent(self, tmp_path):
        al = AuditLogger(str(tmp_path))
        f1 = al._get_session_log_file("s1")
        f2 = al._get_session_log_file("s1")
        assert f1 == f2


# ── log_action (async) ──────────────────────────────────────────────


class TestLogAction:
    @pytest.mark.asyncio
    async def test_logs_allowed_action(self, tmp_path):
        al = AuditLogger(str(tmp_path))
        action = _make_cmd_action("echo ok")
        vr = _make_validation_result(allowed=True)

        audit_id = await al.log_action(
            session_id="s1",
            iteration=1,
            action=action,
            validation_result=vr,
            timestamp=datetime(2025, 1, 1, 12, 0, 0),
        )

        assert isinstance(audit_id, str)
        assert audit_id

        # Verify file was written
        log_file = al._get_session_log_file("s1")
        content = log_file.read_text()
        assert "echo ok" in content

    @pytest.mark.asyncio
    async def test_logs_blocked_action(self, tmp_path):
        al = AuditLogger(str(tmp_path))
        action = _make_cmd_action("rm -rf /")
        vr = _make_validation_result(
            allowed=False,
            risk_level=ActionSecurityRisk.HIGH,
            blocked_reason="CRITICAL",
        )

        audit_id = await al.log_action(
            session_id="s1",
            iteration=2,
            action=action,
            validation_result=vr,
            timestamp=datetime(2025, 1, 1, 12, 1, 0),
        )

        log_file = al._get_session_log_file("s1")
        lines = [l for l in log_file.read_text().strip().split("\n") if l]
        data = json.loads(lines[-1])
        assert data["validation_result"] == "blocked"
        assert data["id"] == audit_id

    @pytest.mark.asyncio
    async def test_logs_requires_review(self, tmp_path):
        al = AuditLogger(str(tmp_path))
        action = _make_cmd_action("sudo something")
        vr = _make_validation_result(allowed=True, requires_review=True)

        await al.log_action(
            session_id="s1",
            iteration=3,
            action=action,
            validation_result=vr,
            timestamp=datetime(2025, 1, 1, 12, 2, 0),
        )

        log_file = al._get_session_log_file("s1")
        lines = [l for l in log_file.read_text().strip().split("\n") if l]
        data = json.loads(lines[-1])
        assert data["validation_result"] == "requires_review"


# ── read_session_audit ───────────────────────────────────────────────


class TestReadSessionAudit:
    @pytest.mark.asyncio
    async def test_reads_logged_entries(self, tmp_path):
        al = AuditLogger(str(tmp_path))
        action = _make_cmd_action("echo test")
        vr = _make_validation_result()

        await al.log_action(
            session_id="read-test",
            iteration=0,
            action=action,
            validation_result=vr,
            timestamp=datetime(2025, 1, 1),
        )

        entries = al.read_session_audit("read-test")
        assert len(entries) == 1
        assert entries[0].action_content == "echo test"

    def test_empty_session(self, tmp_path):
        al = AuditLogger(str(tmp_path))
        entries = al.read_session_audit("empty-session")
        assert entries == []


# ── get_blocked_actions / get_high_risk_actions ──────────────────────


class TestFilteredQueries:
    @pytest.mark.asyncio
    async def test_get_blocked_actions(self, tmp_path):
        al = AuditLogger(str(tmp_path))
        # Log allowed and blocked
        await al.log_action(
            session_id="filter-test",
            iteration=0,
            action=_make_cmd_action("echo ok"),
            validation_result=_make_validation_result(allowed=True),
            timestamp=datetime(2025, 1, 1),
        )
        await al.log_action(
            session_id="filter-test",
            iteration=1,
            action=_make_cmd_action("rm -rf /"),
            validation_result=_make_validation_result(
                allowed=False, blocked_reason="danger"
            ),
            timestamp=datetime(2025, 1, 1),
        )

        blocked = al.get_blocked_actions("filter-test")
        assert len(blocked) == 1
        assert blocked[0].validation_result == "blocked"

    @pytest.mark.asyncio
    async def test_get_high_risk_actions(self, tmp_path):
        al = AuditLogger(str(tmp_path))
        await al.log_action(
            session_id="risk-test",
            iteration=0,
            action=_make_cmd_action("safe"),
            validation_result=_make_validation_result(
                risk_level=ActionSecurityRisk.LOW
            ),
            timestamp=datetime(2025, 1, 1),
        )
        await al.log_action(
            session_id="risk-test",
            iteration=1,
            action=_make_cmd_action("risky"),
            validation_result=_make_validation_result(
                risk_level=ActionSecurityRisk.HIGH
            ),
            timestamp=datetime(2025, 1, 1),
        )

        high_risk = al.get_high_risk_actions("risk-test")
        assert len(high_risk) == 1
        assert high_risk[0].risk_level == ActionSecurityRisk.HIGH


# ── update_entry_snapshot ────────────────────────────────────────────


class TestUpdateEntrySnapshot:
    @pytest.mark.asyncio
    async def test_updates_existing_entry(self, tmp_path):
        al = AuditLogger(str(tmp_path))
        action = _make_cmd_action("unsafe")
        vr = _make_validation_result()

        audit_id = await al.log_action(
            session_id="snap-test",
            iteration=0,
            action=action,
            validation_result=vr,
            timestamp=datetime(2025, 1, 1),
        )

        updated = await al.update_entry_snapshot(
            session_id="snap-test",
            audit_id=audit_id,
            filesystem_snapshot_id="snap-abc",
            rollback_available=True,
        )
        assert updated is True

        entries = al.read_session_audit("snap-test")
        assert len(entries) == 1
        assert entries[0].filesystem_snapshot_id == "snap-abc"
        assert entries[0].rollback_available is True

    @pytest.mark.asyncio
    async def test_returns_false_for_unknown_id(self, tmp_path):
        al = AuditLogger(str(tmp_path))
        action = _make_cmd_action("echo")
        vr = _make_validation_result()
        await al.log_action(
            session_id="snap-miss",
            iteration=0,
            action=action,
            validation_result=vr,
            timestamp=datetime(2025, 1, 1),
        )

        updated = await al.update_entry_snapshot(
            session_id="snap-miss",
            audit_id="non-existent-id",
            filesystem_snapshot_id="snap-xyz",
        )
        assert updated is False

    @pytest.mark.asyncio
    async def test_returns_false_for_missing_session(self, tmp_path):
        al = AuditLogger(str(tmp_path))
        # Don't create any log file for this session
        updated = await al.update_entry_snapshot(
            session_id="totally-new",
            audit_id="id1",
            filesystem_snapshot_id="snap-1",
        )
        # Should handle gracefully (creates file but finds no entry)
        assert updated is False


# ── export_audit_trail ───────────────────────────────────────────────


class TestExportAuditTrail:
    @pytest.mark.asyncio
    async def test_exports_to_json(self, tmp_path):
        al = AuditLogger(str(tmp_path))
        await al.log_action(
            session_id="export-test",
            iteration=0,
            action=_make_cmd_action("echo hi"),
            validation_result=_make_validation_result(),
            timestamp=datetime(2025, 1, 1),
        )

        out_path = str(tmp_path / "export.json")
        al.export_audit_trail("export-test", out_path)

        with open(out_path, encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["action_content"] == "echo hi"
