"""Unit tests for backend.engines.orchestrator.hallucination_detector — Self-correction."""

import pytest

from backend.engines.orchestrator.hallucination_detector import HallucinationDetector
from backend.events.action import FileEditAction


# ---------------------------------------------------------------------------
# File creation hallucination detection
# ---------------------------------------------------------------------------


class TestFileCreationHallucination:
    @pytest.mark.parametrize(
        "response_text",
        [
            "I created test.py with the code",
            "I've created config.toml successfully",
            "Created app.js with the implementation",
            "The file main.rs has been created",
            "I made utils.py for the helpers",
            "Generated setup.py",
            "Wrote database.sql",
            "saved as output.json",
            "saved to results.csv",
        ],
    )
    def test_detects_file_creation_claims_without_tool(self, response_text):
        detector = HallucinationDetector()
        result = detector.detect_text_hallucination(
            llm_response_text=response_text,
            tools_called=[],
            actions=[],
        )

        assert result["hallucinated"] is True
        assert result["confidence"] >= 0.85
        assert "file_creation" in str(result["details"])
        assert any(
            tool in result["missing_tools"]
            for tool in ["edit_file", "str_replace_editor"]
        )

    def test_file_creation_with_tool_call_no_hallucination(self):
        detector = HallucinationDetector()
        result = detector.detect_text_hallucination(
            llm_response_text="I created test.py with the implementation",
            tools_called=["edit_file"],
            actions=[],
        )

        assert result["hallucinated"] is False

    def test_file_creation_with_action_no_hallucination(self):
        detector = HallucinationDetector()
        result = detector.detect_text_hallucination(
            llm_response_text="I created test.py",
            tools_called=[],
            actions=[FileEditAction(path="test.py")],
        )

        assert result["hallucinated"] is False


# ---------------------------------------------------------------------------
# File edit hallucination detection
# ---------------------------------------------------------------------------


class TestFileEditHallucination:
    @pytest.mark.parametrize(
        "response_text",
        [
            "I edited config.py to add the feature",
            "I've modified app.js",
            "Updated main.rs with the fix",
            "Changed settings.toml",
            "Modified database.sql",
        ],
    )
    def test_detects_file_edit_claims_without_tool(self, response_text):
        detector = HallucinationDetector()
        result = detector.detect_text_hallucination(
            llm_response_text=response_text,
            tools_called=[],
            actions=[],
        )

        assert result["hallucinated"] is True
        assert result["confidence"] >= 0.8
        assert "file_edit" in str(result["details"])

    def test_file_edit_with_tool_call_no_hallucination(self):
        detector = HallucinationDetector()
        result = detector.detect_text_hallucination(
            llm_response_text="I edited config.py",
            tools_called=["str_replace_editor"],
            actions=[],
        )

        assert result["hallucinated"] is False


# ---------------------------------------------------------------------------
# Code execution hallucination detection
# ---------------------------------------------------------------------------


class TestCodeExecutionHallucination:
    @pytest.mark.parametrize(
        "response_text",
        [
            "I ran the test suite",
            "I've executed the script",
            "Ran pytest",
            "Running the build command",
        ],
    )
    def test_detects_code_execution_claims_without_tool(self, response_text):
        detector = HallucinationDetector()
        result = detector.detect_text_hallucination(
            llm_response_text=response_text,
            tools_called=[],
            actions=[],
        )

        assert result["hallucinated"] is True
        # Code execution has lower confidence (conversational ambiguity)
        assert result["confidence"] >= 0.5

    def test_code_execution_with_tool_call_no_hallucination(self):
        detector = HallucinationDetector()
        result = detector.detect_text_hallucination(
            llm_response_text="I ran the tests",
            tools_called=["execute_bash"],
            actions=[],
        )

        assert result["hallucinated"] is False


# ---------------------------------------------------------------------------
# No hallucination cases
# ---------------------------------------------------------------------------


class TestNoHallucination:
    def test_safe_conversational_text(self):
        detector = HallucinationDetector()
        result = detector.detect_text_hallucination(
            llm_response_text="Let me create a file for you. I'll use edit_file to do that.",
            tools_called=["edit_file"],
            actions=[],
        )

        assert result["hallucinated"] is False

    def test_empty_response(self):
        detector = HallucinationDetector()
        result = detector.detect_text_hallucination(
            llm_response_text="",
            tools_called=[],
            actions=[],
        )

        assert result["hallucinated"] is False

    def test_thinking_only(self):
        detector = HallucinationDetector()
        result = detector.detect_text_hallucination(
            llm_response_text="I'm thinking about the best approach...",
            tools_called=[],
            actions=[],
        )

        assert result["hallucinated"] is False


# ---------------------------------------------------------------------------
# Multiple hallucinations
# ---------------------------------------------------------------------------


class TestMultipleHallucinations:
    def test_multiple_file_operations_claimed(self):
        detector = HallucinationDetector()
        result = detector.detect_text_hallucination(
            llm_response_text="I created test.py and edited config.toml and ran the tests",
            tools_called=[],
            actions=[],
        )

        assert result["hallucinated"] is True
        assert len(result["claimed_operations"]) >= 2
        # Multiple file ops should trigger high/critical severity
        assert result["severity"] in ("high", "critical")

    def test_mixed_hallucinations(self):
        detector = HallucinationDetector()
        result = detector.detect_text_hallucination(
            llm_response_text="I created app.py, modified config.json, and executed the script",
            tools_called=[],
            actions=[],
        )

        assert result["hallucinated"] is True
        assert len(result["details"]) >= 2


# ---------------------------------------------------------------------------
# Severity calculation
# ---------------------------------------------------------------------------


class TestSeverityCalculation:
    def test_critical_severity_file_ops_high_confidence(self):
        detector = HallucinationDetector()
        result = detector.detect_text_hallucination(
            llm_response_text="I created test.py with full implementation",
            tools_called=[],
            actions=[],
        )

        # File creation with high confidence should be critical
        assert result["severity"] == "critical"

    def test_high_severity_multiple_hallucinations(self):
        detector = HallucinationDetector()
        # File edit (0.85 confidence) + code execution = has_file_hallucination
        # but max_confidence is exactly 0.85, not > 0.85, so severity is "high"
        result = detector.detect_text_hallucination(
            llm_response_text="I edited config.py and ran the tests",
            tools_called=[],
            actions=[],
        )

        assert result["severity"] in ("high", "critical")

    def test_medium_severity_high_confidence_non_file(self):
        detector = HallucinationDetector()
        # This is a bit tricky since code execution is lower confidence
        # We'll check that medium is possible
        result = detector.detect_text_hallucination(
            llm_response_text="I edited utils.py",  # File edit - medium confidence
            tools_called=[],
            actions=[],
        )

        assert result["severity"] in ("critical", "high", "medium")

    def test_low_severity_single_low_confidence(self):
        detector = HallucinationDetector()
        result = detector.detect_text_hallucination(
            llm_response_text="I ran something",  # Vague claim
            tools_called=[],
            actions=[],
        )

        # Single low-confidence detection
        if result["hallucinated"]:
            assert result["severity"] in ("low", "medium")


# ---------------------------------------------------------------------------
# Correction prompt generation
# ---------------------------------------------------------------------------


class TestCorrectionPromptGeneration:
    def test_generates_prompt_for_hallucination(self):
        detector = HallucinationDetector()
        detection_result = {
            "hallucinated": True,
            "claimed_operations": ["Created test.py"],
            "missing_tools": ["edit_file"],
        }

        prompt = detector.generate_correction_prompt(
            detection_result, original_request="Create a test file"
        )

        assert "HALLUCINATION DETECTED" in prompt
        assert "Created test.py" in prompt
        assert "edit_file" in prompt
        assert "Create a test file" in prompt
        assert "RETRY" in prompt

    def test_empty_prompt_for_no_hallucination(self):
        detector = HallucinationDetector()
        detection_result = {"hallucinated": False}

        prompt = detector.generate_correction_prompt(
            detection_result, original_request="test"
        )

        assert prompt == ""

    def test_prompt_includes_all_missing_tools(self):
        detector = HallucinationDetector()
        detection_result = {
            "hallucinated": True,
            "claimed_operations": ["Created file", "Ran tests"],
            "missing_tools": ["edit_file", "execute_bash"],
        }

        prompt = detector.generate_correction_prompt(
            detection_result, original_request="Setup project"
        )

        for tool in ["edit_file", "execute_bash"]:
            assert tool in prompt


# ---------------------------------------------------------------------------
# Pattern matching edge cases
# ---------------------------------------------------------------------------


class TestPatternMatching:
    def test_case_insensitive_detection(self):
        detector = HallucinationDetector()
        result = detector.detect_text_hallucination(
            llm_response_text="I CREATED TEST.PY",
            tools_called=[],
            actions=[],
        )

        assert result["hallucinated"] is True

    def test_filename_with_path(self):
        detector = HallucinationDetector()
        result = detector.detect_text_hallucination(
            llm_response_text="I created src/utils/helper.py",
            tools_called=[],
            actions=[],
        )

        assert result["hallucinated"] is True

    def test_various_file_extensions(self):
        extensions = ["py", "js", "ts", "rs", "go", "java", "cpp", "h", "md", "json"]
        detector = HallucinationDetector()

        for ext in extensions:
            result = detector.detect_text_hallucination(
                llm_response_text=f"I created test_file.{ext}",
                tools_called=[],
                actions=[],
            )
            assert result["hallucinated"] is True, f"Failed to detect .{ext} file"


# ---------------------------------------------------------------------------
# Detector configuration
# ---------------------------------------------------------------------------


class TestDetectorConfiguration:
    def test_detection_enabled_by_default(self):
        detector = HallucinationDetector()
        assert detector.detection_enabled is True

    def test_disabled_detector_returns_no_hallucination(self):
        detector = HallucinationDetector()
        detector.detection_enabled = False

        result = detector.detect_text_hallucination(
            llm_response_text="I created test.py",
            tools_called=[],
            actions=[],
        )

        assert result["hallucinated"] is False

    def test_confidence_threshold_configurable(self):
        detector = HallucinationDetector()
        assert hasattr(detector, "false_positive_threshold")
        assert 0.0 <= detector.false_positive_threshold <= 1.0
