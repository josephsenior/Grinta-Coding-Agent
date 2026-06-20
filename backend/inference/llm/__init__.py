"""LLM integration and communication layer.

Classes:
    LLM

Functions:
    retry_decorator
"""

from __future__ import annotations

import copy

from backend.inference.capabilities.model_features import get_features
from backend.inference.clients import get_direct_client
from backend.inference.llm.config import (
    _apply_base_url_discovery,
    _apply_custom_tokenizer,
    _get_provider_resolver,
    _is_local_model,
    _llm_model_metadata_for_log,
    _load_cached_features,
    _resolve_function_calling_config,
    _safe_call_kwargs_for_log,
    _validate_api_key_or_local,
)
from backend.inference.llm.core import LLM
from backend.inference.llm.exceptions import (
    _map_anthropic_exception,
    _map_api_status_error,
    _map_bad_request_with_context_check,
    _map_openai_exception,
    _map_provider_exception,
    _safe_exception_text,
    _try_google_exception_mapping,
    _try_heuristic_exception_mapping,
)
from backend.inference.llm.stream import (
    _INBAND_PREFIX_LIMIT,
    _stream_with_chunk_timeout,
)

__all__ = [
    'LLM',
    'copy',
    'get_direct_client',
    'get_features',
    '_INBAND_PREFIX_LIMIT',
    '_apply_base_url_discovery',
    '_apply_custom_tokenizer',
    '_get_provider_resolver',
    '_is_local_model',
    '_llm_model_metadata_for_log',
    '_load_cached_features',
    '_map_anthropic_exception',
    '_map_api_status_error',
    '_map_bad_request_with_context_check',
    '_map_openai_exception',
    '_map_provider_exception',
    '_resolve_function_calling_config',
    '_safe_call_kwargs_for_log',
    '_safe_exception_text',
    '_stream_with_chunk_timeout',
    '_try_google_exception_mapping',
    '_try_heuristic_exception_mapping',
    '_validate_api_key_or_local',
]
