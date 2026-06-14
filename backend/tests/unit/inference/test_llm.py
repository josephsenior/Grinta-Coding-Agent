"""Comprehensive tests for backend.inference.llm - LLM integration and exception mapping."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, Mock, patch

import pytest

from backend.core.config import LLMConfig
from backend.inference.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadRequestError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)
from backend.inference.llm import (
    LLM,
    _map_anthropic_exception,
    _map_openai_exception,
    _map_provider_exception,
)


class TestMapOpenAIException:
    """Tests for _map_openai_exception() function."""

    def test_maps_authentication_error(self):
        """Test mapping OpenAI AuthenticationError."""
        try:
            import openai

            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = openai.AuthenticationError(
                message='Invalid API key', response=mock_response, body=None
            )
            result = _map_openai_exception(exc, 'gpt-4')

            assert isinstance(result, AuthenticationError)
            assert result.model == 'gpt-4'
            assert result.llm_provider == 'openai'
        except ImportError:
            pytest.skip('OpenAI not installed')

    def test_maps_rate_limit_error(self):
        """Test mapping OpenAI RateLimitError."""
        try:
            import openai

            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = openai.RateLimitError(
                message='Rate limit exceeded', response=mock_response, body=None
            )
            result = _map_openai_exception(exc, 'gpt-4')

            assert isinstance(result, RateLimitError)
            assert result.model == 'gpt-4'
        except ImportError:
            pytest.skip('OpenAI not installed')

    def test_maps_api_connection_error(self):
        """Test mapping OpenAI APIConnectionError."""
        try:
            import openai

            exc = openai.APIConnectionError(request=MagicMock())
            result = _map_openai_exception(exc, 'gpt-4')

            assert isinstance(result, APIConnectionError)
        except ImportError:
            pytest.skip('OpenAI not installed')

    def test_maps_timeout_error(self):
        """Test mapping OpenAI APITimeoutError."""
        try:
            import openai

            exc = openai.APITimeoutError(request=MagicMock())
            result = _map_openai_exception(exc, 'gpt-4')

            assert isinstance(result, Timeout)
        except ImportError:
            pytest.skip('OpenAI not installed')

    def test_maps_bad_request_error(self):
        """Test mapping OpenAI BadRequestError."""
        try:
            import openai

            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = openai.BadRequestError(
                message='Invalid request', response=mock_response, body=None
            )
            result = _map_openai_exception(exc, 'gpt-4')

            assert isinstance(result, BadRequestError)
        except ImportError:
            pytest.skip('OpenAI not installed')

    def test_maps_context_window_error(self):
        """Test mapping context window exceeded in BadRequestError."""
        try:
            import openai

            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = openai.BadRequestError(
                message='maximum context length exceeded',
                response=mock_response,
                body=None,
            )
            result = _map_openai_exception(exc, 'gpt-4')

            assert isinstance(result, ContextWindowExceededError)
        except ImportError:
            pytest.skip('OpenAI not installed')

    def test_maps_internal_server_error(self):
        """Test mapping OpenAI InternalServerError."""
        try:
            import openai

            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = openai.InternalServerError(
                message='Server error', response=mock_response, body=None
            )
            result = _map_openai_exception(exc, 'gpt-4')

            assert isinstance(result, InternalServerError)
        except ImportError:
            pytest.skip('OpenAI not installed')

    def test_maps_api_status_error_503(self):
        """Test mapping APIStatusError with 503 to ServiceUnavailable."""
        try:
            import openai

            mock_response = MagicMock()
            mock_response.status_code = 503
            mock_response.request = MagicMock()
            exc = openai.APIStatusError(
                message='Service unavailable', response=mock_response, body=None
            )
            exc.status_code = 503
            result = _map_openai_exception(exc, 'gpt-4')

            assert isinstance(result, ServiceUnavailableError)
        except ImportError:
            pytest.skip('OpenAI not installed')

    def test_maps_api_status_error_other(self):
        """Test mapping APIStatusError with other status codes."""
        try:
            import openai

            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.request = MagicMock()
            exc = openai.APIStatusError(
                message='Bad request', response=mock_response, body=None
            )
            exc.status_code = 400
            result = _map_openai_exception(exc, 'gpt-4')

            assert isinstance(result, APIError)
            assert result.status_code == 400
        except ImportError:
            pytest.skip('OpenAI not installed')

    def test_returns_none_for_unknown_exception(self):
        """Test returns None for non-OpenAI exceptions."""
        exc = ValueError('Not an OpenAI exception')
        result = _map_openai_exception(exc, 'gpt-4')
        assert result is None

    def test_returns_none_when_openai_not_installed(self):
        """Test returns None when openai package not available."""
        with patch.dict('sys.modules', {'openai': None}):
            exc = Exception('Test')
            result = _map_openai_exception(exc, 'gpt-4')
            assert result is None


def test_get_call_kwargs_includes_configured_timeout():
    llm = object.__new__(LLM)
    llm.config = LLMConfig(model='openai/gpt-4.1', timeout=23)

    with (
        patch(
            'backend.inference.catalog_loader.apply_model_param_overrides',
            side_effect=lambda _model, call_kwargs, **_kwargs: call_kwargs,
        ),
        patch(
            'backend.inference.catalog_loader.sanitize_call_kwargs_for_provider',
            side_effect=lambda _model, call_kwargs: call_kwargs,
        ),
    ):
        kwargs = llm._get_call_kwargs()

    assert kwargs['timeout'] == 23.0


class TestMapAnthropicException:
    """Tests for _map_anthropic_exception() function."""

    def test_maps_authentication_error(self):
        """Test mapping Anthropic AuthenticationError."""
        try:
            import anthropic

            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = anthropic.AuthenticationError(
                message='Invalid API key', response=mock_response, body=None
            )
            result = _map_anthropic_exception(exc, 'claude-3')

            assert isinstance(result, AuthenticationError)
            assert result.model == 'claude-3'
            assert result.llm_provider == 'anthropic'
        except ImportError:
            pytest.skip('Anthropic not installed')

    def test_maps_rate_limit_error(self):
        """Test mapping Anthropic RateLimitError."""
        try:
            import anthropic

            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = anthropic.RateLimitError(
                message='Rate limited', response=mock_response, body=None
            )
            result = _map_anthropic_exception(exc, 'claude-3')

            assert isinstance(result, RateLimitError)
        except ImportError:
            pytest.skip('Anthropic not installed')

    def test_maps_api_connection_error(self):
        """Test mapping Anthropic APIConnectionError."""
        try:
            import anthropic

            exc = anthropic.APIConnectionError(request=MagicMock())
            result = _map_anthropic_exception(exc, 'claude-3')

            assert isinstance(result, APIConnectionError)
        except ImportError:
            pytest.skip('Anthropic not installed')

    def test_maps_timeout_error(self):
        """Test mapping Anthropic APITimeoutError."""
        try:
            import anthropic

            exc = anthropic.APITimeoutError(request=MagicMock())
            result = _map_anthropic_exception(exc, 'claude-3')

            assert isinstance(result, Timeout)
        except ImportError:
            pytest.skip('Anthropic not installed')

    def test_maps_bad_request_error(self):
        """Test mapping Anthropic BadRequestError."""
        try:
            import anthropic

            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = anthropic.BadRequestError(
                message='Invalid', response=mock_response, body=None
            )
            result = _map_anthropic_exception(exc, 'claude-3')

            assert isinstance(result, BadRequestError)
        except ImportError:
            pytest.skip('Anthropic not installed')

    def test_maps_context_window_error(self):
        """Test mapping context window exceeded."""
        try:
            import anthropic

            mock_response = MagicMock()
            mock_response.request = MagicMock()
            exc = anthropic.BadRequestError(
                message='maximum context length exceeded',
                response=mock_response,
                body=None,
            )
            result = _map_anthropic_exception(exc, 'claude-3')

            assert isinstance(result, ContextWindowExceededError)
        except ImportError:
            pytest.skip('Anthropic not installed')

    def test_returns_none_for_unknown_exception(self):
        """Test returns None for non-Anthropic exceptions."""
        exc = ValueError('Not an Anthropic exception')
        result = _map_anthropic_exception(exc, 'claude-3')
        assert result is None


class TestMapProviderException:
    """Tests for _map_provider_exception() function."""

    def test_passes_through_llm_error(self):
        """Test that LLMError subclasses pass through unchanged."""
        exc = AuthenticationError('Test', model='gpt-4')
        result = _map_provider_exception(exc, 'gpt-4')
        assert result is exc

    def test_maps_generic_google_error(self):
        """Test mapping generic Google Generative AI error."""

        # Create exception with 'google' in class name to trigger Google error detection
        class GoogleGenerativeAIError(Exception):
            pass

        exc = GoogleGenerativeAIError('Model inference failed')
        result = _map_provider_exception(exc, 'gemini-pro')

        assert isinstance(result, APIError)
        assert result.llm_provider == 'google'

    def test_maps_google_quota_error(self):
        """Test mapping Google quota/rate limit error."""

        # Create exception with 'google' in class name
        class GoogleAPIError(Exception):
            pass

        exc = GoogleAPIError('Quota exceeded for generativeai')
        result = _map_provider_exception(exc, 'gemini-pro')

        assert isinstance(result, RateLimitError)
        assert result.llm_provider == 'google'

    def test_maps_google_context_window_error(self):
        """Test mapping Google context window error."""

        # Create exception with 'google' in class name
        class GoogleAPIError(Exception):
            pass

        exc = GoogleAPIError('maximum context length exceeded')
        result = _map_provider_exception(exc, 'gemini-pro')

        assert isinstance(result, ContextWindowExceededError)
        assert result.llm_provider == 'google'

    def test_maps_content_filter_error(self):
        """Test mapping content filter errors."""
        exc = Exception('Response blocked by content_filter')
        result = _map_provider_exception(exc, 'gpt-4')

        assert isinstance(result, ContentPolicyViolationError)

    def test_maps_content_policy_error(self):
        """Test mapping content policy errors."""
        exc = Exception('Violates content policy')
        result = _map_provider_exception(exc, 'gpt-4')

        assert isinstance(result, ContentPolicyViolationError)

    def test_maps_safety_error(self):
        """Test mapping safety filter errors."""
        exc = Exception('Blocked by safety filters')
        result = _map_provider_exception(exc, 'gemini-pro')

        assert isinstance(result, ContentPolicyViolationError)

    def test_maps_generic_context_window_error(self):
        """Test mapping generic context window errors."""
        exc = Exception('Context length exceeded')
        result = _map_provider_exception(exc, 'unknown-model')

        assert isinstance(result, ContextWindowExceededError)

    def test_fallback_to_api_error(self):
        """Test unknown exceptions fallback to APIError."""
        exc = Exception('Some random error')
        result = _map_provider_exception(exc, 'test-model')

        assert isinstance(result, APIError)
        assert result.model == 'test-model'

    def test_preserves_error_message(self):
        """Test that error messages are preserved."""
        exc = Exception('Detailed error message')
        result = _map_provider_exception(exc, 'test-model')

        assert 'Detailed error message' in str(result)


class TestLLMInit:
    """Tests for LLM.__init__() initialization."""

    @patch('backend.inference.llm.get_direct_client')
    @patch('backend.inference.llm.get_features')
    @patch('backend.inference.provider_resolver.get_resolver')
    def test_init_basic(self, mock_resolver, mock_features, mock_client):
        """Test basic LLM initialization."""
        # Setup mocks
        mock_config = Mock()
        mock_config.model = 'gpt-4'
        mock_config.base_url = 'https://api.openai.com'
        mock_config.api_key = 'test-key'
        mock_config.native_tool_calling = None
        mock_config.max_input_tokens = None
        mock_config.max_output_tokens = None
        mock_config.custom_tokenizer = None

        mock_resolver.return_value.is_local_model.return_value = False
        mock_resolver.return_value.resolve_base_url.return_value = None

        mock_feature = Mock()
        mock_feature.supports_function_calling = True
        mock_feature.max_input_tokens = 8000
        mock_feature.max_output_tokens = 4000
        mock_features.return_value = mock_feature

        with patch.object(LLM, '_extract_api_key', return_value='test-key'):
            llm = LLM(mock_config, 'test-service')

        assert llm.service_id == 'test-service'
        assert llm.config.model == 'gpt-4'
        mock_client.assert_called_once()

    @patch('backend.inference.llm.get_direct_client')
    @patch('backend.inference.llm.get_features')
    @patch('backend.inference.provider_resolver.get_resolver')
    def test_init_model_id_passed_through(
        self, mock_resolver, mock_features, mock_client
    ):
        """Model id is used as configured; there is no alias resolution layer."""
        mock_config = Mock()
        mock_config.model = 'gpt4'
        mock_config.base_url = 'https://api.openai.com'
        mock_config.api_key = 'test-key'
        mock_config.native_tool_calling = None
        mock_config.max_input_tokens = None
        mock_config.max_output_tokens = None
        mock_config.custom_tokenizer = None

        mock_resolver.return_value.is_local_model.return_value = False
        mock_resolver.return_value.resolve_base_url.return_value = None

        mock_features.return_value = Mock(
            supports_function_calling=True,
            max_input_tokens=8000,
            max_output_tokens=4000,
        )

        with patch.object(LLM, '_extract_api_key', return_value='test-key'):
            llm = LLM(mock_config, 'test-service')

        assert llm.config.model == 'gpt4'

    @patch('backend.inference.llm.get_direct_client')
    @patch('backend.inference.llm.get_features')
    @patch('backend.inference.provider_resolver.get_resolver')
    def test_init_auto_discovers_base_url(
        self, mock_resolver, mock_features, mock_client
    ):
        """Test auto-discovery of base_url for local models."""
        mock_config = Mock()
        mock_config.model = 'ollama/llama2'
        mock_config.base_url = None
        mock_config.api_key = None
        mock_config.native_tool_calling = None
        mock_config.max_input_tokens = None
        mock_config.max_output_tokens = None
        mock_config.custom_tokenizer = None

        # Resolver discovers local endpoint
        mock_resolver_inst = mock_resolver.return_value
        mock_resolver_inst.resolve_base_url.return_value = 'http://localhost:11434'
        mock_resolver_inst.is_local_model.return_value = True
        mock_resolver_inst.is_local_model.return_value = True

        mock_features.return_value = Mock(
            supports_function_calling=False,
            max_input_tokens=4096,
            max_output_tokens=2048,
        )

        with patch.object(LLM, '_extract_api_key', return_value=None):
            llm = LLM(mock_config, 'test-service')

        # base_url should be auto-discovered
        assert llm.config.base_url == 'http://localhost:11434'

    @patch('backend.inference.llm.get_direct_client')
    @patch('backend.inference.llm.get_features')
    @patch('backend.inference.provider_resolver.get_resolver')
    def test_init_local_model_no_api_key_required(
        self, mock_resolver, mock_features, mock_client
    ):
        """Test local models don't require API key."""
        mock_config = Mock()
        mock_config.model = 'ollama/llama2'
        mock_config.base_url = 'http://localhost:11434'
        mock_config.api_key = None
        mock_config.native_tool_calling = None
        mock_config.max_input_tokens = None
        mock_config.max_output_tokens = None
        mock_config.custom_tokenizer = None

        mock_resolver.return_value.is_local_model.return_value = True
        mock_resolver.return_value.resolve_base_url.return_value = None

        mock_features.return_value = Mock(
            supports_function_calling=False,
            max_input_tokens=4096,
            max_output_tokens=2048,
        )

        with patch.object(LLM, '_extract_api_key', return_value=None):
            # Should not raise
            llm = LLM(mock_config, 'test-service')
            assert llm.service_id == 'test-service'

    @patch('backend.inference.llm.get_direct_client')
    @patch('backend.inference.llm.get_features')
    @patch('backend.inference.provider_resolver.get_resolver')
    def test_init_cloud_model_requires_api_key(
        self, mock_resolver, mock_features, mock_client
    ):
        """Test cloud models require API key."""
        mock_config = Mock()
        mock_config.model = 'gpt-4'
        mock_config.base_url = None
        mock_config.api_key = None
        mock_config.native_tool_calling = None
        mock_config.max_input_tokens = None
        mock_config.max_output_tokens = None
        mock_config.custom_tokenizer = None

        mock_resolver.return_value.is_local_model.return_value = False
        mock_resolver.return_value.resolve_base_url.return_value = None

        with patch.object(LLM, '_extract_api_key', return_value=None):
            with pytest.raises(AuthenticationError) as exc_info:
                LLM(mock_config, 'test-service')

            assert 'No API key provided' in str(exc_info.value)

    @patch('backend.inference.llm.get_direct_client')
    @patch('backend.inference.llm.get_features')
    @patch('backend.inference.provider_resolver.get_resolver')
    def test_init_with_metrics(self, mock_resolver, mock_features, mock_client):
        """Test initialization with custom metrics."""
        mock_config = Mock()
        mock_config.model = 'gpt-4'
        mock_config.base_url = 'https://api.openai.com'
        mock_config.api_key = 'test-key'
        mock_config.native_tool_calling = None
        mock_config.max_input_tokens = None
        mock_config.max_output_tokens = None
        mock_config.custom_tokenizer = None

        mock_resolver.return_value.is_local_model.return_value = False
        mock_resolver.return_value.resolve_base_url.return_value = None

        mock_features.return_value = Mock(
            supports_function_calling=True,
            max_input_tokens=8000,
            max_output_tokens=4000,
        )

        custom_metrics = Mock()

        with patch.object(LLM, '_extract_api_key', return_value='test-key'):
            llm = LLM(mock_config, 'test-service', metrics=custom_metrics)

        assert llm.metrics is custom_metrics

    @patch('backend.inference.llm.get_direct_client')
    @patch('backend.inference.llm.get_features')
    @patch('backend.inference.provider_resolver.get_resolver')
    def test_init_function_calling_configuration(
        self, mock_resolver, mock_features, mock_client
    ):
        """Test function calling is properly configured."""
        mock_config = Mock()
        mock_config.model = 'gpt-4'
        mock_config.base_url = 'https://api.openai.com'
        mock_config.api_key = 'test-key'
        mock_config.native_tool_calling = True  # Explicitly enabled
        mock_config.max_input_tokens = None
        mock_config.max_output_tokens = None
        mock_config.custom_tokenizer = None

        mock_resolver.return_value.is_local_model.return_value = False
        mock_resolver.return_value.resolve_base_url.return_value = None

        mock_features.return_value = Mock(
            supports_function_calling=True,
            max_input_tokens=8000,
            max_output_tokens=4000,
        )

        with patch.object(LLM, '_extract_api_key', return_value='test-key'):
            llm = LLM(mock_config, 'test-service')

        assert llm._function_calling_active is True

    @patch('backend.inference.llm.get_direct_client')
    @patch('backend.inference.llm.get_features')
    @patch('backend.inference.provider_resolver.get_resolver')
    def test_init_handles_feature_lookup_failure(
        self, mock_resolver, mock_features, mock_client
    ):
        """Test graceful handling of feature lookup failures."""
        mock_config = Mock()
        mock_config.model = 'unknown-model'
        mock_config.base_url = 'http://localhost:8000'
        mock_config.api_key = None
        mock_config.native_tool_calling = None
        mock_config.max_input_tokens = None
        mock_config.max_output_tokens = None
        mock_config.custom_tokenizer = None

        mock_resolver.return_value.is_local_model.return_value = True
        mock_resolver.return_value.resolve_base_url.return_value = None
        mock_features.side_effect = KeyError('Model not found')

        with patch.object(LLM, '_extract_api_key', return_value=None):
            # Should not raise, should use defaults
            llm = LLM(mock_config, 'test-service')
            assert llm._function_calling_active is False

    @patch('backend.inference.llm.get_direct_client')
    @patch('backend.inference.llm.get_features')
    @patch('backend.inference.provider_resolver.get_resolver')
    def test_init_config_is_deep_copied(
        self, mock_resolver, mock_features, mock_client
    ):
        """Test that config is deep copied on init."""
        mock_config = Mock()
        mock_config.model = 'gpt-4'
        mock_config.base_url = 'https://api.openai.com'
        mock_config.api_key = 'test-key'
        mock_config.native_tool_calling = None
        mock_config.max_input_tokens = None
        mock_config.max_output_tokens = None
        mock_config.custom_tokenizer = None

        mock_resolver.return_value.is_local_model.return_value = False
        mock_resolver.return_value.resolve_base_url.return_value = None

        mock_features.return_value = Mock(
            supports_function_calling=True,
            max_input_tokens=8000,
            max_output_tokens=4000,
        )

        with patch('backend.inference.llm.copy.deepcopy') as mock_deepcopy:
            mock_deepcopy.return_value = mock_config
            with patch.object(LLM, '_extract_api_key', return_value='test-key'):
                LLM(mock_config, 'test-service')

            mock_deepcopy.assert_called_once_with(mock_config)


class TestLLMProperties:
    """Tests for LLM property accessors."""

    @patch('backend.inference.llm.get_direct_client')
    @patch('backend.inference.llm.get_features')
    @patch('backend.inference.provider_resolver.get_resolver')
    def test_features_property(self, mock_resolver, mock_features, mock_client):
        """Test features property returns cached features."""
        mock_config = Mock()
        mock_config.model = 'gpt-4'
        mock_config.base_url = 'https://api.openai.com'
        mock_config.api_key = 'test-key'
        mock_config.native_tool_calling = None
        mock_config.max_input_tokens = None
        mock_config.max_output_tokens = None
        mock_config.custom_tokenizer = None

        mock_resolver.return_value.is_local_model.return_value = False
        mock_resolver.return_value.resolve_base_url.return_value = None

        mock_feature = Mock()
        mock_feature.supports_function_calling = True
        mock_feature.max_input_tokens = 8000
        mock_feature.max_output_tokens = 4000
        mock_features.return_value = mock_feature

        with patch.object(LLM, '_extract_api_key', return_value='test-key'):
            llm = LLM(mock_config, 'test-service')

        assert llm.features is mock_feature


class TestGetCallKwargs:
    """Regression tests for catalog-first call kwargs behavior."""

    def _make_llm_stub(self, model: str = 'gpt-4o') -> LLM:
        llm = LLM.__new__(LLM)
        llm.config = cast(
            LLMConfig,
            SimpleNamespace(
                model=model,
                temperature=0.2,
                max_output_tokens=1024,
                top_p=0.9,
                top_k=40,
                reasoning_effort='medium',
                seed=123,
            ),
        )
        return llm

    @patch('backend.inference.catalog_loader.sanitize_call_kwargs_for_provider')
    @patch('backend.inference.catalog_loader.apply_model_param_overrides')
    def test_catalog_overrides_invoked_before_sanitization(
        self, mock_apply_overrides, mock_sanitize
    ):
        llm = self._make_llm_stub('google/gemini-2.5-pro')

        mock_apply_overrides.return_value = {
            'model': 'google/gemini-2.5-pro',
            'temperature': 0.2,
            'max_tokens': 1024,
            'top_p': 0.9,
            'top_k': 40,
            'tools': [{'type': 'function', 'function': {'name': 'x'}}],
            'tool_choice': 'none',
            'reasoning_effort': 'medium',
        }
        mock_sanitize.return_value = {
            'model': 'google/gemini-2.5-pro',
            'temperature': 0.2,
            'max_tokens': 1024,
            'top_p': 0.9,
            'top_k': 40,
            'tools': [{'type': 'function', 'function': {'name': 'x'}}],
        }

        result = llm._get_call_kwargs(
            is_stream=True,
            tools=[{'type': 'function', 'function': {'name': 'x'}}],
            tool_choice='none',
        )

        assert result['model'] == 'google/gemini-2.5-pro'
        assert 'tool_choice' not in result

        mock_apply_overrides.assert_called_once_with(
            'google/gemini-2.5-pro',
            {
                'model': 'google/gemini-2.5-pro',
                'temperature': 0.2,
                'max_tokens': 1024,
                'tools': [{'type': 'function', 'function': {'name': 'x'}}],
                'tool_choice': 'none',
                'top_p': 0.9,
                'top_k': 40,
            },
            reasoning_effort='medium',
            is_stream=True,
            provider=None,
            caching_prompt=True,
        )
        mock_sanitize.assert_called_once_with(
            'google/gemini-2.5-pro', mock_apply_overrides.return_value
        )

    def test_seed_is_added_after_overrides_and_kept_when_supported(self):
        llm = self._make_llm_stub('gpt-4o')

        result = llm._get_call_kwargs(is_stream=False, tool_choice='none')

        assert result['model'] == 'gpt-4o'
        assert result['seed'] == 123
        assert result['tool_choice'] == 'none'

    def test_explicit_max_tokens_is_not_overwritten_by_config_default(self):
        llm = self._make_llm_stub('gpt-4o')

        result = llm._get_call_kwargs(is_stream=True, max_tokens=321)

        assert result['max_tokens'] == 321


class TestInbandDisconnectDetection:
    """astream() must detect in-band provider disconnect messages and raise APIConnectionError.

    Regression suite for Lightning AI / DeepSeek proxy injecting disconnect
    notices (e.g. "ç½‘ç»œä¸­æ–­ï¼Œè¯·é‡æ–°è¿žæŽ¥") as stream content instead of HTTP errors.
    """

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _make_chunk(content: str) -> dict:
        return {'choices': [{'delta': {'content': content}}]}

    @staticmethod
    def _make_llm(chunks: list[dict]) -> LLM:
        """Return a minimal LLM stub wired to yield *chunks* from astream()."""
        from types import SimpleNamespace

        llm = LLM.__new__(LLM)
        llm.debug = False  # satisfies DebugMixin.log_prompt / log_response

        llm.config = SimpleNamespace(  # type: ignore[attr-defined,assignment]
            model='lightning-ai/deepseek-v4-pro',
            temperature=0,
            max_output_tokens=None,
            top_p=None,
            top_k=None,
            timeout=None,
            seed=None,
            reasoning_effort=None,
            num_retries=1,  # one attempt only â†’ no retries
            retry_min_wait=0,
            retry_max_wait=0,
            on_cancel_requested_fn=None,
        )

        async def _fake_astream(**_kwargs):
            for c in chunks:
                yield c

        llm.client = MagicMock()
        llm.client.astream = _fake_astream  # type: ignore[attr-defined]
        return llm

    @staticmethod
    def _run(llm: LLM) -> list[dict]:
        """Drive llm.astream() to completion, returning all yielded chunks."""
        import asyncio

        async def _collect():
            result = []
            async for chunk in llm.astream():
                result.append(chunk)
            return result

        with patch.multiple(
            'backend.inference.catalog_loader',
            apply_model_param_overrides=lambda _m, kw, **_kw2: kw,
            sanitize_call_kwargs_for_provider=lambda _m, kw: kw,
        ):
            return asyncio.run(_collect())

    # ------------------------------------------------------------------ #
    # Tests                                                                #
    # ------------------------------------------------------------------ #

    def test_chinese_disconnect_raises_api_connection_error(self):
        """Chinese disconnect phrase from Lightning AI / DeepSeek proxy raises."""
        llm = self._make_llm([self._make_chunk('ç½‘ç»œä¸­æ–­ï¼Œè¯·é‡æ–°è¿žæŽ¥')])
        with pytest.raises(APIConnectionError, match='in-band disconnect'):
            self._run(llm)

    def test_disconnect_across_two_chunks_raises(self):
        """Phrase split across consecutive chunks is still detected."""
        llm = self._make_llm(
            [self._make_chunk('ç½‘ç»œä¸­æ–­'), self._make_chunk('ï¼Œè¯·é‡æ–°è¿žæŽ¥')]
        )
        with pytest.raises(APIConnectionError):
            self._run(llm)

    def test_english_bad_gateway_raises(self):
        """Generic English proxy disconnect phrase raises."""
        llm = self._make_llm([self._make_chunk('bad gateway')])
        with pytest.raises(APIConnectionError):
            self._run(llm)

    def test_normal_content_is_not_flagged(self):
        """Normal model output passes through without raising."""
        chunks = [self._make_chunk('Hello'), self._make_chunk(' world')]
        result = self._run(self._make_llm(chunks))
        assert len(result) == 2

    def test_disconnect_phrase_beyond_prefix_limit_is_not_inspected(self):
        """Content that starts with legitimate output is never probed for disconnect.

        Once the first real chunk has been yielded the inspection window closes,
        so a disconnect phrase appearing only in later chunks must not raise.
        """
        from backend.inference.llm import _INBAND_PREFIX_LIMIT

        # First chunk is large legitimate content (beyond the prefix limit).
        big_content = 'A' * (_INBAND_PREFIX_LIMIT + 10)
        chunks = [self._make_chunk(big_content), self._make_chunk('ç½‘ç»œä¸­æ–­')]
        result = self._run(self._make_llm(chunks))
        assert len(result) == 2


class TestAstreamRetryListener:
    @staticmethod
    def _make_retrying_llm(listener: MagicMock) -> LLM:
        from types import SimpleNamespace

        llm = LLM.__new__(LLM)
        llm.debug = False
        llm.retry_listener = listener
        llm.config = SimpleNamespace(
            model='opencode-go/minimax-m2.7',
            temperature=0,
            max_output_tokens=None,
            top_p=None,
            top_k=None,
            timeout=None,
            seed=None,
            reasoning_effort=None,
            num_retries=2,
            retry_min_wait=0,
            retry_max_wait=0,
            on_cancel_requested_fn=None,
        )

        attempts = {'count': 0}

        async def _fake_astream(**_kwargs):
            if attempts['count'] == 0:
                attempts['count'] += 1
                raise APIConnectionError('connection reset')
            yield {'choices': [{'delta': {'content': 'ok'}}]}

        llm.client = MagicMock()
        llm.client.astream = _fake_astream  # type: ignore[attr-defined]
        return llm

    def test_astream_emits_retry_pending_and_resuming_listener_events(self):
        import asyncio

        listener = MagicMock()
        llm = self._make_retrying_llm(listener)

        async def _collect():
            result = []
            async for chunk in llm.astream():
                result.append(chunk)
            return result

        with patch.multiple(
            'backend.inference.catalog_loader',
            apply_model_param_overrides=lambda _m, kw, **_kw2: kw,
            sanitize_call_kwargs_for_provider=lambda _m, kw: kw,
        ):
            chunks = asyncio.run(_collect())

        assert len(chunks) == 1
        assert listener.call_count == 2
        first = listener.call_args_list[0]
        assert first.args == (1, 2)
        assert first.kwargs == {
            'status_type': 'llm_retry_pending',
            'reason': 'APIConnectionError',
            'wait_seconds': 1,
            'source': 'llm_stream',
            'streaming': True,
        }
        second = listener.call_args_list[1]
        assert second.args == (2, 2)
        assert second.kwargs == {
            'status_type': 'llm_retry_resuming',
            'reason': 'stream reconnect',
            'source': 'llm_stream',
            'streaming': True,
        }
