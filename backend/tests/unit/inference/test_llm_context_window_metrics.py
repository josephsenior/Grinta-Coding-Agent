from __future__ import annotations

from unittest.mock import Mock, patch

from backend.inference.llm import LLM
from backend.inference.metrics import Metrics


def test_llm_records_context_window_from_limits():
    mock_config = Mock()
    mock_config.model = 'gpt-4'
    mock_config.base_url = 'https://api.openai.com'
    mock_config.api_key = 'test-key'
    mock_config.native_tool_calling = None
    mock_config.max_input_tokens = None
    mock_config.max_output_tokens = None
    mock_config.custom_tokenizer = None
    mock_config.temperature = 0.0
    mock_config.top_p = None
    mock_config.top_k = None
    mock_config.reasoning_effort = None
    mock_config.seed = None
    mock_config.num_retries = 0
    mock_config.retry_min_wait = 0
    mock_config.retry_max_wait = 0
    mock_config.retry_multiplier = 1
    mock_config.custom_llm_provider = None
    mock_config.disable_vision = False
    mock_config.caching_prompt = False
    mock_config.timeout = None

    with (
        patch('backend.inference.llm.get_direct_client') as mock_get_client,
        patch('backend.inference.llm.get_features') as mock_get_features,
        patch('backend.inference.provider_resolver.get_resolver') as mock_resolver,
        patch.object(LLM, '_extract_api_key', return_value='test-key'),
    ):
        mock_resolver.return_value.is_local_model.return_value = False
        mock_resolver.return_value.resolve_base_url.return_value = None
        mock_get_features.return_value = Mock(
            supports_function_calling=True,
            max_input_tokens=8000,
            max_output_tokens=2000,
        )

        response = Mock()
        response.id = 'resp1'
        response.usage = {'prompt_tokens': 10, 'completion_tokens': 5}
        response.to_dict.return_value = {'id': 'resp1'}

        mock_client = Mock()
        mock_client.get_completion_cost.return_value = 0.0
        mock_client.completion.return_value = response
        mock_get_client.return_value = mock_client

        llm = LLM(mock_config, 'test', metrics=Metrics(model_name='gpt-4'))

        llm.completion(messages=[{'role': 'user', 'content': 'hi'}])

        assert llm.metrics.token_usages
        assert llm.metrics.token_usages[-1].context_window == 10000
