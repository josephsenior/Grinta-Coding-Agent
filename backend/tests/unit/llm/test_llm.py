"""Comprehensive tests for backend.llm.llm - LLM integration and exception mapping."""

from unittest.mock import AsyncMock, MagicMock, Mock, patch, call

import pytest

from backend.llm.llm import (
    _map_openai_exception,
    _map_anthropic_exception,
    _map_provider_exception,
    LLM,
)
from backend.llm.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadRequestError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    InternalServerError,
    LLMError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)


class TestMapOpenAIException:
    """Tests for _map_openai_exception() function."""

    def test_maps_authentication_error(self):
        """Test mapping OpenAI AuthenticationError."""
        try:
            import openai
            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = openai.AuthenticationError(message="Invalid API key", response=mock_response, body=None)
            result = _map_openai_exception(exc, "gpt-4")
            
            assert isinstance(result, AuthenticationError)
            assert result.model == "gpt-4"
            assert result.llm_provider == "openai"
        except ImportError:
            pytest.skip("OpenAI not installed")

    def test_maps_rate_limit_error(self):
        """Test mapping OpenAI RateLimitError."""
        try:
            import openai
            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = openai.RateLimitError(message="Rate limit exceeded", response=mock_response, body=None)
            result = _map_openai_exception(exc, "gpt-4")
            
            assert isinstance(result, RateLimitError)
            assert result.model == "gpt-4"
        except ImportError:
            pytest.skip("OpenAI not installed")

    def test_maps_api_connection_error(self):
        """Test mapping OpenAI APIConnectionError."""
        try:
            import openai
            exc = openai.APIConnectionError(request=MagicMock())
            result = _map_openai_exception(exc, "gpt-4")
            
            assert isinstance(result, APIConnectionError)
        except ImportError:
            pytest.skip("OpenAI not installed")

    def test_maps_timeout_error(self):
        """Test mapping OpenAI APITimeoutError."""
        try:
            import openai
            exc = openai.APITimeoutError(request=MagicMock())
            result = _map_openai_exception(exc, "gpt-4")
            
            assert isinstance(result, Timeout)
        except ImportError:
            pytest.skip("OpenAI not installed")

    def test_maps_bad_request_error(self):
        """Test mapping OpenAI BadRequestError."""
        try:
            import openai
            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = openai.BadRequestError(message="Invalid request", response=mock_response, body=None)
            result = _map_openai_exception(exc, "gpt-4")
            
            assert isinstance(result, BadRequestError)
        except ImportError:
            pytest.skip("OpenAI not installed")

    def test_maps_context_window_error(self):
        """Test mapping context window exceeded in BadRequestError."""
        try:
            import openai
            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = openai.BadRequestError(
                message="maximum context length exceeded",
                response=mock_response,
                body=None
            )
            result = _map_openai_exception(exc, "gpt-4")
            
            assert isinstance(result, ContextWindowExceededError)
        except ImportError:
            pytest.skip("OpenAI not installed")

    def test_maps_internal_server_error(self):
        """Test mapping OpenAI InternalServerError."""
        try:
            import openai
            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = openai.InternalServerError(message="Server error", response=mock_response, body=None)
            result = _map_openai_exception(exc, "gpt-4")
            
            assert isinstance(result, InternalServerError)
        except ImportError:
            pytest.skip("OpenAI not installed")

    def test_maps_api_status_error_503(self):
        """Test mapping APIStatusError with 503 to ServiceUnavailable."""
        try:
            import openai
            mock_response = MagicMock()
            mock_response.status_code = 503
            mock_response.request = MagicMock()
            exc = openai.APIStatusError(message="Service unavailable", response=mock_response, body=None)
            exc.status_code = 503
            result = _map_openai_exception(exc, "gpt-4")
            
            assert isinstance(result, ServiceUnavailableError)
        except ImportError:
            pytest.skip("OpenAI not installed")

    def test_maps_api_status_error_other(self):
        """Test mapping APIStatusError with other status codes."""
        try:
            import openai
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.request = MagicMock()
            exc = openai.APIStatusError(message="Bad request", response=mock_response, body=None)
            exc.status_code = 400
            result = _map_openai_exception(exc, "gpt-4")
            
            assert isinstance(result, APIError)
            assert result.status_code == 400
        except ImportError:
            pytest.skip("OpenAI not installed")

    def test_returns_none_for_unknown_exception(self):
        """Test returns None for non-OpenAI exceptions."""
        exc = ValueError("Not an OpenAI exception")
        result = _map_openai_exception(exc, "gpt-4")
        assert result is None

    def test_returns_none_when_openai_not_installed(self):
        """Test returns None when openai package not available."""
        with patch.dict("sys.modules", {"openai": None}):
            exc = Exception("Test")
            result = _map_openai_exception(exc, "gpt-4")
            assert result is None


class TestMapAnthropicException:
    """Tests for _map_anthropic_exception() function."""

    def test_maps_authentication_error(self):
        """Test mapping Anthropic AuthenticationError."""
        try:
            import anthropic
            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = anthropic.AuthenticationError(message="Invalid API key", response=mock_response, body=None)
            result = _map_anthropic_exception(exc, "claude-3")
            
            assert isinstance(result, AuthenticationError)
            assert result.model == "claude-3"
            assert result.llm_provider == "anthropic"
        except ImportError:
            pytest.skip("Anthropic not installed")

    def test_maps_rate_limit_error(self):
        """Test mapping Anthropic RateLimitError."""
        try:
            import anthropic
            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = anthropic.RateLimitError(message="Rate limited", response=mock_response, body=None)
            result = _map_anthropic_exception(exc, "claude-3")
            
            assert isinstance(result, RateLimitError)
        except ImportError:
            pytest.skip("Anthropic not installed")

    def test_maps_api_connection_error(self):
        """Test mapping Anthropic APIConnectionError."""
        try:
            import anthropic
            exc = anthropic.APIConnectionError(request=MagicMock())
            result = _map_anthropic_exception(exc, "claude-3")
            
            assert isinstance(result, APIConnectionError)
        except ImportError:
            pytest.skip("Anthropic not installed")

    def test_maps_timeout_error(self):
        """Test mapping Anthropic APITimeoutError."""
        try:
            import anthropic
            exc = anthropic.APITimeoutError(request=MagicMock())
            result = _map_anthropic_exception(exc, "claude-3")
            
            assert isinstance(result, Timeout)
        except ImportError:
            pytest.skip("Anthropic not installed")

    def test_maps_bad_request_error(self):
        """Test mapping Anthropic BadRequestError."""
        try:
            import anthropic
            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = anthropic.BadRequestError(message="Invalid", response=mock_response, body=None)
            result = _map_anthropic_exception(exc, "claude-3")
            
            assert isinstance(result, BadRequestError)
        except ImportError:
            pytest.skip("Anthropic not installed")

    def test_maps_context_window_error(self):
        """Test mapping context window exceeded."""
        try:
            import anthropic
            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = anthropic.BadRequestError(
                message="maximum context length exceeded",
                response=mock_response,
                body=None
            )
            result = _map_anthropic_exception(exc, "claude-3")
            
            assert isinstance(result, ContextWindowExceededError)
        except ImportError:
            pytest.skip("Anthropic not installed")

    def test_returns_none_for_unknown_exception(self):
        """Test returns None for non-Anthropic exceptions."""
        exc = ValueError("Not an Anthropic exception")
        result = _map_anthropic_exception(exc, "claude-3")
        assert result is None


class TestMapProviderException:
    """Tests for _map_provider_exception() function."""

    def test_passes_through_llm_error(self):
        """Test that LLMError subclasses pass through unchanged."""
        exc = AuthenticationError("Test", model="gpt-4")
        result = _map_provider_exception(exc, "gpt-4")
        assert result is exc

    def test_maps_generic_google_error(self):
        """Test mapping generic Google Generative AI error."""
        # Create exception with 'google' in class name to trigger Google error detection
        class GoogleGenerativeAIError(Exception):
            pass
        
        exc = GoogleGenerativeAIError("Model inference failed")
        result = _map_provider_exception(exc, "gemini-pro")
        
        assert isinstance(result, APIError)
        assert result.llm_provider == "google"

    def test_maps_google_quota_error(self):
        """Test mapping Google quota/rate limit error."""
        # Create exception with 'google' in class name
        class GoogleAPIError(Exception):
            pass
        
        exc = GoogleAPIError("Quota exceeded for generativeai")
        result = _map_provider_exception(exc, "gemini-pro")
        
        assert isinstance(result, RateLimitError)
        assert result.llm_provider == "google"

    def test_maps_google_context_window_error(self):
        """Test mapping Google context window error."""
        # Create exception with 'google' in class name
        class GoogleAPIError(Exception):
            pass
        
        exc = GoogleAPIError("maximum context length exceeded")
        result = _map_provider_exception(exc, "gemini-pro")
        
        assert isinstance(result, ContextWindowExceededError)
        assert result.llm_provider == "google"

    def test_maps_content_filter_error(self):
        """Test mapping content filter errors."""
        exc = Exception("Response blocked by content_filter")
        result = _map_provider_exception(exc, "gpt-4")
        
        assert isinstance(result, ContentPolicyViolationError)

    def test_maps_content_policy_error(self):
        """Test mapping content policy errors."""
        exc = Exception("Violates content policy")
        result = _map_provider_exception(exc, "gpt-4")
        
        assert isinstance(result, ContentPolicyViolationError)

    def test_maps_safety_error(self):
        """Test mapping safety filter errors."""
        exc = Exception("Blocked by safety filters")
        result = _map_provider_exception(exc, "gemini-pro")
        
        assert isinstance(result, ContentPolicyViolationError)

    def test_maps_generic_context_window_error(self):
        """Test mapping generic context window errors."""
        exc = Exception("Context length exceeded")
        result = _map_provider_exception(exc, "unknown-model")
        
        assert isinstance(result, ContextWindowExceededError)

    def test_fallback_to_api_error(self):
        """Test unknown exceptions fallback to APIError."""
        exc = Exception("Some random error")
        result = _map_provider_exception(exc, "test-model")
        
        assert isinstance(result, APIError)
        assert result.model == "test-model"

    def test_preserves_error_message(self):
        """Test that error messages are preserved."""
        exc = Exception("Detailed error message")
        result = _map_provider_exception(exc, "test-model")
        
        assert "Detailed error message" in str(result)


class TestLLMInit:
    """Tests for LLM.__init__() initialization."""

    @patch("backend.llm.llm.get_direct_client")
    @patch("backend.llm.llm.get_features")
    @patch("backend.llm.model_aliases.get_alias_manager")
    @patch("backend.llm.provider_resolver.get_resolver")
    def test_init_basic(self, mock_resolver, mock_alias_mgr, mock_features, mock_client):
        """Test basic LLM initialization."""
        # Setup mocks
        mock_config = Mock()
        mock_config.model = "gpt-4"
        mock_config.base_url = "https://api.openai.com"
        mock_config.api_key = "test-key"
        mock_config.native_tool_calling = None
        mock_config.max_input_tokens = None
        mock_config.max_output_tokens = None
        mock_config.custom_tokenizer = None
        
        mock_alias_mgr.return_value.resolve_alias.return_value = "gpt-4"
        mock_resolver.return_value.is_local_model.return_value = False
        mock_resolver.return_value.resolve_base_url.return_value = None
        
        mock_feature = Mock()
        mock_feature.supports_function_calling = True
        mock_feature.max_input_tokens = 8000
        mock_feature.max_output_tokens = 4000
        mock_features.return_value = mock_feature
        
        with patch.object(LLM, "_extract_api_key", return_value="test-key"):
            llm = LLM(mock_config, "test-service")
        
        assert llm.service_id == "test-service"
        assert llm.config.model == "gpt-4"
        mock_client.assert_called_once()

    @patch("backend.llm.llm.get_direct_client")
    @patch("backend.llm.llm.get_features")
    @patch("backend.llm.model_aliases.get_alias_manager")
    @patch("backend.llm.provider_resolver.get_resolver")
    def test_init_with_alias_resolution(self, mock_resolver, mock_alias_mgr, mock_features, mock_client):
        """Test initialization with model alias resolution."""
        mock_config = Mock()
        mock_config.model = "gpt4"
        mock_config.base_url = "https://api.openai.com"
        mock_config.api_key = "test-key"
        mock_config.native_tool_calling = None
        mock_config.max_input_tokens = None
        mock_config.max_output_tokens = None
        mock_config.custom_tokenizer = None
        
        # Alias resolves to full name
        mock_alias_mgr.return_value.resolve_alias.return_value = "gpt-4"
        mock_resolver.return_value.is_local_model.return_value = False
        mock_resolver.return_value.resolve_base_url.return_value = None
        
        mock_features.return_value = Mock(
            supports_function_calling=True,
            max_input_tokens=8000,
            max_output_tokens=4000
        )
        
        with patch.object(LLM, "_extract_api_key", return_value="test-key"):
            llm = LLM(mock_config, "test-service")
        
        # Config should be updated with resolved model
        assert llm.config.model == "gpt-4"

    @patch("backend.llm.llm.get_direct_client")
    @patch("backend.llm.llm.get_features")
    @patch("backend.llm.model_aliases.get_alias_manager")
    @patch("backend.llm.provider_resolver.get_resolver")
    def test_init_auto_discovers_base_url(self, mock_resolver, mock_alias_mgr, mock_features, mock_client):
        """Test auto-discovery of base_url for local models."""
        mock_config = Mock()
        mock_config.model = "ollama/llama2"
        mock_config.base_url = None
        mock_config.api_key = None
        mock_config.native_tool_calling = None
        mock_config.max_input_tokens = None
        mock_config.max_output_tokens = None
        mock_config.custom_tokenizer = None
        
        mock_alias_mgr.return_value.resolve_alias.return_value = "ollama/llama2"
        
        # Resolver discovers local endpoint
        mock_resolver_inst = mock_resolver.return_value
        mock_resolver_inst.resolve_base_url.return_value = "http://localhost:11434"
        mock_resolver_inst.is_local_model.return_value = True
        mock_resolver_inst.is_local_model.return_value = True
        
        mock_features.return_value = Mock(
            supports_function_calling=False,
            max_input_tokens=4096,
            max_output_tokens=2048
        )
        
        with patch.object(LLM, "_extract_api_key", return_value=None):
            llm = LLM(mock_config, "test-service")
        
        # base_url should be auto-discovered
        assert llm.config.base_url == "http://localhost:11434"

    @patch("backend.llm.llm.get_direct_client")
    @patch("backend.llm.llm.get_features")
    @patch("backend.llm.model_aliases.get_alias_manager")
    @patch("backend.llm.provider_resolver.get_resolver")
    def test_init_local_model_no_api_key_required(self, mock_resolver, mock_alias_mgr, mock_features, mock_client):
        """Test local models don't require API key."""
        mock_config = Mock()
        mock_config.model = "ollama/llama2"
        mock_config.base_url = "http://localhost:11434"
        mock_config.api_key = None
        mock_config.native_tool_calling = None
        mock_config.max_input_tokens = None
        mock_config.max_output_tokens = None
        mock_config.custom_tokenizer = None
        
        mock_alias_mgr.return_value.resolve_alias.return_value = "ollama/llama2"
        mock_resolver.return_value.is_local_model.return_value = True
        mock_resolver.return_value.resolve_base_url.return_value = None
        
        mock_features.return_value = Mock(
            supports_function_calling=False,
            max_input_tokens=4096,
            max_output_tokens=2048
        )
        
        with patch.object(LLM, "_extract_api_key", return_value=None):
            # Should not raise
            llm = LLM(mock_config, "test-service")
            assert llm.service_id == "test-service"

    @patch("backend.llm.llm.get_direct_client")
    @patch("backend.llm.llm.get_features")
    @patch("backend.llm.model_aliases.get_alias_manager")
    @patch("backend.llm.provider_resolver.get_resolver")
    def test_init_cloud_model_requires_api_key(self, mock_resolver, mock_alias_mgr, mock_features, mock_client):
        """Test cloud models require API key."""
        mock_config = Mock()
        mock_config.model = "gpt-4"
        mock_config.base_url = None
        mock_config.api_key = None
        mock_config.native_tool_calling = None
        mock_config.max_input_tokens = None
        mock_config.max_output_tokens = None
        mock_config.custom_tokenizer = None
        
        mock_alias_mgr.return_value.resolve_alias.return_value = "gpt-4"
        mock_resolver.return_value.is_local_model.return_value = False
        mock_resolver.return_value.resolve_base_url.return_value = None
        
        with patch.object(LLM, "_extract_api_key", return_value=None):
            with pytest.raises(AuthenticationError) as exc_info:
                LLM(mock_config, "test-service")
            
            assert "No API key provided" in str(exc_info.value)

    @patch("backend.llm.llm.get_direct_client")
    @patch("backend.llm.llm.get_features")
    @patch("backend.llm.model_aliases.get_alias_manager")
    @patch("backend.llm.provider_resolver.get_resolver")
    def test_init_with_metrics(self, mock_resolver, mock_alias_mgr, mock_features, mock_client):
        """Test initialization with custom metrics."""
        mock_config = Mock()
        mock_config.model = "gpt-4"
        mock_config.base_url = "https://api.openai.com"
        mock_config.api_key = "test-key"
        mock_config.native_tool_calling = None
        mock_config.max_input_tokens = None
        mock_config.max_output_tokens = None
        mock_config.custom_tokenizer = None
        
        mock_alias_mgr.return_value.resolve_alias.return_value = "gpt-4"
        mock_resolver.return_value.is_local_model.return_value = False
        mock_resolver.return_value.resolve_base_url.return_value = None
        
        mock_features.return_value = Mock(
            supports_function_calling=True,
            max_input_tokens=8000,
            max_output_tokens=4000
        )
        
        custom_metrics = Mock()
        
        with patch.object(LLM, "_extract_api_key", return_value="test-key"):
            llm = LLM(mock_config, "test-service", metrics=custom_metrics)
        
        assert llm.metrics is custom_metrics

    @patch("backend.llm.llm.get_direct_client")
    @patch("backend.llm.llm.get_features")
    @patch("backend.llm.model_aliases.get_alias_manager")
    @patch("backend.llm.provider_resolver.get_resolver")
    def test_init_function_calling_configuration(self, mock_resolver, mock_alias_mgr, mock_features, mock_client):
        """Test function calling is properly configured."""
        mock_config = Mock()
        mock_config.model = "gpt-4"
        mock_config.base_url = "https://api.openai.com"
        mock_config.api_key = "test-key"
        mock_config.native_tool_calling = True  # Explicitly enabled
        mock_config.max_input_tokens = None
        mock_config.max_output_tokens = None
        mock_config.custom_tokenizer = None
        
        mock_alias_mgr.return_value.resolve_alias.return_value = "gpt-4"
        mock_resolver.return_value.is_local_model.return_value = False
        mock_resolver.return_value.resolve_base_url.return_value = None
        
        mock_features.return_value = Mock(
            supports_function_calling=True,
            max_input_tokens=8000,
            max_output_tokens=4000
        )
        
        with patch.object(LLM, "_extract_api_key", return_value="test-key"):
            llm = LLM(mock_config, "test-service")
        
        assert llm._function_calling_active is True

    @patch("backend.llm.llm.get_direct_client")
    @patch("backend.llm.llm.get_features")
    @patch("backend.llm.model_aliases.get_alias_manager")
    @patch("backend.llm.provider_resolver.get_resolver")
    def test_init_handles_feature_lookup_failure(self, mock_resolver, mock_alias_mgr, mock_features, mock_client):
        """Test graceful handling of feature lookup failures."""
        mock_config = Mock()
        mock_config.model = "unknown-model"
        mock_config.base_url = "http://localhost:8000"
        mock_config.api_key = None
        mock_config.native_tool_calling = None
        mock_config.max_input_tokens = None
        mock_config.max_output_tokens = None
        mock_config.custom_tokenizer = None
        
        mock_alias_mgr.return_value.resolve_alias.return_value = "unknown-model"
        mock_resolver.return_value.is_local_model.return_value = True
        mock_resolver.return_value.resolve_base_url.return_value = None
        mock_features.side_effect = KeyError("Model not found")
        
        with patch.object(LLM, "_extract_api_key", return_value=None):
            # Should not raise, should use defaults
            llm = LLM(mock_config, "test-service")
            assert llm._function_calling_active is False

    @patch("backend.llm.llm.get_direct_client")
    @patch("backend.llm.llm.get_features")
    @patch("backend.llm.model_aliases.get_alias_manager")
    @patch("backend.llm.provider_resolver.get_resolver")
    def test_init_config_is_deep_copied(self, mock_resolver, mock_alias_mgr, mock_features, mock_client):
        """Test that config is deep copied on init."""
        mock_config = Mock()
        mock_config.model = "gpt-4"
        mock_config.base_url = "https://api.openai.com"
        mock_config.api_key = "test-key"
        mock_config.native_tool_calling = None
        mock_config.max_input_tokens = None
        mock_config.max_output_tokens = None
        mock_config.custom_tokenizer = None
        
        mock_alias_mgr.return_value.resolve_alias.return_value = "gpt-4"
        mock_resolver.return_value.is_local_model.return_value = False
        mock_resolver.return_value.resolve_base_url.return_value = None
        
        mock_features.return_value = Mock(
            supports_function_calling=True,
            max_input_tokens=8000,
            max_output_tokens=4000
        )
        
        with patch("backend.llm.llm.copy.deepcopy") as mock_deepcopy:
            mock_deepcopy.return_value = mock_config
            with patch.object(LLM, "_extract_api_key", return_value="test-key"):
                llm = LLM(mock_config, "test-service")
            
            mock_deepcopy.assert_called_once_with(mock_config)


class TestLLMProperties:
    """Tests for LLM property accessors."""

    @patch("backend.llm.llm.get_direct_client")
    @patch("backend.llm.llm.get_features")
    @patch("backend.llm.model_aliases.get_alias_manager")
    @patch("backend.llm.provider_resolver.get_resolver")
    def test_features_property(self, mock_resolver, mock_alias_mgr, mock_features, mock_client):
        """Test features property returns cached features."""
        mock_config = Mock()
        mock_config.model = "gpt-4"
        mock_config.base_url = "https://api.openai.com"
        mock_config.api_key = "test-key"
        mock_config.native_tool_calling = None
        mock_config.max_input_tokens = None
        mock_config.max_output_tokens = None
        mock_config.custom_tokenizer = None
        
        mock_alias_mgr.return_value.resolve_alias.return_value = "gpt-4"
        mock_resolver.return_value.is_local_model.return_value = False
        mock_resolver.return_value.resolve_base_url.return_value = None
        
        mock_feature = Mock()
        mock_feature.supports_function_calling = True
        mock_feature.max_input_tokens = 8000
        mock_feature.max_output_tokens = 4000
        mock_features.return_value = mock_feature
        
        with patch.object(LLM, "_extract_api_key", return_value="test-key"):
            llm = LLM(mock_config, "test-service")
        
        assert llm.features is mock_feature




