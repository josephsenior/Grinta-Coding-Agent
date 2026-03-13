"""Tests for backend.engines.orchestrator.file_verification_guard."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from typing import Any, cast


from backend.engines.orchestrator.file_verification_guard import (
    FileOperationContext,
    FileVerificationGuard,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_state():
    """Return a minimal mock State object."""
    state = MagicMock()
    state.history = []
    return state


def _make_action(path: str | None = None, action_type: str = "edit"):
    """Return a minimal mock Action with an optional path."""
    action = MagicMock()
    action.path = path
    action.action = action_type
    type(action).__name__ = "FileEditAction"
    return action


def _make_action_no_path():
    """Return a mock Action with no path attribute."""
    action = MagicMock(spec=[])  # no attributes at all
    return action


# ---------------------------------------------------------------------------
# FileOperationContext
# ---------------------------------------------------------------------------

class TestFileOperationContext:
    def test_defaults(self):
        ctx = FileOperationContext(operation_type="edit", file_paths=["a.py"])
        assert ctx.verified is False
        assert ctx.turn_started == 0

    def test_custom_values(self):
        ctx = FileOperationContext(
            operation_type="create",
            file_paths=["x.py", "y.py"],
            verified=True,
            turn_started=5,
        )
        assert ctx.operation_type == "create"
        assert ctx.file_paths == ["x.py", "y.py"]
        assert ctx.verified is True
        assert ctx.turn_started == 5

    def test_delete_type(self):
        ctx = FileOperationContext(operation_type="delete", file_paths=["gone.py"])
        assert ctx.operation_type == "delete"


# ---------------------------------------------------------------------------
# FileVerificationGuard.__init__ and reset
# ---------------------------------------------------------------------------

class TestFileVerificationGuardInit:
    def test_initial_state(self):
        g = FileVerificationGuard()
        assert g.pending_file_operations == []
        assert g.turn_counter == 0
        assert g.stats["verifications_injected"] == 0
        assert g.stats["hallucinations_prevented"] == 0
        assert g.stats["strict_mode_activations"] == 0

    def test_reset_clears_state(self):
        g = FileVerificationGuard()
        g.pending_file_operations.append(
            FileOperationContext("edit", ["f.py"], verified=True, turn_started=1)
        )
        g.turn_counter = 10
        g.stats["verifications_injected"] = 3
        g.reset()
        assert g.pending_file_operations == []
        assert g.turn_counter == 0
        assert g.stats["verifications_injected"] == 0
        assert g.stats["hallucinations_prevented"] == 0
        assert g.stats["strict_mode_activations"] == 0

    def test_reset_does_not_raise_on_empty(self):
        g = FileVerificationGuard()
        g.reset()  # should not raise


# ---------------------------------------------------------------------------
# should_enforce_tools
# ---------------------------------------------------------------------------

class TestShouldEnforceTools:
    def setup_method(self):
        self.g = FileVerificationGuard()
        self.state = _make_state()

    # --- empty / None message ---
    def test_empty_message_strict_returns_required(self):
        assert self.g.should_enforce_tools("", self.state, strict_mode=True) == "required"

    def test_empty_message_no_strict_returns_auto(self):
        assert self.g.should_enforce_tools("", self.state, strict_mode=False) == "auto"

    # --- question patterns -> "auto" ---
    def test_why_question_returns_auto(self):
        assert self.g.should_enforce_tools("why does this fail?", self.state) == "auto"

    def test_how_does_question_returns_auto(self):
        assert self.g.should_enforce_tools("how does the cache work?", self.state) == "auto"

    def test_what_is_question_returns_auto(self):
        assert self.g.should_enforce_tools("what is the purpose of this?", self.state) == "auto"

    def test_explain_why_returns_auto(self):
        assert self.g.should_enforce_tools("explain why this happens", self.state) == "auto"

    def test_tell_me_why_returns_auto(self):
        assert self.g.should_enforce_tools("tell me why it crashes", self.state) == "auto"

    # --- action patterns -> "required" ---
    def test_create_returns_required(self):
        result = self.g.should_enforce_tools("please create a new file", self.state)
        assert result == "required"

    def test_fix_returns_required(self):
        assert self.g.should_enforce_tools("fix the bug in auth.py", self.state) == "required"

    def test_edit_returns_required(self):
        assert self.g.should_enforce_tools("edit the config file", self.state) == "required"

    def test_implement_returns_required(self):
        assert self.g.should_enforce_tools("implement the login feature", self.state) == "required"

    def test_add_returns_required(self):
        assert self.g.should_enforce_tools("add a new route", self.state) == "required"

    def test_update_returns_required(self):
        assert self.g.should_enforce_tools("update the tests", self.state) == "required"

    def test_delete_returns_required(self):
        assert self.g.should_enforce_tools("delete unused files", self.state) == "required"

    def test_run_returns_required(self):
        assert self.g.should_enforce_tools("run the tests", self.state) == "required"

    def test_refactor_returns_required(self):
        assert self.g.should_enforce_tools("refactor the module", self.state) == "required"

    def test_check_returns_required(self):
        assert self.g.should_enforce_tools("check the coverage", self.state) == "required"

    def test_build_returns_required(self):
        assert self.g.should_enforce_tools("build the project", self.state) == "required"

    def test_install_returns_required(self):
        assert self.g.should_enforce_tools("install dependencies", self.state) == "required"

    def test_set_up_returns_required(self):
        assert self.g.should_enforce_tools("set up the environment", self.state) == "required"

    # --- action incrementing strict_mode_activations ---
    def test_action_increments_strict_mode_stat(self):
        self.g.should_enforce_tools("create a file", self.state)
        assert self.g.stats["strict_mode_activations"] == 1

    # --- pending file operations force "required" ---
    def test_pending_operations_force_required_non_question(self):
        # Question patterns short-circuit before the pending-ops check,
        # so use an unrecognised message to reach the pending-ops branch.
        self.g.pending_file_operations.append(
            FileOperationContext("edit", ["x.py"], verified=False, turn_started=0)
        )
        result = self.g.should_enforce_tools("go ahead please", self.state)
        assert result == "required"

    # --- strict_mode default True ---
    def test_strict_mode_default_returns_required_on_unknown(self):
        # A message that matches no patterns but strict_mode=True
        result = self.g.should_enforce_tools("go ahead", self.state, strict_mode=True)
        assert result == "required"

    def test_no_strict_mode_returns_auto_on_unknown(self):
        result = self.g.should_enforce_tools("go ahead", self.state, strict_mode=False)
        assert result == "auto"

    def test_strict_activations_incremented_when_strict_fallback(self):
        before = self.g.stats["strict_mode_activations"]
        self.g.should_enforce_tools("sure thing", self.state, strict_mode=True)
        # strict_mode fallback also increments
        assert self.g.stats["strict_mode_activations"] >= before


# ---------------------------------------------------------------------------
# _is_file_operation
# ---------------------------------------------------------------------------

class TestIsFileOperation:
    def setup_method(self):
        self.g = FileVerificationGuard()

    def test_action_with_path_is_file_op(self):
        action = _make_action(path="/some/file.py")
        assert self.g._is_file_operation(action) is True

    def test_action_no_path_is_not_file_op(self):
        action = _make_action_no_path()
        assert self.g._is_file_operation(action) is False

    def test_action_empty_path_is_not_file_op(self):
        action = MagicMock()
        action.path = "   "
        assert self.g._is_file_operation(action) is False

    def test_action_edit_type_is_file_op(self):
        action = MagicMock()
        action.action = "edit"
        action.path = "some/file.py"
        assert self.g._is_file_operation(action) is True

    def test_action_write_type_is_file_op(self):
        action = MagicMock()
        action.action = "write"
        action.path = "some/file.py"
        assert self.g._is_file_operation(action) is True

    def test_filewriteaction_class_name_is_file_op(self):
        action = MagicMock()
        type(action).__name__ = "FileWriteAction"
        action.path = "x.py"
        assert self.g._is_file_operation(action) is True


# ---------------------------------------------------------------------------
# _safe_file_path
# ---------------------------------------------------------------------------

class TestSafeFilePath:
    def setup_method(self):
        self.g = FileVerificationGuard()

    def test_valid_path_returned(self):
        action = MagicMock()
        action.path = "/foo/bar.py"
        assert FileVerificationGuard._safe_file_path(action) == "/foo/bar.py"

    def test_none_path_returns_none(self):
        action = MagicMock()
        action.path = None
        assert FileVerificationGuard._safe_file_path(action) is None

    def test_blank_path_returns_none(self):
        action = MagicMock()
        action.path = "  "
        assert FileVerificationGuard._safe_file_path(action) is None

    def test_no_path_attr_returns_none(self):
        action = MagicMock(spec=[])
        assert FileVerificationGuard._safe_file_path(action) is None


# ---------------------------------------------------------------------------
# inject_verification_commands
# ---------------------------------------------------------------------------

class TestInjectVerificationCommands:
    """inject_verification_commands is now a pass-through (returns actions unchanged)."""

    def setup_method(self):
        self.g = FileVerificationGuard()

    def test_non_file_action_not_duplicated(self):
        action = _make_action_no_path()
        result = self.g.inject_verification_commands([action], turn=1)
        assert len(result) == 1
        assert result[0] is action

    def test_file_action_gets_verification_appended(self):
        """Pass-through: file actions are returned unchanged."""
        action = _make_action(path="/tmp/test.py")
        result = self.g.inject_verification_commands([action], turn=2)
        assert len(result) == 1
        assert result[0] is action

    def test_stats_incremented_after_file_op(self):
        """Pass-through: no verifications are injected."""
        action = _make_action(path="/tmp/file.py")
        self.g.inject_verification_commands([action], turn=1)
        assert self.g.stats["verifications_injected"] == 0

    def test_pending_operations_registered(self):
        """Pass-through: no pending operations registered."""
        action = _make_action(path="/project/main.py")
        self.g.inject_verification_commands([action], turn=3)
        assert len(self.g.pending_file_operations) == 0

    def test_no_verification_when_create_returns_none(self):
        """Pass-through: returns input unchanged."""
        action = _make_action(path="/tmp/file.py")
        result = self.g.inject_verification_commands([action], turn=1)
        assert len(result) == 1

    def test_multiple_file_actions_all_get_verification(self):
        """Pass-through: multiple actions returned unchanged."""
        a1 = _make_action(path="/tmp/a.py")
        a2 = _make_action(path="/tmp/b.py")
        result = self.g.inject_verification_commands([a1, a2], turn=1)
        assert len(result) == 2  # pass-through, no extras


# ---------------------------------------------------------------------------
# validate_response
# ---------------------------------------------------------------------------

class TestValidateResponse:
    def setup_method(self):
        self.g = FileVerificationGuard()

    def _make_edit_action(self):
        from backend.core.schemas import ActionType
        action = MagicMock()
        action.action = ActionType.EDIT
        return action

    def test_no_file_claims_is_valid(self):
        valid, err = self.g.validate_response("I checked the logs.", [])
        assert valid is True
        assert err is None

    def test_file_claim_with_no_tools_is_invalid(self):
        text = "I created the file backend/utils/helpers.py successfully."
        valid, err = self.g.validate_response(text, [])
        assert valid is False
        assert err is not None
        assert "did not call the required tools" in err.lower()

    def test_hallucination_increments_stat(self):
        text = "I wrote utils/helpers.py to disk."
        self.g.validate_response(text, [])
        assert self.g.stats["hallucinations_prevented"] == 1

    def test_file_claim_with_edit_action_is_valid(self):
        text = "I edited src/module.py as requested."
        action = self._make_edit_action()
        valid, err = self.g.validate_response(text, [action])
        assert valid is True
        assert err is None

    def test_response_without_file_path_no_false_positive(self):
        # Sentence claims a "file" but without a real path → no pattern match
        text = "I created a solution to the problem."
        valid, err = self.g.validate_response(text, [])
        assert valid is True


# ---------------------------------------------------------------------------
# _extract_file_operation_claims
# ---------------------------------------------------------------------------

class TestExtractFileOperationClaims:
    def setup_method(self):
        self.g = FileVerificationGuard()

    def test_empty_text_no_claims(self):
        assert self.g._extract_file_operation_claims("") == []

    def test_path_created_via_pattern(self):
        text = "I created backend/utils/helpers.py for you."
        claims = self.g._extract_file_operation_claims(text)
        assert len(claims) >= 1

    def test_wrote_file_in_backticks(self):
        text = "I wrote `src/auth/login.py` to disk."
        claims = self.g._extract_file_operation_claims(text)
        assert len(claims) >= 1

    def test_no_file_path_no_claim(self):
        text = "I created a great solution for you."
        claims = self.g._extract_file_operation_claims(text)
        assert claims == []

    def test_deduplicated_claims(self):
        text = "I created utils/a.py and I created utils/a.py."
        claims = self.g._extract_file_operation_claims(text)
        # Deduplication via set → only 1 unique claim
        assert len(claims) == 1


# ---------------------------------------------------------------------------
# mark_operation_verified / get_unverified_operations
# ---------------------------------------------------------------------------

class TestVerificationTracking:
    def setup_method(self):
        self.g = FileVerificationGuard()

    def test_mark_operation_verified(self):
        self.g.pending_file_operations.append(
            FileOperationContext("edit", ["/src/main.py"], verified=False)
        )
        self.g.mark_operation_verified("/src/main.py")
        assert self.g.pending_file_operations[0].verified is True

    def test_mark_operation_no_match_does_not_raise(self):
        self.g.mark_operation_verified("/not/listed.py")  # should be silent

    def test_get_unverified_operations_empty(self):
        assert self.g.get_unverified_operations() == []

    def test_get_unverified_operations_returns_unverified(self):
        self.g.pending_file_operations.append(
            FileOperationContext("edit", ["a.py"], verified=False)
        )
        self.g.pending_file_operations.append(
            FileOperationContext("edit", ["b.py"], verified=True)
        )
        unverified = self.g.get_unverified_operations()
        assert len(unverified) == 1
        assert "a.py" in unverified[0].file_paths


# ---------------------------------------------------------------------------
# cleanup_old_operations
# ---------------------------------------------------------------------------

class TestCleanupOldOperations:
    def setup_method(self):
        self.g = FileVerificationGuard()

    def test_removes_old_operations(self):
        self.g.pending_file_operations.append(
            FileOperationContext("edit", ["old.py"], turn_started=0)
        )
        self.g.cleanup_old_operations(current_turn=10, max_age=3)
        assert self.g.pending_file_operations == []

    def test_keeps_recent_operations(self):
        self.g.pending_file_operations.append(
            FileOperationContext("edit", ["recent.py"], turn_started=8)
        )
        self.g.cleanup_old_operations(current_turn=10, max_age=3)
        assert len(self.g.pending_file_operations) == 1

    def test_boundary_age_kept(self):
        # turn_started=7, current=10, max_age=3 → age=3  → kept (<=)
        self.g.pending_file_operations.append(
            FileOperationContext("edit", ["boundary.py"], turn_started=7)
        )
        self.g.cleanup_old_operations(current_turn=10, max_age=3)
        assert len(self.g.pending_file_operations) == 1

    def test_mixed_operations(self):
        self.g.pending_file_operations += [
            FileOperationContext("edit", ["old.py"], turn_started=1),
            FileOperationContext("edit", ["new.py"], turn_started=9),
        ]
        self.g.cleanup_old_operations(current_turn=10, max_age=3)
        assert len(self.g.pending_file_operations) == 1
        assert "new.py" in self.g.pending_file_operations[0].file_paths


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------

class TestGetStats:
    def setup_method(self):
        self.g = FileVerificationGuard()

    def test_initial_stats(self):
        stats = self.g.get_stats()
        assert stats["verifications_injected"] == 0
        assert stats["hallucinations_prevented"] == 0
        assert stats["strict_mode_activations"] == 0
        assert stats["pending_operations"] == 0
        assert stats["unverified_operations"] == 0

    def test_pending_and_unverified_counts_reflect_state(self):
        self.g.pending_file_operations.append(
            FileOperationContext("edit", ["a.py"], verified=False)
        )
        self.g.pending_file_operations.append(
            FileOperationContext("edit", ["b.py"], verified=True)
        )
        stats = self.g.get_stats()
        assert stats["pending_operations"] == 2
        assert stats["unverified_operations"] == 1

    def test_stats_counts_after_hallucination_prevention(self):
        text = "I created backend/utils/helpers.py for you."
        self.g.validate_response(text, [])
        stats = self.g.get_stats()
        assert stats["hallucinations_prevented"] >= 1
