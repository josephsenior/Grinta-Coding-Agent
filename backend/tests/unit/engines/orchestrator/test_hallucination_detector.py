"""Comprehensive unit tests for HallucinationDetector.

All methods are pure logic (regex pattern matching), no external LLM or
network dependencies.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.engines.orchestrator.hallucination_detector import HallucinationDetector
from backend.events.action.files import FileEditAction
from backend.events.action import NullAction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detector() -> HallucinationDetector:
    return HallucinationDetector()


def _fake_file_edit_action() -> FileEditAction:
    action = MagicMock(spec=FileEditAction)
    return action


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------

class TestInit:
    def test_detection_enabled_by_default(self):
        d = _detector()
        assert d.detection_enabled is True

    def test_false_positive_threshold(self):
        d = _detector()
        assert d.false_positive_threshold == pytest.approx(0.7)

    def test_has_pattern_lists(self):
        d = _detector()
        assert len(d.FILE_CREATION_PATTERNS) > 0
        assert len(d.FILE_EDIT_PATTERNS) > 0
        assert len(d.CODE_EXEC_PATTERNS) > 0


# ---------------------------------------------------------------------------
# detect_text_hallucination — disabled
# ---------------------------------------------------------------------------

class TestDetectionDisabled:
    def test_disabled_returns_no_hallucination(self):
        d = _detector()
        d.detection_enabled = False
        result = d.detect_text_hallucination(
            "I created file.py and I ran the tests",
            tools_called=[],
            actions=[],
        )
        assert result == {"hallucinated": False}


# ---------------------------------------------------------------------------
# detect_text_hallucination — no hallucination cases
# ---------------------------------------------------------------------------

class TestNoHallucination:
    def test_clean_text_no_claims(self):
        d = _detector()
        result = d.detect_text_hallucination("Analysing the requirements.", [], [])
        assert result["hallucinated"] is False

    def test_file_creation_claim_with_tool_called(self):
        """If the agent claimed it AND called edit_file, no hallucination."""
        d = _detector()
        result = d.detect_text_hallucination(
            "I created file.py with the implementation.",
            tools_called=["edit_file"],
            actions=[],
        )
        assert result["hallucinated"] is False

    def test_file_creation_claim_with_action_object(self):
        """If a FileEditAction exists in actions, no hallucination."""
        d = _detector()
        result = d.detect_text_hallucination(
            "I created module.py",
            tools_called=[],
            actions=[_fake_file_edit_action()],
        )
        assert result["hallucinated"] is False

    def test_file_edit_with_str_replace_editor_tool(self):
        d = _detector()
        result = d.detect_text_hallucination(
            "Updated main.py with the new function",
            tools_called=["str_replace_editor"],
            actions=[],
        )
        assert result["hallucinated"] is False


# ---------------------------------------------------------------------------
# detect_text_hallucination — file creation hallucination
# ---------------------------------------------------------------------------

class TestFileCreationHallucination:
    def test_i_created_file_no_tool(self):
        d = _detector()
        result = d.detect_text_hallucination(
            "I created app.py with the main function.",
            tools_called=[],
            actions=[],
        )
        assert result["hallucinated"] is True
        assert result["severity"] in ("high", "critical")
        assert "app.py" in " ".join(result["claimed_operations"])

    def test_ive_written_file_no_tool(self):
        d = _detector()
        result = d.detect_text_hallucination(
            "I've written utils.py",
            tools_called=[],
            actions=[],
        )
        assert result["hallucinated"] is True

    def test_created_file_pattern_no_tool(self):
        d = _detector()
        result = d.detect_text_hallucination(
            "Created config.json for the project",
            tools_called=[],
            actions=[],
        )
        assert result["hallucinated"] is True

    def test_saved_as_pattern_no_tool(self):
        d = _detector()
        result = d.detect_text_hallucination(
            "saved as mymodule.py",
            tools_called=[],
            actions=[],
        )
        assert result["hallucinated"] is True

    def test_file_has_been_created_pattern(self):
        d = _detector()
        result = d.detect_text_hallucination(
            "The file data.json has been created",
            tools_called=[],
            actions=[],
        )
        assert result["hallucinated"] is True

    def test_confidence_is_high(self):
        d = _detector()
        result = d.detect_text_hallucination(
            "I created test.py",
            tools_called=[],
            actions=[],
        )
        assert result["confidence"] >= 0.85

    def test_missing_tools_listed(self):
        d = _detector()
        result = d.detect_text_hallucination(
            "I created test.py",
            tools_called=[],
            actions=[],
        )
        assert "edit_file" in result["missing_tools"] or "str_replace_editor" in result["missing_tools"]


# ---------------------------------------------------------------------------
# detect_text_hallucination — file edit hallucination
# ---------------------------------------------------------------------------

class TestFileEditHallucination:
    def test_i_edited_file_no_tool(self):
        d = _detector()
        result = d.detect_text_hallucination(
            "I edited utils.py to fix the bug",
            tools_called=[],
            actions=[],
        )
        assert result["hallucinated"] is True

    def test_updated_file_no_tool(self):
        d = _detector()
        result = d.detect_text_hallucination(
            "Updated models.py with the new class",
            tools_called=[],
            actions=[],
        )
        assert result["hallucinated"] is True

    def test_ive_modified_no_tool(self):
        d = _detector()
        result = d.detect_text_hallucination(
            "I've modified config.yaml",
            tools_called=[],
            actions=[],
        )
        assert result["hallucinated"] is True

    def test_changed_file_no_tool(self):
        d = _detector()
        result = d.detect_text_hallucination(
            "Changed settings.py to use environment variables",
            tools_called=[],
            actions=[],
        )
        assert result["hallucinated"] is True


# ---------------------------------------------------------------------------
# detect_text_hallucination — code execution hallucination
# ---------------------------------------------------------------------------

class TestCodeExecHallucination:
    def test_i_ran_no_tool(self):
        d = _detector()
        result = d.detect_text_hallucination(
            "I ran the test suite",
            tools_called=[],
            actions=[],
        )
        assert result["hallucinated"] is True

    def test_i_executed_no_tool(self):
        d = _detector()
        result = d.detect_text_hallucination(
            "I've executed the script",
            tools_called=[],
            actions=[],
        )
        assert result["hallucinated"] is True

    def test_ran_pattern_no_tool(self):
        d = _detector()
        result = d.detect_text_hallucination(
            "Ran 'pytest -x'",
            tools_called=[],
            actions=[],
        )
        assert result["hallucinated"] is True

    def test_exec_confidence_lower_than_file(self):
        d = _detector()
        exec_result = d.detect_text_hallucination(
            "I ran the tests",
            tools_called=[],
            actions=[],
        )
        file_result = d.detect_text_hallucination(
            "I created main.py",
            tools_called=[],
            actions=[],
        )
        # Code exec has lower confidence than file creation
        assert exec_result["confidence"] < file_result["confidence"]


# ---------------------------------------------------------------------------
# _calculate_severity
# ---------------------------------------------------------------------------

class TestCalculateSeverity:
    def setup_method(self):
        self.d = _detector()

    def test_empty_list_returns_none(self):
        assert self.d._calculate_severity([]) == "none"

    def test_low_confidence_code_exec_is_low(self):
        hallucinations = [{"type": "code_execution", "confidence": 0.6, "missing_tools": []}]
        assert self.d._calculate_severity(hallucinations) == "low"

    def test_medium_when_confidence_above_07(self):
        hallucinations = [{"type": "code_execution", "confidence": 0.75, "missing_tools": []}]
        assert self.d._calculate_severity(hallucinations) == "medium"

    def test_critical_for_file_creation_high_confidence(self):
        hallucinations = [{"type": "file_creation", "confidence": 0.9, "missing_tools": []}]
        assert self.d._calculate_severity(hallucinations) == "critical"

    def test_high_for_file_edit_low_confidence(self):
        hallucinations = [{"type": "file_edit", "confidence": 0.5, "missing_tools": []}]
        assert self.d._calculate_severity(hallucinations) == "high"

    def test_high_for_more_than_two_hallucinations(self):
        hallucinations = [
            {"type": "code_execution", "confidence": 0.6, "missing_tools": []},
            {"type": "code_execution", "confidence": 0.6, "missing_tools": []},
            {"type": "code_execution", "confidence": 0.6, "missing_tools": []},
        ]
        assert self.d._calculate_severity(hallucinations) == "high"


# ---------------------------------------------------------------------------
# generate_correction_prompt
# ---------------------------------------------------------------------------

class TestGenerateCorrectionPrompt:
    def setup_method(self):
        self.d = _detector()

    def test_no_hallucination_returns_empty(self):
        result = self.d.generate_correction_prompt({"hallucinated": False}, "")
        assert result == ""

    def test_hallucination_prompt_contains_claimed_ops(self):
        detection = {
            "hallucinated": True,
            "claimed_operations": ["I created file.py"],
            "missing_tools": ["edit_file"],
        }
        prompt = self.d.generate_correction_prompt(detection, "Create a file")
        assert "I created file.py" in prompt
        assert "edit_file" in prompt

    def test_contains_original_request(self):
        detection = {
            "hallucinated": True,
            "claimed_operations": ["Ran tests"],
            "missing_tools": ["execute_bash"],
        }
        prompt = self.d.generate_correction_prompt(detection, "Run the test suite")
        assert "Run the test suite" in prompt

    def test_prompt_contains_correction_instruction(self):
        detection = {
            "hallucinated": True,
            "claimed_operations": ["I wrote main.py"],
            "missing_tools": ["edit_file"],
        }
        prompt = self.d.generate_correction_prompt(detection, "Write main.py")
        assert "HALLUCINATION" in prompt or "CORRECTION" in prompt

    def test_missing_hallucinated_key_returns_empty(self):
        result = self.d.generate_correction_prompt({}, "request")
        assert result == ""

    def test_multiple_claimed_ops_all_listed(self):
        detection = {
            "hallucinated": True,
            "claimed_operations": ["I created a.py", "I created b.py"],
            "missing_tools": ["edit_file"],
        }
        prompt = self.d.generate_correction_prompt(detection, "task")
        assert "a.py" in prompt
        assert "b.py" in prompt
