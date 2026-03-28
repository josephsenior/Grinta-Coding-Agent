"""Tests for backend.gateway.utils.error_formatter — error formatting helpers."""

from __future__ import annotations


from backend.gateway.utils.error_patterns import (
    check_auth_pattern,
    check_file_not_found_pattern,
    check_network_pattern,
    check_permission_pattern,
    check_rate_limit_pattern,
)
from backend.core.enums import ErrorCategory, ErrorSeverity
from backend.core.errors import (
    AgentRuntimeUnavailableError,
    AgentStuckInLoopError,
    LLMContextWindowExceedError,
    LLMMalformedActionError,
    LLMNoResponseError,
    UserCancelledError,
)
from backend.gateway.utils.error_formatter import (
    ErrorAction,
    UserFriendlyError,
    format_agent_stuck_error,
    format_context_window_error,
    format_error_for_user,
    format_llm_authentication_error,
    format_llm_no_response_error,
    format_malformed_action_error,
    format_network_error,
    format_rate_limit_error,
    format_runtime_unavailable_error,
    format_user_cancelled_error,
    safe_format_error,
    to_dict,
)


# ---------------------------------------------------------------------------
# ErrorAction
# ---------------------------------------------------------------------------


class TestErrorAction:
    def test_basic(self):
        a = ErrorAction(label="Retry", action_type="retry")
        assert a.label == "Retry"
        assert a.action_type == "retry"
        assert a.url is None
        assert a.highlight is False
        assert a.data == {}

    def test_to_dict(self):
        a = ErrorAction("Go", "nav", url="/x", highlight=True, data={"k": 1})
        d = a.to_dict()
        assert d["label"] == "Go"
        assert d["type"] == "nav"
        assert d["url"] == "/x"
        assert d["highlight"] is True
        assert d["data"] == {"k": 1}


# ---------------------------------------------------------------------------
# UserFriendlyError
# ---------------------------------------------------------------------------


class TestUserFriendlyError:
    def test_defaults(self):
        e = UserFriendlyError(title="T", message="M")
        assert e.title == "T"
        assert e.severity == ErrorSeverity.ERROR
        assert e.category == ErrorCategory.SYSTEM
        assert e.can_retry is False
        assert e.actions == []
        assert e.metadata == {}

    def test_to_dict_keys(self):
        e = UserFriendlyError(title="T", message="M")
        d = e.to_dict()
        required_keys = {
            "title",
            "message",
            "severity",
            "category",
            "icon",
            "suggestion",
            "actions",
            "technical_details",
            "error_code",
            "can_retry",
            "retry_delay",
            "help_url",
            "reassurance",
            "metadata",
            "timestamp",
        }
        assert required_keys.issubset(d.keys())

    def test_actions_serialized(self):
        a = ErrorAction("X", "y")
        e = UserFriendlyError(title="T", message="M", actions=[a])
        d = e.to_dict()
        assert len(d["actions"]) == 1
        assert d["actions"][0]["label"] == "X"


# ---------------------------------------------------------------------------
# Pattern checkers
# ---------------------------------------------------------------------------


class TestPatternCheckers:
    def test_rate_limit(self):
        assert check_rate_limit_pattern("rate limit exceeded") is True
        assert check_rate_limit_pattern("too many requests") is True
        assert check_rate_limit_pattern("normal error") is False

    def test_auth_pattern(self):
        assert check_auth_pattern("authentication failed") is True
        assert check_auth_pattern("invalid token") is True
        assert check_auth_pattern("check your api key") is True
        assert check_auth_pattern("normal") is False

    def test_network_pattern(self):
        assert check_network_pattern("connection refused") is True
        assert check_network_pattern("timeout error") is True
        assert check_network_pattern("normal") is False

    def test_file_not_found_pattern(self):
        assert check_file_not_found_pattern("file not found") is True
        assert check_file_not_found_pattern("no such file or directory") is True
        assert check_file_not_found_pattern("normal") is False

    def test_permission_pattern(self):
        assert check_permission_pattern("permission denied") is True
        assert check_permission_pattern("forbidden access") is True
        assert check_permission_pattern("normal") is False


# ---------------------------------------------------------------------------
# Specific formatters
# ---------------------------------------------------------------------------


class TestSpecificFormatters:
    def test_format_llm_no_response(self):
        err = LLMNoResponseError("timeout")
        result = format_llm_no_response_error(err)
        assert result.error_code == "LLM_NO_RESPONSE"
        assert result.can_retry is True

    def test_format_context_window(self):
        err = LLMContextWindowExceedError("too long")
        result = format_context_window_error(err)
        assert result.error_code == "CONTEXT_WINDOW_EXCEEDED"
        assert result.can_retry is False

    def test_format_agent_stuck(self):
        err = AgentStuckInLoopError("looping")
        result = format_agent_stuck_error(err)
        assert result.error_code == "AGENT_STUCK_IN_LOOP"

    def test_format_runtime_unavailable(self):
        err = AgentRuntimeUnavailableError("down")
        result = format_runtime_unavailable_error(err)
        assert result.error_code == "RUNTIME_UNAVAILABLE"
        assert result.can_retry is True

    def test_format_malformed_action(self):
        err = LLMMalformedActionError("bad json")
        result = format_malformed_action_error(err)
        assert result.error_code == "MALFORMED_ACTION"

    def test_format_user_cancelled(self):
        err = UserCancelledError("nope")
        result = format_user_cancelled_error(err)
        assert result.error_code == "USER_CANCELLED"
        assert result.can_retry is False

    def test_format_llm_auth_detects_anthropic(self):
        err = Exception("Anthropic API key invalid")
        result = format_llm_authentication_error(err)
        assert "Anthropic" in result.message

    def test_format_llm_auth_detects_openai(self):
        err = Exception("OpenAI key error")
        result = format_llm_authentication_error(err)
        assert "OpenAI" in result.message

    def test_format_rate_limit(self):
        err = Exception("rate limited")
        result = format_rate_limit_error(err)
        assert result.error_code == "RATE_LIMIT_EXCEEDED"

    def test_format_network_error(self):
        err = Exception("connection refused")
        result = format_network_error(err)
        assert result.error_code == "NETWORK_ERROR"


# ---------------------------------------------------------------------------
# format_error_for_user  (main entry point)
# ---------------------------------------------------------------------------


class TestFormatErrorForUser:
    def test_mapped_error_type(self):
        err = LLMNoResponseError("timeout")
        d = format_error_for_user(err)
        assert d["error_code"] == "LLM_NO_RESPONSE"

    def test_pattern_based_error(self):
        err = RuntimeError("rate limit hit")
        d = format_error_for_user(err)
        assert d["error_code"] == "RATE_LIMIT_EXCEEDED"

    def test_generic_fallback(self):
        err = RuntimeError("totally unknown error")
        d = format_error_for_user(err)
        assert d["error_code"] == "RUNTIMEERROR"

    def test_context_merged(self):
        err = LLMNoResponseError("timeout")
        d = format_error_for_user(err, context={"user_id": "u1"})
        assert d["metadata"]["user_id"] == "u1"


# ---------------------------------------------------------------------------
# safe_format_error
# ---------------------------------------------------------------------------


class TestSafeFormatError:
    def test_returns_dict(self):
        err = RuntimeError("boom")
        d = safe_format_error(err)
        assert isinstance(d, dict)
        assert "title" in d

    def test_never_raises(self):
        # Even with a weird error, it should not raise
        err = RuntimeError("weird")
        result = safe_format_error(err)
        assert result is not None


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------


class TestToDict:
    def test_basic(self):
        err = ValueError("oops")
        d = to_dict(err)
        assert d["type"] == "ValueError"
        assert d["message"] == "oops"
