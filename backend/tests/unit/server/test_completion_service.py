"""Tests for backend.server.services.completion_service module.

Targets completion_service.py by testing:
- CompletionRequest and CompletionResult dataclasses
- Internal helper functions for tracking, budgets, security, and sanitization
- get_code_completion async function with all resilience features
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.controller.error_recovery import ErrorType
from backend.events.action import ActionSecurityRisk
from backend.server.services.completion_service import (
    CompletionRequest,
    CompletionResult,
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
    def test_record_error(self):
        record_error("conv1", Exception("Test error"))
        # Should increment consecutive_errors
        # (implementation detail: module-level tracking dict)

    def test_record_success(self):
        record_error("conv2", Exception("Error"))
        record_success("conv2")
        # Should reset consecutive_errors to 0


class TestCircuitBreaker:
    def test_check_circuit_breaker_ok(self):
        record_success("conv_ok")
        should_block, reason = check_circuit_breaker("conv_ok")
        assert should_block is False
        assert reason is None

    def test_check_circuit_breaker_consecutive_errors(self):
        for _ in range(6):
            record_error("conv_fail", Exception("Err"))
        should_block, reason = check_circuit_breaker("conv_fail")
        assert should_block is True
        assert "consecutive errors" in reason.lower()


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
        completion = "result = eval(user_input)"
        risk, warning = analyze_security(completion)
        assert risk == ActionSecurityRisk.HIGH
        assert "eval" in warning.lower()

    def test_high_risk_exec(self):
        completion = "exec(some_code)"
        risk, warning = analyze_security(completion)
        assert risk == ActionSecurityRisk.HIGH

    def test_high_risk_subprocess(self):
        completion = "subprocess.call(cmd, shell=True)"
        risk, warning = analyze_security(completion)
        assert risk == ActionSecurityRisk.HIGH

    def test_medium_risk_open(self):
        completion = "f = open('file.txt')"
        risk, warning = analyze_security(completion)
        assert risk == ActionSecurityRisk.MEDIUM
        assert "open" in warning.lower()

    def test_medium_risk_pickle(self):
        completion = "data = pickle.load(file)"
        risk, warning = analyze_security(completion)
        assert risk == ActionSecurityRisk.MEDIUM

    def test_low_risk(self):
        completion = "x = 1 + 2"
        risk, warning = analyze_security(completion)
        assert risk == ActionSecurityRisk.LOW
        assert warning is None


# -----------------------------------------------------------
# Sanitization
# -----------------------------------------------------------

class TestSanitization:
    def test_strip_markdown_fence(self):
        raw = "```python\nprint('hello')\n```"
        result = sanitize_completion(raw)
        assert result == "print('hello')"

    def test_truncate_long(self):
        raw = "x" * 2000
        result = sanitize_completion(raw)
        assert len(result) <= 1000

    def test_remove_hallucination_pattern(self):
        raw = "def foo():\n    pass\nI have created the function successfully."
        result = sanitize_completion(raw)
        # Should truncate at suspicious pattern
        assert "I have created" not in result

    def test_remove_multiple_hallucinations(self):
        raw = "code here\nI've written this code\nmore hallucination\nThe file has been created"
        result = sanitize_completion(raw)
        # Should truncate at first hallucination
        assert "I've written" not in result


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
        conversation_sid="conv_success",
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
        conversation_sid="conv_security",
        user_id="user1",
        llm_config=llm_config,
        manager=manager,
        anti_hallucination=anti_hallucination,
    )
    assert result.completion == ""
    assert result.stop_reason == "security_risk_high"
    assert result.warning is not None


@pytest.mark.asyncio
async def test_get_code_completion_hallucination_detected(
    completion_req, llm_config, manager, anti_hallucination
):
    manager.request_llm_completion = AsyncMock(return_value="code here")
    anti_hallucination.validate_response = MagicMock(return_value=(False, "Hallucination"))
    result = await get_code_completion(
        req=completion_req,
        conversation_sid="conv_hallucination",
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
    # First call times out, second succeeds
    manager.request_llm_completion = AsyncMock(
        side_effect=[asyncio.TimeoutError(), "os.path"]
    )
    with patch("backend.server.services.completion_service.COMPLETION_TIMEOUT", 0.1):
        result = await get_code_completion(
            req=completion_req,
            conversation_sid="conv_timeout",
            user_id="user1",
            llm_config=llm_config,
            manager=manager,
            anti_hallucination=anti_hallucination,
        )
    # Should succeed on retry
    assert result.status_code == 200


@pytest.mark.asyncio
async def test_get_code_completion_circuit_breaker_tripped(
    completion_req, llm_config, manager, anti_hallucination
):
    # Trip circuit breaker
    for _ in range(6):
        record_error("conv_breaker", Exception("Error"))
    result = await get_code_completion(
        req=completion_req,
        conversation_sid="conv_breaker",
        user_id="user1",
        llm_config=llm_config,
        manager=manager,
        anti_hallucination=anti_hallucination,
    )
    assert result.status_code == 503
    assert result.stop_reason == "circuit_breaker_tripped"


@pytest.mark.asyncio
async def test_get_code_completion_sanitizes_markdown(
    completion_req, llm_config, manager, anti_hallucination
):
    manager.request_llm_completion = AsyncMock(return_value="```python\nos.path\n```")
    result = await get_code_completion(
        req=completion_req,
        conversation_sid="conv_markdown",
        user_id="user1",
        llm_config=llm_config,
        manager=manager,
        anti_hallucination=anti_hallucination,
    )
    assert result.status_code == 200
    assert "```" not in result.completion
    assert "os.path" in result.completion
