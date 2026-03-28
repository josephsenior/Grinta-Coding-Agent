"""Tests for backend.gateway.services.completion_service module.

Targets completion_service.py by testing:
- CompletionRequest and CompletionResult dataclasses
- Internal helper functions for tracking, budgets, security, and sanitization
- get_code_completion async function with all resilience features
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from backend.ledger.action import ActionSecurityRisk
from backend.gateway.services.completion_service import (
    CompletionRequest,
    CompletionResult,
    _error_tracking,
    analyze_security,
    check_circuit_breaker,
    estimate_cost,
    format_error_message,
    get_code_completion,
    record_error,
    record_success,
    sanitize_completion,
    track_cost,
)


def _fresh_id() -> str:
    """Return a unique conversation ID so tests never share module-level state."""
    return f"test-{uuid.uuid4().hex}"


# -----------------------------------------------------------
# Data Models
# -----------------------------------------------------------


class TestCompletionRequest:
    def test_create(self):
        req = CompletionRequest(
            file_path="test.py",
            file_content="import os\n",
            language="python",
            position={"line": 1, "character": 10},
            prefix="import ",
            suffix="\n",
        )
        assert req.file_path == "test.py"
        assert req.language == "python"
        assert req.prefix == "import "

    def test_frozen(self):
        req = CompletionRequest(
            file_path="test.py",
            file_content="",
            language="python",
            position={"line": 1, "character": 0},
            prefix="",
            suffix="",
        )
        with pytest.raises(AttributeError):
            req.file_path = "new.py"  # type: ignore


class TestCompletionResult:
    def test_create_success(self):
        result = CompletionResult(completion="os.path", stop_reason="stop")
        assert result.completion == "os.path"
        assert result.stop_reason == "stop"
        assert result.status_code == 200

    def test_create_with_error(self):
        result = CompletionResult(
            completion="", stop_reason="error", error="Failed", status_code=500
        )
        assert result.error == "Failed"
        assert result.status_code == 500

    def test_frozen(self):
        result = CompletionResult(completion="test")
        with pytest.raises(AttributeError):
            result.completion = "new"  # type: ignore


# -----------------------------------------------------------
# Error Tracking
# -----------------------------------------------------------


class TestErrorTracking:
    def test_record_error_increments_consecutive(self):
        cid = _fresh_id()
        record_error(cid, Exception("boom"))
        assert _error_tracking[cid]["consecutive_errors"] == 1
        record_error(cid, Exception("boom2"))
        assert _error_tracking[cid]["consecutive_errors"] == 2

    def test_record_error_appends_to_recent_success_as_false(self):
        cid = _fresh_id()
        record_error(cid, Exception("err"))
        assert _error_tracking[cid]["recent_success"][-1] is False

    def test_record_success_resets_consecutive(self):
        cid = _fresh_id()
        record_error(cid, Exception("err"))
        record_error(cid, Exception("err"))
        record_success(cid)
        assert _error_tracking[cid]["consecutive_errors"] == 0

    def test_record_success_appends_true(self):
        cid = _fresh_id()
        record_success(cid)
        assert _error_tracking[cid]["recent_success"][-1] is True

    def test_recent_success_capped_at_20(self):
        cid = _fresh_id()
        for _ in range(25):
            record_error(cid, Exception("e"))
        assert len(_error_tracking[cid]["recent_success"]) <= 20


class TestCircuitBreaker:
    def test_clean_conversation_not_blocked(self):
        cid = _fresh_id()
        should_block, reason = check_circuit_breaker(cid)
        assert should_block is False
        assert reason is None

    def test_after_success_not_blocked(self):
        cid = _fresh_id()
        record_success(cid)
        should_block, reason = check_circuit_breaker(cid)
        assert should_block is False
        assert reason is None

    def test_consecutive_errors_threshold_not_met(self):
        """4 errors should NOT trip the breaker (threshold is 5)."""
        cid = _fresh_id()
        for _ in range(4):
            record_error(cid, Exception("err"))
        should_block, _ = check_circuit_breaker(cid)
        assert should_block is False

    def test_consecutive_errors_trips_at_five(self):
        """Exactly 5 consecutive errors should trip the breaker."""
        cid = _fresh_id()
        for _ in range(5):
            record_error(cid, Exception("err"))
        should_block, reason = check_circuit_breaker(cid)
        assert should_block is True
        assert reason is not None
        assert "consecutive errors" in reason.lower()

    def test_consecutive_errors_trips_above_five(self):
        cid = _fresh_id()
        for _ in range(7):
            record_error(cid, Exception("err"))
        should_block, reason = check_circuit_breaker(cid)
        assert should_block is True
        assert reason is not None
        assert "consecutive errors" in reason.lower()

    def test_error_rate_path_exactly_50_percent(self):
        """Error rate >= 50% in last 10 of recent_success trips the breaker.

        This exercises the fixed line:
            if error_count / len(recent) >= 0.5
        (was previously: `if error_count / recent.5:` — invalid syntax)
        """
        cid = _fresh_id()
        # Ensure consecutive_errors stays below 5 so we test the rate path
        # Add 10 entries: 5 True, 5 False → exactly 50 % error rate
        for _ in range(5):
            record_success(cid)
        for _ in range(5):
            record_error(cid, Exception("err"))
        # Reset consecutive so only the rate path triggers
        _error_tracking[cid]["consecutive_errors"] = 0
        should_block, reason = check_circuit_breaker(cid)
        assert should_block is True
        assert reason is not None
        assert "error rate" in reason.lower()
        assert "50%" in reason

    def test_error_rate_path_above_50_percent(self):
        cid = _fresh_id()
        for _ in range(3):
            record_success(cid)
        for _ in range(7):
            record_error(cid, Exception("err"))
        _error_tracking[cid]["consecutive_errors"] = 0
        should_block, reason = check_circuit_breaker(cid)
        assert should_block is True
        assert reason is not None
        assert "error rate" in reason.lower()

    def test_error_rate_path_below_50_percent_not_blocked(self):
        """49 % error rate should NOT trip the rate-based path."""
        cid = _fresh_id()
        # Build up more than 10 recent_success entries so the slice is clean
        for _ in range(6):
            record_success(cid)
        for _ in range(4):
            record_error(cid, Exception("err"))
        _error_tracking[cid]["consecutive_errors"] = 0
        should_block, _ = check_circuit_breaker(cid)
        assert should_block is False

    def test_error_rate_path_requires_at_least_10_recent(self):
        """Fewer than 10 entries in recent_success must not trigger the rate path."""
        cid = _fresh_id()
        # Only 9 total entries, all errors → rate = 100 % but window < 10
        for _ in range(9):
            record_error(cid, Exception("err"))
        _error_tracking[cid]["consecutive_errors"] = 0
        # Should not block via rate path (consecutive check also 0 now)
        should_block, _ = check_circuit_breaker(cid)
        assert should_block is False


# -----------------------------------------------------------
# Cost Tracking
# -----------------------------------------------------------


class TestCostTracking:
    def test_estimate_cost(self):
        cost = estimate_cost("gpt-4", 100, 50)
        assert cost > 0

    def test_track_cost(self):
        cost = track_cost("gpt-4", 100, 50, "user:test")
        assert cost > 0


# -----------------------------------------------------------
# Security
# -----------------------------------------------------------


class TestSecurityAnalysis:
    def test_high_risk_eval(self):
        risk, warning = analyze_security("result = eval(user_input)")
        assert risk == ActionSecurityRisk.HIGH
        assert warning is not None
        assert "eval" in warning.lower()

    def test_high_risk_exec(self):
        risk, warning = analyze_security("exec(some_code)")
        assert risk == ActionSecurityRisk.HIGH
        assert warning is not None

    def test_high_risk_subprocess(self):
        risk, warning = analyze_security("subprocess.call(cmd, shell=True)")
        assert risk == ActionSecurityRisk.HIGH

    def test_high_risk_os_system(self):
        risk, warning = analyze_security("os.system('rm -rf /')")
        assert risk == ActionSecurityRisk.HIGH

    def test_high_risk_import(self):
        risk, warning = analyze_security("mod = __import__('os')")
        assert risk == ActionSecurityRisk.HIGH

    def test_high_risk_shell_true(self):
        risk, warning = analyze_security("run(cmd, shell=True)")
        assert risk == ActionSecurityRisk.HIGH

    def test_medium_risk_open(self):
        risk, warning = analyze_security("f = open('file.txt', encoding='utf-8')")
        assert risk == ActionSecurityRisk.MEDIUM
        assert warning is not None
        assert "open" in warning.lower()

    def test_medium_risk_pickle(self):
        risk, warning = analyze_security("data = pickle.load(file)")
        assert risk == ActionSecurityRisk.MEDIUM

    def test_medium_risk_json_loads(self):
        risk, warning = analyze_security("obj = json.loads(raw)")
        assert risk == ActionSecurityRisk.MEDIUM

    def test_medium_risk_requests_get(self):
        risk, warning = analyze_security("resp = requests.get(url)")
        assert risk == ActionSecurityRisk.MEDIUM

    def test_low_risk_arithmetic(self):
        risk, warning = analyze_security("x = 1 + 2")
        assert risk == ActionSecurityRisk.LOW
        assert warning is None

    def test_low_risk_clean_function(self):
        risk, warning = analyze_security("def add(a, b):\n    return a + b")
        assert risk == ActionSecurityRisk.LOW
        assert warning is None

    def test_high_risk_overrides_medium(self):
        """When a completion contains both medium and high patterns, HIGH is returned."""
        code = "f = open('file')\nresult = eval(user)"
        risk, _ = analyze_security(code)
        assert risk == ActionSecurityRisk.HIGH


# -----------------------------------------------------------
# Sanitization
# -----------------------------------------------------------


class TestSanitization:
    def test_strip_markdown_fence_with_language(self):
        raw = "```python\nprint('hello')\n```"
        result = sanitize_completion(raw)
        assert result == "print('hello')"

    def test_strip_markdown_fence_without_language(self):
        raw = "```\nprint('hello')\n```"
        result = sanitize_completion(raw)
        assert "```" not in result
        assert "print('hello')" in result

    def test_no_fence_passes_through(self):
        raw = "x = 1 + 2"
        result = sanitize_completion(raw)
        assert result == "x = 1 + 2"

    def test_truncate_long_completion(self):
        raw = "x" * 2000
        result = sanitize_completion(raw)
        assert len(result) <= 1000

    def test_exactly_at_limit_not_truncated(self):
        raw = "x" * 1000
        result = sanitize_completion(raw)
        assert len(result) == 1000

    def test_remove_hallucination_created(self):
        raw = "def foo():\n    pass\nI have created the function successfully."
        result = sanitize_completion(raw)
        assert "I have created" not in result
        assert "def foo" in result

    def test_remove_hallucination_written(self):
        raw = "result = 42\nI've written this code for you."
        result = sanitize_completion(raw)
        assert "I've written" not in result
        assert "result = 42" in result

    def test_remove_hallucination_file_created(self):
        raw = "import os\nFile created successfully."
        result = sanitize_completion(raw)
        assert "File created successfully" not in result

    def test_remove_multiple_hallucinations_stops_at_first(self):
        raw = "code1\nI have written this\ncode2\nThe file has been saved"
        result = sanitize_completion(raw)
        # Truncates at the FIRST pattern
        assert "I have written" not in result
        assert "The file has been" not in result

    def test_hallucination_at_start_returns_empty(self):
        raw = "I have created the function"
        result = sanitize_completion(raw)
        assert result == ""

    def test_strip_whitespace(self):
        raw = "  \n  x = 1  \n  "
        result = sanitize_completion(raw)
        # strip() is applied; content should be present
        assert "x = 1" in result


# -----------------------------------------------------------
# Error Formatting
# -----------------------------------------------------------


