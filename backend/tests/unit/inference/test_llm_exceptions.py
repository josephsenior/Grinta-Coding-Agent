"""Tests for backend.inference.exceptions — LLM exception hierarchy and is_context_window_error."""

from __future__ import annotations

import pytest

from backend.inference.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadRequestError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    InternalServerError,
    LLMError,
    NotFoundError,
    OpenAIError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
    is_context_window_error,
)


# ── LLMError base ──────────────────────────────────────────────────────


class TestLLMError:
    def test_basic_instantiation(self):
        e = LLMError("something broke")
        assert str(e).startswith("something broke")
        assert e.message == "something broke"
        assert e.llm_provider is None
        assert e.model is None
        assert e.status_code is None

    def test_full_attributes(self):
        e = LLMError("fail", llm_provider="openai", model="gpt-4", status_code=500)
        assert e.llm_provider == "openai"
        assert e.model == "gpt-4"
        assert e.status_code == 500

    def test_kwargs_stored(self):
        e = LLMError("fail", extra_info="debug")
        assert e.kwargs == {"extra_info": "debug"}

    def test_is_exception(self):
        assert issubclass(LLMError, Exception)


# ── Subclass hierarchy ─────────────────────────────────────────────────


class TestSubclasses:
    @pytest.mark.parametrize(
        "cls",
        [
            APIConnectionError,
            APIError,
            AuthenticationError,
            BadRequestError,
            ContentPolicyViolationError,
            ContextWindowExceededError,
            InternalServerError,
            NotFoundError,
            RateLimitError,
            ServiceUnavailableError,
            Timeout,
            OpenAIError,
        ],
    )
    def test_inherits_from_llm_error(self, cls):
        assert issubclass(cls, LLMError)

    @pytest.mark.parametrize(
        "cls",
        [
            APIConnectionError,
            APIError,
            AuthenticationError,
            BadRequestError,
            ContentPolicyViolationError,
            ContextWindowExceededError,
            InternalServerError,
            NotFoundError,
            RateLimitError,
            ServiceUnavailableError,
            Timeout,
            OpenAIError,
        ],
    )
    def test_instantiation_with_message(self, cls):
        e = cls("test error")
        assert e.message == "test error"

    @pytest.mark.parametrize(
        "cls",
        [
            APIConnectionError,
            APIError,
            AuthenticationError,
            BadRequestError,
            ContentPolicyViolationError,
            ContextWindowExceededError,
            InternalServerError,
            NotFoundError,
            RateLimitError,
            ServiceUnavailableError,
            Timeout,
            OpenAIError,
        ],
    )
    def test_catches_as_llm_error(self, cls):
        with pytest.raises(LLMError):
            raise cls("boom")


# ── is_context_window_error ────────────────────────────────────────────


class TestIsContextWindowError:
    def test_context_window_exceeded_error_instance(self):
        exc = ContextWindowExceededError("overflow")
        assert is_context_window_error("whatever", exc) is True

    def test_prompt_is_too_long(self):
        assert is_context_window_error("prompt is too long", ValueError()) is True

    def test_input_length_max_tokens(self):
        msg = "input length and `max_tokens` exceed context limit"
        assert is_context_window_error(msg, ValueError()) is True

    def test_please_reduce_length(self):
        msg = "please reduce the length of either one"
        assert is_context_window_error(msg, ValueError()) is True

    def test_request_exceeds_context(self):
        msg = "the request exceeds the available context size"
        assert is_context_window_error(msg, ValueError()) is True

    def test_context_length_exceeded(self):
        assert is_context_window_error("context length exceeded", ValueError()) is True

    def test_sambanova_context(self):
        msg = "SambanovaException: maximum context length exceeded"
        assert is_context_window_error(msg, ValueError()) is True

    def test_sambanova_without_context_keyword_false(self):
        msg = "SambanovaException: rate limit hit"
        assert is_context_window_error(msg, ValueError()) is False

    def test_contextwindowexceedederror_in_string(self):
        msg = "ContextWindowExceededError: too many tokens"
        assert is_context_window_error(msg, ValueError()) is True

    def test_no_match(self):
        assert is_context_window_error("connection timeout", ValueError()) is False

    def test_case_insensitive(self):
        assert is_context_window_error("Prompt Is Too Long", ValueError()) is True

    def test_empty_string(self):
        assert is_context_window_error("", ValueError()) is False
