"""Tests for backend.controller.services.recovery_service – pure helpers and classification."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.controller.error_recovery import ErrorType
from backend.controller.services.recovery_service import RecoveryService


def _make_context() -> MagicMock:
    controller = MagicMock()
    controller.state = MagicMock()
    controller.state.last_error = None
    controller.event_stream = MagicMock()
    controller.circuit_breaker_service = MagicMock()
    controller.status_callback = None
    ctx = MagicMock()
    ctx.get_controller.return_value = controller
    ctx.emit_event = MagicMock()
    return ctx


def _make_retry_service() -> MagicMock:
    rs = MagicMock()
    rs.retry_count = 0
    rs.increment_retry_count.return_value = 1
    return rs


# ── _format_user_message ─────────────────────────────────────────────


class TestFormatUserMessage:
    def test_module_not_found(self):
        svc = RecoveryService(_make_context(), _make_retry_service())
        msg = svc._format_user_message(
            ModuleNotFoundError("numpy"), ErrorType.MODULE_NOT_FOUND
        )
        assert "module" in msg.lower()

    def test_runtime_crash(self):
        svc = RecoveryService(_make_context(), _make_retry_service())
        msg = svc._format_user_message(RuntimeError("crash"), ErrorType.RUNTIME_CRASH)
        assert "crashed" in msg.lower() or "runtime" in msg.lower()

    def test_unknown_error_fallback(self):
        svc = RecoveryService(_make_context(), _make_retry_service())
        msg = svc._format_user_message(ValueError("oops"), ErrorType.UNKNOWN_ERROR)
        assert "ValueError" in msg
        assert "oops" in msg

    def test_filesystem_error(self):
        svc = RecoveryService(_make_context(), _make_retry_service())
        msg = svc._format_user_message(OSError("disk"), ErrorType.FILESYSTEM_ERROR)
        assert "file system" in msg.lower() or "File system" in msg


# ── _extract_retry_delay ─────────────────────────────────────────────


class TestExtractRetryDelay:
    def test_seconds_pattern(self):
        svc = RecoveryService(_make_context(), _make_retry_service())
        result = svc._extract_retry_delay("Please retry in 38.6s")
        assert "minute" in result.lower() or "second" in result.lower()

    def test_minutes_pattern(self):
        svc = RecoveryService(_make_context(), _make_retry_service())
        result = svc._extract_retry_delay("retry after 5 minutes please")
        assert "5 minute" in result

    def test_no_match_returns_default(self):
        svc = RecoveryService(_make_context(), _make_retry_service())
        result = svc._extract_retry_delay("some random error message")
        assert result == "a few moments"

    def test_single_minute(self):
        svc = RecoveryService(_make_context(), _make_retry_service())
        result = svc._extract_retry_delay("retry after 1 minute")
        assert "1 minute" in result
        assert "minutes" not in result  # singular


# ── _format_llm_error ────────────────────────────────────────────────


class TestFormatLlmError:
    def test_generic_exception_returns_none(self):
        svc = RecoveryService(_make_context(), _make_retry_service())
        assert svc._format_llm_error(ValueError("nope")) is None

    def test_api_connection_error(self):
        from backend.llm.exceptions import APIConnectionError as ACE

        svc = RecoveryService(_make_context(), _make_retry_service())
        exc = ACE(message="connection refused")
        result = svc._format_llm_error(exc)
        assert result is not None
        assert "Connection Error" in result

    def test_authentication_error(self):
        from backend.llm.exceptions import AuthenticationError as AE

        svc = RecoveryService(_make_context(), _make_retry_service())
        exc = AE(message="invalid api key", llm_provider="test", model="test")
        result = svc._format_llm_error(exc)
        assert result is not None
        assert "Authentication" in result


# ── _format_rate_limit_error ─────────────────────────────────────────


class TestFormatRateLimitError:
    def test_quota_exceeded(self):
        svc = RecoveryService(_make_context(), _make_retry_service())
        result = svc._format_rate_limit_error(Exception("quota exceeded for free_tier"))
        assert "Quota" in result

    def test_standard_rate_limit(self):
        svc = RecoveryService(_make_context(), _make_retry_service())
        result = svc._format_rate_limit_error(
            Exception("rate limit reached retry in 30s")
        )
        assert "Rate Limit" in result


# ── _emit_recovery_event ─────────────────────────────────────────────


class TestEmitRecoveryEvent:
    def test_emits_event(self):
        ctx = _make_context()
        svc = RecoveryService(ctx, _make_retry_service())
        svc._emit_recovery_event("start", error_type="UNKNOWN_ERROR")
        ctx.emit_event.assert_called_once()
        obs = ctx.emit_event.call_args[0][0]
        assert "stage=start" in obs.content
        assert "UNKNOWN_ERROR" in obs.content

    def test_emit_failure_does_not_propagate(self):
        ctx = _make_context()
        ctx.emit_event.side_effect = RuntimeError("emit fail")
        svc = RecoveryService(ctx, _make_retry_service())
        svc._emit_recovery_event("test")  # should not raise


# ── _determine_runtime_status ────────────────────────────────────────


class TestDetermineRuntimeStatus:
    def test_auth_error(self):
        from backend.llm.exceptions import AuthenticationError as AE
        from backend.core.enums import RuntimeStatus

        svc = RecoveryService(_make_context(), _make_retry_service())
        exc = AE(message="bad key", llm_provider="test", model="test")
        status = svc._determine_runtime_status(exc)
        assert status == RuntimeStatus.ERROR_LLM_AUTHENTICATION

    def test_generic_error(self):
        from backend.core.enums import RuntimeStatus

        svc = RecoveryService(_make_context(), _make_retry_service())
        status = svc._determine_runtime_status(ValueError("oops"))
        assert status == RuntimeStatus.ERROR


# ── react_to_exception (integration-ish) ─────────────────────────────


class TestReactToException:
    @pytest.mark.asyncio
    async def test_authentication_error_skips_recovery(self):
        from backend.llm.exceptions import AuthenticationError as AE

        ctx = _make_context()
        controller = ctx.get_controller()
        controller.state.agent_state = "RUNNING"
        controller.set_agent_state_to = AsyncMock()
        controller.log_task_audit = AsyncMock()
        retry_svc = _make_retry_service()
        retry_svc.schedule_retry_after_failure = AsyncMock(return_value=False)
        svc = RecoveryService(ctx, retry_svc, max_retries=3)
        exc = AE(message="invalid key", llm_provider="test", model="test")
        await svc.react_to_exception(exc)
        # AuthenticationError skips recovery but still falls through to handle_non_recoverable
        controller.state.set_last_error.assert_called()

    @pytest.mark.asyncio
    async def test_max_retries_skips_recovery(self):
        ctx = _make_context()
        controller = ctx.get_controller()
        controller.state.agent_state = "RUNNING"
        controller.set_agent_state_to = AsyncMock()
        controller.log_task_audit = AsyncMock()
        retry_svc = _make_retry_service()
        retry_svc.retry_count = 5  # exceed max
        retry_svc.schedule_retry_after_failure = AsyncMock(return_value=False)
        svc = RecoveryService(ctx, retry_svc, max_retries=3)
        await svc.react_to_exception(RuntimeError("boom"))
        controller.state.set_last_error.assert_called()
