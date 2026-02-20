"""Tests for backend.api.services.completion_service module.

Targets completion_service.py by testing:
- CompletionRequest and CompletionResult dataclasses
- Internal helper functions for tracking, budgets, security, and sanitization
- get_code_completion async function with all resilience features
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.controller.error_recovery import ErrorType
from backend.events.action import ActionSecurityRisk
from backend.api.services.completion_service import (
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
        assert "consecutive errors" in reason.lower()

    def test_consecutive_errors_trips_above_five(self):
        cid = _fresh_id()
        for _ in range(7):
            record_error(cid, Exception("err"))
        should_block, reason = check_circuit_breaker(cid)
        assert should_block is True
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


class TestErrorFormatting:
    def test_network_error(self):
        exc = Exception("Connection refused")
        msg = format_error_message(exc, ErrorType.NETWORK_ERROR)
        assert "AI service" in msg
        assert "connectivity" in msg.lower()

    def test_timeout_error(self):
        exc = Exception("Timeout")
        msg = format_error_message(exc, ErrorType.TIMEOUT_ERROR)
        assert "timed out" in msg.lower()

    def test_permission_error(self):
        exc = Exception("403 Forbidden")
        msg = format_error_message(exc, ErrorType.PERMISSION_ERROR)
        assert "permissions" in msg.lower()

    def test_module_not_found(self):
        exc = Exception("No module named 'foo'")
        msg = format_error_message(exc, ErrorType.MODULE_NOT_FOUND)
        assert "Missing module" in msg

    def test_default_fallback_unknown_type(self):
        exc = Exception("Something exotic happened")
        msg = format_error_message(exc, ErrorType.UNKNOWN_ERROR)
        assert "Something exotic happened" in msg

    def test_error_type_value_appended(self):
        """Every formatted message should include the ErrorType value for traceability."""
        exc = Exception("err")
        msg = format_error_message(exc, ErrorType.NETWORK_ERROR)
        assert ErrorType.NETWORK_ERROR.value in msg


# -----------------------------------------------------------
# get_code_completion Integration
# -----------------------------------------------------------


@pytest.fixture
def completion_req():
    return CompletionRequest(
        file_path="test.py",
        file_content="import os\n",
        language="python",
        position={"line": 1, "character": 7},
        prefix="import ",
        suffix="\n",
    )


@pytest.fixture
def llm_config():
    config = MagicMock()
    config.model = "gpt-4"
    return config


@pytest.fixture
def manager():
    mgr = MagicMock()
    mgr.request_llm_completion = AsyncMock(return_value="os.path")
    return mgr


@pytest.fixture
def anti_hallucination():
    guard = MagicMock()
    guard.validate_response = MagicMock(return_value=(True, None))
    return guard


@pytest.mark.asyncio
async def test_get_code_completion_success(
    completion_req, llm_config, manager, anti_hallucination
):
    result = await get_code_completion(
        req=completion_req,
        conversation_sid=_fresh_id(),
        user_id="user1",
        llm_config=llm_config,
        manager=manager,
        anti_hallucination=anti_hallucination,
    )
    assert result.status_code == 200
    assert result.completion == "os.path"
    assert result.stop_reason == "stop"


@pytest.mark.asyncio
async def test_get_code_completion_high_security_risk(
    completion_req, llm_config, manager, anti_hallucination
):
    manager.request_llm_completion = AsyncMock(return_value="eval(user_input)")
    result = await get_code_completion(
        req=completion_req,
        conversation_sid=_fresh_id(),
        user_id="user1",
        llm_config=llm_config,
        manager=manager,
        anti_hallucination=anti_hallucination,
    )
    assert result.completion == ""
    assert result.stop_reason == "security_risk_high"
    assert result.warning is not None


@pytest.mark.asyncio
async def test_get_code_completion_medium_security_risk_allowed(
    completion_req, llm_config, manager, anti_hallucination
):
    """MEDIUM risk completions should be allowed through (only HIGH is blocked)."""
    manager.request_llm_completion = AsyncMock(
        return_value="f = open('config.txt', encoding='utf-8')"
    )
    result = await get_code_completion(
        req=completion_req,
        conversation_sid=_fresh_id(),
        user_id="user1",
        llm_config=llm_config,
        manager=manager,
        anti_hallucination=anti_hallucination,
    )
    assert result.status_code == 200
    assert result.completion != ""
    # security_risk should reflect MEDIUM
    assert result.security_risk == "medium"


@pytest.mark.asyncio
async def test_get_code_completion_hallucination_detected(
    completion_req, llm_config, manager, anti_hallucination
):
    manager.request_llm_completion = AsyncMock(return_value="code here")
    anti_hallucination.validate_response = MagicMock(
        return_value=(False, "Hallucination")
    )
    result = await get_code_completion(
        req=completion_req,
        conversation_sid=_fresh_id(),
        user_id="user1",
        llm_config=llm_config,
        manager=manager,
        anti_hallucination=anti_hallucination,
    )
    assert result.completion == ""
    assert result.stop_reason == "hallucination_detected"


@pytest.mark.asyncio
async def test_get_code_completion_timeout_with_retry(
    completion_req, llm_config, manager, anti_hallucination
):
    """asyncio.TimeoutError on first attempt, success on second."""
    manager.request_llm_completion = AsyncMock(
        side_effect=[asyncio.TimeoutError(), "os.path"]
    )
    with patch("backend.api.services.completion_service.COMPLETION_TIMEOUT", 0.1):
        with patch(
            "backend.api.services.completion_service.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            result = await get_code_completion(
                req=completion_req,
                conversation_sid=_fresh_id(),
                user_id="user1",
                llm_config=llm_config,
                manager=manager,
                anti_hallucination=anti_hallucination,
            )
    assert result.status_code == 200
    assert result.completion == "os.path"


@pytest.mark.asyncio
async def test_get_code_completion_circuit_breaker_tripped(
    completion_req, llm_config, manager, anti_hallucination
):
    cid = _fresh_id()
    # Trip via consecutive errors (>= 5)
    for _ in range(5):
        record_error(cid, Exception("Error"))
    result = await get_code_completion(
        req=completion_req,
        conversation_sid=cid,
        user_id="user1",
        llm_config=llm_config,
        manager=manager,
        anti_hallucination=anti_hallucination,
    )
    assert result.status_code == 503
    assert result.stop_reason == "circuit_breaker_tripped"
    # LLM should never even be called when circuit breaker is open
    manager.request_llm_completion.assert_not_called()


@pytest.mark.asyncio
async def test_get_code_completion_circuit_breaker_error_rate(
    completion_req, llm_config, manager, anti_hallucination
):
    """Circuit breaker triggered via the error-RATE path (the previously-buggy line)."""
    cid = _fresh_id()
    for _ in range(5):
        record_success(cid)
    for _ in range(5):
        record_error(cid, Exception("err"))
    _error_tracking[cid]["consecutive_errors"] = 0  # ensure rate path fires
    result = await get_code_completion(
        req=completion_req,
        conversation_sid=cid,
        user_id="user1",
        llm_config=llm_config,
        manager=manager,
        anti_hallucination=anti_hallucination,
    )
    assert result.status_code == 503
    assert result.stop_reason == "circuit_breaker_tripped"
    manager.request_llm_completion.assert_not_called()


@pytest.mark.asyncio
async def test_get_code_completion_budget_exceeded(
    completion_req, llm_config, anti_hallucination
):
    """When budget is already exceeded the function must return 402 immediately."""
    from backend.api.services.completion_service import _budgets

    cid = _fresh_id()
    # Pre-fill budget beyond the limit
    _budgets[cid]["total_cost"] = 999.0
    _budgets[cid]["max_total_cost"] = 1.0

    manager = MagicMock()
    manager.request_llm_completion = AsyncMock(return_value="os.path")

    result = await get_code_completion(
        req=completion_req,
        conversation_sid=cid,
        user_id="user1",
        llm_config=llm_config,
        manager=manager,
        anti_hallucination=anti_hallucination,
    )
    assert result.status_code == 402
    assert result.stop_reason == "budget_exceeded"
    manager.request_llm_completion.assert_not_called()


@pytest.mark.asyncio
async def test_get_code_completion_sanitizes_markdown(
    completion_req, llm_config, manager, anti_hallucination
):
    manager.request_llm_completion = AsyncMock(return_value="```python\nos.path\n```")
    result = await get_code_completion(
        req=completion_req,
        conversation_sid=_fresh_id(),
        user_id="user1",
        llm_config=llm_config,
        manager=manager,
        anti_hallucination=anti_hallucination,
    )
    assert result.status_code == 200
    assert "```" not in result.completion
    assert "os.path" in result.completion


@pytest.mark.asyncio
async def test_get_code_completion_records_success_on_ok(
    completion_req, llm_config, manager, anti_hallucination
):
    """A successful completion must reset consecutive_errors via record_success."""
    cid = _fresh_id()
    record_error(cid, Exception("previous err"))
    assert _error_tracking[cid]["consecutive_errors"] == 1

    await get_code_completion(
        req=completion_req,
        conversation_sid=cid,
        user_id="user1",
        llm_config=llm_config,
        manager=manager,
        anti_hallucination=anti_hallucination,
    )
    assert _error_tracking[cid]["consecutive_errors"] == 0


@pytest.mark.asyncio
async def test_get_code_completion_empty_string_stop_reason(
    completion_req, llm_config, manager, anti_hallucination
):
    """An empty (but valid) LLM response should use stop_reason='empty'."""
    manager.request_llm_completion = AsyncMock(return_value="")
    result = await get_code_completion(
        req=completion_req,
        conversation_sid=_fresh_id(),
        user_id="user1",
        llm_config=llm_config,
        manager=manager,
        anti_hallucination=anti_hallucination,
    )
    assert result.status_code == 200
    assert result.stop_reason == "empty"


@pytest.mark.asyncio
async def test_get_code_completion_timeout_all_retries_exhausted(
    completion_req, llm_config, manager, anti_hallucination
):
    """TimeoutError on all attempts → 504 response."""
    manager.request_llm_completion = AsyncMock(side_effect=asyncio.TimeoutError())
    with patch(
        "backend.api.services.completion_service.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        result = await get_code_completion(
            req=completion_req,
            conversation_sid=_fresh_id(),
            user_id="user1",
            llm_config=llm_config,
            manager=manager,
            anti_hallucination=anti_hallucination,
        )
    assert result.status_code == 504
    assert result.stop_reason == "timeout"
    assert "Timed out" in result.error


@pytest.mark.asyncio
async def test_get_code_completion_non_retryable_error_permission(
    completion_req, llm_config, manager, anti_hallucination
):
    """Non-retryable error (PERMISSION_ERROR) should raise immediately."""
    error = Exception("403 Forbidden")
    manager.request_llm_completion = AsyncMock(side_effect=error)
    
    with patch(
        "backend.api.services.completion_service.ErrorRecoveryStrategy.classify_error"
    ) as mock_classify:
        mock_classify.return_value = ErrorType.PERMISSION_ERROR
        
        with pytest.raises(Exception, match="403 Forbidden"):
            await get_code_completion(
                req=completion_req,
                conversation_sid=_fresh_id(),
                user_id="user1",
                llm_config=llm_config,
                manager=manager,
                anti_hallucination=anti_hallucination,
            )


@pytest.mark.asyncio
async def test_get_code_completion_retryable_error_network(
    completion_req, llm_config, manager, anti_hallucination
):
    """Retryable error (NETWORK_ERROR) on first attempt, then success."""
    manager.request_llm_completion = AsyncMock(
        side_effect=[Exception("Connection lost"), "os.path"]
    )
    
    with patch(
        "backend.api.services.completion_service.ErrorRecoveryStrategy.classify_error"
    ) as mock_classify:
        mock_classify.side_effect = [
            ErrorType.NETWORK_ERROR,  # First attempt
        ]
        
        with patch(
            "backend.api.services.completion_service.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            result = await get_code_completion(
                req=completion_req,
                conversation_sid=_fresh_id(),
                user_id="user1",
                llm_config=llm_config,
                manager=manager,
                anti_hallucination=anti_hallucination,
            )
    assert result.status_code == 200
    assert "os.path" in result.completion


@pytest.mark.asyncio
async def test_get_code_completion_medium_risk_with_warning(
    completion_req, llm_config, manager, anti_hallucination
):
    """MEDIUM risk completions pass through with security_risk in result."""
    manager.request_llm_completion = AsyncMock(
        return_value="with open('file.txt') as f:\n    data = f.read()"
    )
    result = await get_code_completion(
        req=completion_req,
        conversation_sid=_fresh_id(),
        user_id="user1",
        llm_config=llm_config,
        manager=manager,
        anti_hallucination=anti_hallucination,
    )
    assert result.status_code == 200
    assert result.security_risk == "medium"
    # Note: warning is not included for MEDIUM risk, only for HIGH risk
    assert result.warning is None
