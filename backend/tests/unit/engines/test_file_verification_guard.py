"""Tests for backend.engines.orchestrator.file_verification_guard."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.engines.orchestrator.file_verification_guard import (
    FileOperationContext,
    FileVerificationGuard,
)


@pytest.fixture
def guard():
    g = FileVerificationGuard()
    yield g
    g.reset()


# ── should_enforce_tools ─────────────────────────────────────────────

class TestShouldEnforceTools:
    def test_empty_message_strict(self, guard):
        assert guard.should_enforce_tools("", MagicMock(), strict_mode=True) == "required"

    def test_empty_message_not_strict(self, guard):
        assert guard.should_enforce_tools("", MagicMock(), strict_mode=False) == "auto"

    def test_question_pattern(self, guard):
        assert guard.should_enforce_tools("why does it fail", MagicMock()) == "auto"
        assert guard.should_enforce_tools("explain why x works", MagicMock()) == "auto"

    def test_action_pattern(self, guard):
        assert guard.should_enforce_tools("create a file", MagicMock()) == "required"
        assert guard.should_enforce_tools("fix the bug", MagicMock()) == "required"
        assert guard.should_enforce_tools("edit main.py", MagicMock()) == "required"

    def test_pending_operations_force_required(self, guard):
        guard.pending_file_operations.append(
            FileOperationContext("edit", ["/tmp/x.py"], False, 1)
        )
        assert guard.should_enforce_tools("hello", MagicMock(), strict_mode=False) == "required"


# ── inject_verification_commands ─────────────────────────────────────

class TestInjectVerification:
    def test_non_file_op_unchanged(self, guard):
        action = MagicMock()
        action.action = "message"
        type(action).__name__ = "MessageAction"
        # remove path attribute to prevent false positive
        del action.path
        result = guard.inject_verification_commands([action], turn=1)
        assert len(result) == 1

    def test_file_edit_op_injects(self, guard):
        action = MagicMock()
        type(action).__name__ = "FileEditAction"
        action.path = "/tmp/x.py"
        action.action = "edit"
        result = guard.inject_verification_commands([action], turn=1)
        assert len(result) >= 2
        assert guard.stats["verifications_injected"] >= 1


# ── validate_response ────────────────────────────────────────────────

class TestValidateResponse:
    def test_no_claims(self, guard):
        ok, msg = guard.validate_response("Just a message", [])
        assert ok is True
        assert msg is None

    def test_claim_with_tools_ok(self, guard):
        from backend.events.action.files import FileEditAction
        action = MagicMock(spec=FileEditAction)
        action.action = "edit"
        ok, msg = guard.validate_response("I created src/main.py", [action])
        assert ok is True


# ── _extract_file_operation_claims ───────────────────────────────────

class TestExtractClaims:
    def test_with_path(self, guard):
        claims = guard._extract_file_operation_claims("I created src/utils/main.py")
        assert len(claims) >= 1

    def test_no_claims(self, guard):
        claims = guard._extract_file_operation_claims("Just thinking about stuff")
        assert len(claims) == 0


# ── mark / cleanup / stats ───────────────────────────────────────────

class TestFileOperationManagement:
    def test_mark_verified(self, guard):
        guard.pending_file_operations.append(
            FileOperationContext("edit", ["/tmp/x.py"], False, 1)
        )
        guard.mark_operation_verified("/tmp/x.py")
        assert guard.pending_file_operations[0].verified is True

    def test_get_unverified(self, guard):
        guard.pending_file_operations.append(
            FileOperationContext("edit", ["/a.py"], False, 1)
        )
        guard.pending_file_operations.append(
            FileOperationContext("edit", ["/b.py"], True, 1)
        )
        unverified = guard.get_unverified_operations()
        assert len(unverified) == 1

    def test_cleanup_old(self, guard):
        guard.pending_file_operations.append(
            FileOperationContext("edit", ["/old.py"], False, 1)
        )
        guard.pending_file_operations.append(
            FileOperationContext("edit", ["/new.py"], False, 5)
        )
        guard.cleanup_old_operations(current_turn=5, max_age=3)
        assert len(guard.pending_file_operations) == 1

    def test_get_stats(self, guard):
        stats = guard.get_stats()
        assert "pending_operations" in stats
        assert "verifications_injected" in stats

    def test_reset(self, guard):
        guard.pending_file_operations.append(
            FileOperationContext("edit", ["/x.py"], False, 1)
        )
        guard.stats["verifications_injected"] = 5
        guard.reset()
        assert len(guard.pending_file_operations) == 0
        assert guard.stats["verifications_injected"] == 0
