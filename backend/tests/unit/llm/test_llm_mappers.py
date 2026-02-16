"""Tests for LLM exception mapping functions."""

import pytest

from backend.llm.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadRequestError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
)
from backend.llm.llm import (
    _map_anthropic_exception,
    _map_openai_exception,
    _map_provider_exception,
)


class TestMapOpenAIException:
    def test_authentication_error(self):
        """Test mapping OpenAI AuthenticationError."""
        try:
            import openai
            from unittest.mock import MagicMock

            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = openai.AuthenticationError(
                message="Invalid API key", response=mock_response, body=None
            )
            result = _map_openai_exception(exc, model="gpt-4")

            assert isinstance(result, AuthenticationError)
            assert result.model == "gpt-4"
            assert result.llm_provider == "openai"
        except ImportError:
            pytest.skip("OpenAI not installed")

    def test_rate_limit_error(self):
        """Test mapping OpenAI RateLimitError."""
        try:
            import openai
            from unittest.mock import MagicMock

            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = openai.RateLimitError(
                message="Rate limit exceeded", response=mock_response, body=None
            )
            result = _map_openai_exception(exc, model="gpt-4")

            assert isinstance(result, RateLimitError)
            assert result.model == "gpt-4"
            assert result.llm_provider == "openai"
        except ImportError:
            pytest.skip("OpenAI not installed")

    def test_api_connection_error(self):
        """Test mapping OpenAI APIConnectionError."""
        try:
            import openai

            exc = openai.APIConnectionError(request=None)
            result = _map_openai_exception(exc, model="gpt-4")

            assert isinstance(result, APIConnectionError)
            assert result.model == "gpt-4"
            assert result.llm_provider == "openai"
        except ImportError:
            pytest.skip("OpenAI not installed")

    def test_api_timeout_error(self):
        """Test mapping OpenAI APITimeoutError."""
        try:
            import openai
            from unittest.mock import MagicMock

            mock_request = MagicMock()
            exc = openai.APITimeoutError(request=mock_request)
            result = _map_openai_exception(exc, model="gpt-4")

            # APITimeoutError maps to APIConnectionError in the actual code
            assert isinstance(result, APIConnectionError)
            assert result.model == "gpt-4"
            assert result.llm_provider == "openai"
        except ImportError:
            pytest.skip("OpenAI not installed")

    def test_bad_request_error(self):
        """Test mapping OpenAI BadRequestError."""
        try:
            import openai
            from unittest.mock import MagicMock

            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = openai.BadRequestError(
                message="Invalid request", response=mock_response, body=None
            )
            result = _map_openai_exception(exc, model="gpt-4")

            assert isinstance(result, BadRequestError)
            assert result.model == "gpt-4"
            assert result.llm_provider == "openai"
        except ImportError:
            pytest.skip("OpenAI not installed")

    def test_bad_request_context_window(self):
        """Test mapping OpenAI BadRequestError with context window message."""
        try:
            import openai
            from unittest.mock import MagicMock

            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = openai.BadRequestError(
                message="context length exceeded", response=mock_response, body=None
            )
            result = _map_openai_exception(exc, model="gpt-4")

            assert isinstance(result, ContextWindowExceededError)
            assert result.model == "gpt-4"
            assert result.llm_provider == "openai"
        except ImportError:
            pytest.skip("OpenAI not installed")

    def test_internal_server_error(self):
        """Test mapping OpenAI InternalServerError."""
        try:
            import openai
            from unittest.mock import MagicMock

            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = openai.InternalServerError(
                message="Internal error", response=mock_response, body=None
            )
            result = _map_openai_exception(exc, model="gpt-4")

            assert isinstance(result, InternalServerError)
            assert result.model == "gpt-4"
            assert result.llm_provider == "openai"
        except ImportError:
            pytest.skip("OpenAI not installed")

    def test_api_status_error_503(self):
        """Test mapping OpenAI APIStatusError with 503."""
        try:
            import openai
            from unittest.mock import MagicMock

            mock_response = MagicMock()
            mock_response.status_code = 503
            mock_response.request = MagicMock()

            exc = openai.APIStatusError(
                message="Service unavailable",
                response=mock_response,
                body=None,
            )
            result = _map_openai_exception(exc, model="gpt-4")

            assert isinstance(result, ServiceUnavailableError)
            assert result.model == "gpt-4"
            assert result.llm_provider == "openai"
        except ImportError:
            pytest.skip("OpenAI not installed")

    def test_api_status_error_other(self):
        """Test mapping OpenAI APIStatusError with other status code."""
        try:
            import openai
            from unittest.mock import MagicMock

            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.request = MagicMock()

            exc = openai.APIStatusError(
                message="Server error",
                response=mock_response,
                body=None,
            )
            result = _map_openai_exception(exc, model="gpt-4")

            assert isinstance(result, APIError)
            assert result.model == "gpt-4"
            assert result.llm_provider == "openai"
            assert result.status_code == 500
        except ImportError:
            pytest.skip("OpenAI not installed")

    def test_non_openai_exception(self):
        """Test handling non-OpenAI exception."""
        exc = ValueError("Not an OpenAI exception")
        result = _map_openai_exception(exc, model="gpt-4")
        assert result is None

    def test_openai_not_installed(self, monkeypatch):
        """Test graceful handling when OpenAI not installed."""
        # Temporarily hide openai module
        import sys

        original_openai = sys.modules.get("openai")
        if original_openai:
            sys.modules["openai"] = None

        exc = ValueError("Some error")
        result = _map_openai_exception(exc, model="gpt-4")
        assert result is None

        # Restore
        if original_openai:
            sys.modules["openai"] = original_openai


class TestMapAnthropicException:
    def test_authentication_error(self):
        """Test mapping Anthropic AuthenticationError."""
        try:
            import anthropic
            from unittest.mock import MagicMock

            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = anthropic.AuthenticationError(
                message="Invalid API key", response=mock_response, body=None
            )
            result = _map_anthropic_exception(exc, model="claude-3")

            assert isinstance(result, AuthenticationError)
            assert result.model == "claude-3"
            assert result.llm_provider == "anthropic"
        except ImportError:
            pytest.skip("Anthropic not installed")

    def test_rate_limit_error(self):
        """Test mapping Anthropic RateLimitError."""
        try:
            import anthropic
            from unittest.mock import MagicMock

            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = anthropic.RateLimitError(
                message="Rate limit exceeded", response=mock_response, body=None
            )
            result = _map_anthropic_exception(exc, model="claude-3")

            assert isinstance(result, RateLimitError)
            assert result.model == "claude-3"
            assert result.llm_provider == "anthropic"
        except ImportError:
            pytest.skip("Anthropic not installed")

    def test_api_connection_error(self):
        """Test mapping Anthropic APIConnectionError."""
        try:
            import anthropic

            exc = anthropic.APIConnectionError(request=None)
            result = _map_anthropic_exception(exc, model="claude-3")

            assert isinstance(result, APIConnectionError)
            assert result.model == "claude-3"
            assert result.llm_provider == "anthropic"
        except ImportError:
            pytest.skip("Anthropic not installed")

    def test_api_timeout_error(self):
        """Test mapping Anthropic APITimeoutError."""
        try:
            import anthropic
            from unittest.mock import MagicMock

            mock_request = MagicMock()
            exc = anthropic.APITimeoutError(request=mock_request)
            result = _map_anthropic_exception(exc, model="claude-3")

            # APITimeoutError maps to APIConnectionError in the actual code
            assert isinstance(result, APIConnectionError)
            assert result.model == "claude-3"
            assert result.llm_provider == "anthropic"
        except ImportError:
            pytest.skip("Anthropic not installed")

    def test_bad_request_error(self):
        """Test mapping Anthropic BadRequestError."""
        try:
            import anthropic
            from unittest.mock import MagicMock

            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = anthropic.BadRequestError(
                message="Invalid request", response=mock_response, body=None
            )
            result = _map_anthropic_exception(exc, model="claude-3")

            assert isinstance(result, BadRequestError)
            assert result.model == "claude-3"
            assert result.llm_provider == "anthropic"
        except ImportError:
            pytest.skip("Anthropic not installed")

    def test_bad_request_context_window(self):
        """Test mapping Anthropic BadRequestError with context window message."""
        try:
            import anthropic
            from unittest.mock import MagicMock

            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = anthropic.BadRequestError(
                message="prompt is too long", response=mock_response, body=None
            )
            result = _map_anthropic_exception(exc, model="claude-3")

            assert isinstance(result, ContextWindowExceededError)
            assert result.model == "claude-3"
            assert result.llm_provider == "anthropic"
        except ImportError:
            pytest.skip("Anthropic not installed")

    def test_internal_server_error(self):
        """Test mapping Anthropic InternalServerError."""
        try:
            import anthropic
            from unittest.mock import MagicMock

            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = anthropic.InternalServerError(
                message="Internal error", response=mock_response, body=None
            )
            result = _map_anthropic_exception(exc, model="claude-3")

            assert isinstance(result, InternalServerError)
            assert result.model == "claude-3"
            assert result.llm_provider == "anthropic"
        except ImportError:
            pytest.skip("Anthropic not installed")

    def test_api_status_error_503(self):
        """Test mapping Anthropic APIStatusError with 503."""
        try:
            import anthropic
            from unittest.mock import MagicMock

            mock_response = MagicMock()
            mock_response.status_code = 503
            mock_response.request = MagicMock()

            exc = anthropic.APIStatusError(
                message="Service unavailable",
                response=mock_response,
                body=None,
            )
            result = _map_anthropic_exception(exc, model="claude-3")

            assert isinstance(result, ServiceUnavailableError)
            assert result.model == "claude-3"
            assert result.llm_provider == "anthropic"
        except ImportError:
            pytest.skip("Anthropic not installed")

    def test_api_status_error_other(self):
        """Test mapping Anthropic APIStatusError with other status code."""
        try:
            import anthropic
            from unittest.mock import MagicMock

            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.request = MagicMock()

            exc = anthropic.APIStatusError(
                message="Server error",
                response=mock_response,
                body=None,
            )
            result = _map_anthropic_exception(exc, model="claude-3")

            assert isinstance(result, APIError)
            assert result.model == "claude-3"
            assert result.llm_provider == "anthropic"
            assert result.status_code == 500
        except ImportError:
            pytest.skip("Anthropic not installed")

    def test_non_anthropic_exception(self):
        """Test handling non-Anthropic exception."""
        exc = ValueError("Not an Anthropic exception")
        result = _map_anthropic_exception(exc, model="claude-3")
        assert result is None


class TestMapProviderException:
    def test_already_llm_error(self):
        """Test that LLMError subclasses pass through unchanged."""
        exc = AuthenticationError("Already mapped", model="test-model")
        result = _map_provider_exception(exc, model="test-model")
        assert result is exc

    def test_google_quota_error(self):
        """Test mapping Google quota error."""

        class GoogleError(Exception):
            pass

        exc = GoogleError("quota exceeded")
        result = _map_provider_exception(exc, model="gemini-pro")

        assert isinstance(result, RateLimitError)
        assert result.model == "gemini-pro"
        assert result.llm_provider == "google"

    def test_google_rate_error(self):
        """Test mapping Google rate limit error."""

        class GoogleError(Exception):
            pass

        exc = GoogleError("rate limit")
        result = _map_provider_exception(exc, model="gemini-pro")

        assert isinstance(result, RateLimitError)
        assert result.model == "gemini-pro"

    def test_google_context_window_error(self):
        """Test mapping Google context window error."""

        class GoogleGenerativeAIError(Exception):
            pass

        exc = GoogleGenerativeAIError("context length exceeded")
        result = _map_provider_exception(exc, model="gemini-pro")

        assert isinstance(result, ContextWindowExceededError)
        assert result.model == "gemini-pro"
        assert result.llm_provider == "google"

    def test_google_generic_error(self):
        """Test mapping generic Google error."""

        class GoogleError(Exception):
            pass

        exc = GoogleError("some error")
        result = _map_provider_exception(exc, model="gemini-pro")

        assert isinstance(result, APIError)
        assert result.model == "gemini-pro"
        assert result.llm_provider == "google"

    def test_content_filter_error(self):
        """Test mapping content filter error."""
        exc = Exception("content_filter triggered")
        result = _map_provider_exception(exc, model="test-model")

        assert isinstance(result, ContentPolicyViolationError)
        assert result.model == "test-model"

    def test_content_policy_error(self):
        """Test mapping content policy error."""
        exc = Exception("content policy violation")
        result = _map_provider_exception(exc, model="test-model")

        assert isinstance(result, ContentPolicyViolationError)
        assert result.model == "test-model"

    def test_safety_error(self):
        """Test mapping safety error."""
        exc = Exception("safety filter triggered")
        result = _map_provider_exception(exc, model="test-model")

        assert isinstance(result, ContentPolicyViolationError)
        assert result.model == "test-model"

    def test_context_window_heuristic(self):
        """Test context window detection via heuristic."""
        exc = Exception("context length exceeded")
        result = _map_provider_exception(exc, model="test-model")

        assert isinstance(result, ContextWindowExceededError)
        assert result.model == "test-model"

    def test_generic_fallback(self):
        """Test fallback to APIError for unknown exceptions."""
        exc = Exception("Unknown error")
        result = _map_provider_exception(exc, model="test-model")

        assert isinstance(result, APIError)
        assert result.model == "test-model"
        assert "Unknown error" in str(result)

    def test_openai_delegation(self):
        """Test that OpenAI exceptions are delegated to _map_openai_exception."""
        try:
            import openai
            from unittest.mock import MagicMock

            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = openai.RateLimitError(
                message="Rate limit", response=mock_response, body=None
            )
            result = _map_provider_exception(exc, model="gpt-4")

            assert isinstance(result, RateLimitError)
            assert result.llm_provider == "openai"
        except ImportError:
            pytest.skip("OpenAI not installed")

    def test_anthropic_delegation(self):
        """Test that Anthropic exceptions are delegated to _map_anthropic_exception."""
        try:
            import anthropic
            from unittest.mock import MagicMock

            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = anthropic.RateLimitError(
                message="Rate limit", response=mock_response, body=None
            )
            result = _map_provider_exception(exc, model="claude-3")

            assert isinstance(result, RateLimitError)
            assert result.llm_provider == "anthropic"
        except ImportError:
            pytest.skip("Anthropic not installed")
