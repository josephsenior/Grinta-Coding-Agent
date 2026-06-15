"""Provider configurations and verified model catalogs.

Extracted from constants.py to keep single-responsibility modules.
"""

from __future__ import annotations

from typing import Any

# Verified models for CLI and configuration — derived from provider catalogs.
# Uses lazy loading to avoid circular imports (constants ← config ← models).
VERIFIED_PROVIDERS = ['anthropic', 'openai', 'mistral', 'groq']


def _get_verified(provider: str) -> list[str]:
    """Lazily load verified models from the catalog."""
    from backend.inference.catalog_loader import get_verified_models

    return get_verified_models(provider)


class _LazyModelList:
    """List-like wrapper that loads from catalog on first access."""

    __slots__ = ('_provider', '_cached')

    def __init__(self, provider: str) -> None:
        self._provider = provider
        self._cached: list[str] | None = None

    def _ensure(self) -> list[str]:
        if self._cached is None:
            self._cached = _get_verified(self._provider)
        return self._cached

    def __iter__(self):
        return iter(self._ensure())

    def __contains__(self, item):
        return item in self._ensure()

    def __len__(self):
        return len(self._ensure())

    def __repr__(self):
        return repr(self._ensure())

    def __getitem__(self, idx):
        return self._ensure()[idx]

    def __eq__(self, other):
        if isinstance(other, list):
            return self._ensure() == other
        return NotImplemented


VERIFIED_OPENAI_MODELS: Any = _LazyModelList('openai')
VERIFIED_ANTHROPIC_MODELS: Any = _LazyModelList('anthropic')
VERIFIED_MISTRAL_MODELS: Any = _LazyModelList('mistral')
VERIFIED_GROQ_MODELS: Any = _LazyModelList('groq')


# Provider extraction patterns
PROVIDER_PREFIX_PATTERNS = {
    'openai': ['openai/'],
    'anthropic': ['anthropic/'],
    'google': ['google/'],
    'xai': ['xai/'],
    'groq': ['groq/'],
    'lightning': ['lightning/'],
    'opencode': ['opencode/'],
    'opencode-go': ['opencode-go/'],
    'zai': ['zai/'],
    'openrouter': ['openrouter/'],
    'vercel': ['vercel/'],
    'nvidia': ['nvidia/', 'moonshotai/'],
    'mistral': ['mistral/'],
    'digitalocean': ['digitalocean/'],
    'deepinfra': ['deepinfra/'],
    'fireworks': ['fireworks/'],
    'together': ['together/'],
    'perplexity': ['perplexity/'],
}

# Legacy heuristic tables intentionally left empty.
# Provider selection now relies on explicit prefixes or exact catalog entries.
PROVIDER_KEYWORD_PATTERNS: dict[str, list[str]] = {}

PROVIDER_FALLBACK_PATTERNS: dict[str, list[str]] = {}

# Provider and API Key constants
DEFAULT_API_KEY_MIN_LENGTH = 10

PROVIDER_CONFIGURATIONS: dict[str, dict[str, Any]] = {
    'openai': {
        'name': 'openai',
        'env_var': 'OPENAI_API_KEY',
        'requires_protocol': True,
        'supports_streaming': True,
        'required_params': {'api_key', 'model'},
        'optional_params': {
            'base_url',
            'api_version',
            'timeout',
            'temperature',
            'max_tokens',
            'top_p',
            'seed',
            'drop_params',
            'custom_llm_provider',
        },
        'forbidden_params': set(),
        'api_key_prefixes': ['sk-'],
        'api_key_min_length': 20,
        'handles_own_routing': False,
        'requires_custom_llm_provider': False,
    },
    'anthropic': {
        'name': 'anthropic',
        'env_var': 'ANTHROPIC_API_KEY',
        'requires_protocol': True,
        'supports_streaming': True,
        'required_params': {'api_key', 'model'},
        'optional_params': {
            'timeout',
            'temperature',
            'max_tokens',
            'seed',
            'drop_params',
        },
        'forbidden_params': {'custom_llm_provider'},
        'api_key_prefixes': ['sk-ant-'],
        'api_key_min_length': 20,
        'handles_own_routing': False,
        'requires_custom_llm_provider': False,
    },
    'google': {
        'name': 'google',
        'env_var': 'GEMINI_API_KEY',
        'requires_protocol': False,
        'supports_streaming': True,
        'required_params': {'api_key', 'model'},
        'optional_params': {
            'timeout',
            'temperature',
            'max_tokens',
            'seed',
            'drop_params',
        },
        'forbidden_params': {
            'custom_llm_provider',
            'base_url',
        },
        'api_key_prefixes': ['AIza'],
        'api_key_min_length': 20,
        'handles_own_routing': True,
        'requires_custom_llm_provider': False,
    },
    'xai': {
        'name': 'xai',
        'env_var': 'XAI_API_KEY',
        'requires_protocol': True,
        'supports_streaming': True,
        'required_params': {'api_key', 'model'},
        'optional_params': {
            'base_url',
            'timeout',
            'temperature',
            'max_tokens',
            'seed',
            'drop_params',
        },
        'forbidden_params': {'custom_llm_provider'},
        'api_key_prefixes': ['xai-'],
        'api_key_min_length': 20,
        'handles_own_routing': False,
        'requires_custom_llm_provider': False,
    },
    'groq': {
        'name': 'groq',
        'env_var': 'GROQ_API_KEY',
        'requires_protocol': True,
        'supports_streaming': True,
        'required_params': {'api_key', 'model'},
        'optional_params': {
            'base_url',
            'timeout',
            'temperature',
            'max_tokens',
            'top_p',
            'seed',
            'drop_params',
        },
        'forbidden_params': {'custom_llm_provider'},
        'api_key_prefixes': ['gsk_'],
        'api_key_min_length': 20,
        'handles_own_routing': False,
        'requires_custom_llm_provider': False,
    },
    'deepseek': {
        'name': 'deepseek',
        'env_var': 'DEEPSEEK_API_KEY',
        'requires_protocol': True,
        'supports_streaming': True,
        'required_params': {'api_key', 'model'},
        'optional_params': {
            'base_url',
            'timeout',
            'temperature',
            'max_tokens',
            'top_p',
            'seed',
            'drop_params',
            'reasoning_effort',
        },
        'forbidden_params': {'custom_llm_provider'},
        'api_key_prefixes': ['sk-'],
        'api_key_min_length': 10,
        'handles_own_routing': False,
        'requires_custom_llm_provider': False,
    },
    'vercel': {
        'name': 'vercel',
        'env_var': 'VERCEL_API_KEY',
        'requires_protocol': True,
        'supports_streaming': True,
        'required_params': {'api_key', 'model'},
        'optional_params': {
            'base_url',
            'timeout',
            'temperature',
            'max_tokens',
            'top_p',
            'seed',
            'drop_params',
        },
        'forbidden_params': {'custom_llm_provider'},
        'api_key_prefixes': ['vck_'],
        'api_key_min_length': 20,
        'handles_own_routing': False,
        'requires_custom_llm_provider': False,
    },
    'openrouter': {
        'name': 'openrouter',
        'env_var': 'OPENROUTER_API_KEY',
        'requires_protocol': True,
        'supports_streaming': True,
        'required_params': {'api_key', 'model'},
        'optional_params': {
            'base_url',
            'timeout',
            'temperature',
            'max_tokens',
            'top_p',
            'seed',
            'drop_params',
        },
        'forbidden_params': {'custom_llm_provider'},
        'api_key_prefixes': ['sk-or-'],
        'api_key_min_length': 20,
        'handles_own_routing': False,
        'requires_custom_llm_provider': False,
    },
    'nvidia': {
        'name': 'nvidia',
        'env_var': 'NVIDIA_API_KEY',
        'requires_protocol': True,
        'supports_streaming': True,
        'required_params': {'api_key', 'model'},
        'optional_params': {
            'base_url',
            'timeout',
            'temperature',
            'max_tokens',
            'top_p',
            'seed',
            'drop_params',
        },
        'forbidden_params': {'custom_llm_provider'},
        'api_key_prefixes': [],
        'api_key_min_length': 20,
        'handles_own_routing': False,
        'requires_custom_llm_provider': False,
    },
    'lightning': {
        'name': 'lightning',
        'env_var': 'LIGHTNING_API_KEY',
        'requires_protocol': True,
        'supports_streaming': True,
        'required_params': {'api_key', 'model'},
        'optional_params': {
            'base_url',
            'timeout',
            'temperature',
            'max_tokens',
            'top_p',
            'seed',
            'drop_params',
        },
        'forbidden_params': {'custom_llm_provider'},
        'api_key_prefixes': [],
        'api_key_min_length': 10,
        'handles_own_routing': False,
        'requires_custom_llm_provider': False,
    },
    'cerebras': {
        'name': 'cerebras',
        'env_var': 'CEREBRAS_API_KEY',
        'requires_protocol': True,
        'supports_streaming': True,
        'required_params': {'api_key', 'model'},
        'optional_params': {
            'base_url',
            'timeout',
            'temperature',
            'max_tokens',
            'top_p',
            'seed',
            'drop_params',
        },
        'forbidden_params': {'custom_llm_provider'},
        'api_key_prefixes': ['csk-'],
        'api_key_min_length': 20,
        'handles_own_routing': False,
        'requires_custom_llm_provider': False,
    },
    'mistral': {
        'name': 'mistral',
        'env_var': 'MISTRAL_API_KEY',
        'requires_protocol': True,
        'supports_streaming': True,
        'required_params': {'api_key', 'model'},
        'optional_params': {
            'base_url',
            'timeout',
            'temperature',
            'max_tokens',
            'top_p',
            'seed',
            'drop_params',
        },
        'forbidden_params': {'custom_llm_provider'},
        'api_key_prefixes': [],
        'api_key_min_length': 10,
        'handles_own_routing': False,
        'requires_custom_llm_provider': False,
    },
    'digitalocean': {
        'name': 'digitalocean',
        'env_var': 'DIGITALOCEAN_API_KEY',
        'requires_protocol': True,
        'supports_streaming': True,
        'required_params': {'api_key', 'model'},
        'optional_params': {
            'base_url',
            'timeout',
            'temperature',
            'max_tokens',
            'top_p',
            'seed',
            'drop_params',
        },
        'forbidden_params': {'custom_llm_provider'},
        'api_key_prefixes': [],
        'api_key_min_length': 10,
        'handles_own_routing': False,
        'requires_custom_llm_provider': False,
    },
    'deepinfra': {
        'name': 'deepinfra',
        'env_var': 'DEEPINFRA_API_KEY',
        'requires_protocol': True,
        'supports_streaming': True,
        'required_params': {'api_key', 'model'},
        'optional_params': {
            'base_url',
            'timeout',
            'temperature',
            'max_tokens',
            'top_p',
            'seed',
            'drop_params',
        },
        'forbidden_params': {'custom_llm_provider'},
        'api_key_prefixes': [],
        'api_key_min_length': 10,
        'handles_own_routing': False,
        'requires_custom_llm_provider': False,
    },
    'fireworks': {
        'name': 'fireworks',
        'env_var': 'FIREWORKS_API_KEY',
        'requires_protocol': True,
        'supports_streaming': True,
        'required_params': {'api_key', 'model'},
        'optional_params': {
            'base_url',
            'timeout',
            'temperature',
            'max_tokens',
            'top_p',
            'seed',
            'drop_params',
        },
        'forbidden_params': {'custom_llm_provider'},
        'api_key_prefixes': [],
        'api_key_min_length': 10,
        'handles_own_routing': False,
        'requires_custom_llm_provider': False,
    },
    'together': {
        'name': 'together',
        'env_var': 'TOGETHER_API_KEY',
        'requires_protocol': True,
        'supports_streaming': True,
        'required_params': {'api_key', 'model'},
        'optional_params': {
            'base_url',
            'timeout',
            'temperature',
            'max_tokens',
            'top_p',
            'seed',
            'drop_params',
        },
        'forbidden_params': {'custom_llm_provider'},
        'api_key_prefixes': [],
        'api_key_min_length': 10,
        'handles_own_routing': False,
        'requires_custom_llm_provider': False,
    },
    'perplexity': {
        'name': 'perplexity',
        'env_var': 'PERPLEXITY_API_KEY',
        'requires_protocol': True,
        'supports_streaming': True,
        'required_params': {'api_key', 'model'},
        'optional_params': {
            'base_url',
            'timeout',
            'temperature',
            'max_tokens',
            'top_p',
            'seed',
            'drop_params',
        },
        'forbidden_params': {'custom_llm_provider'},
        'api_key_prefixes': ['pplx-'],
        'api_key_min_length': 10,
        'handles_own_routing': False,
        'requires_custom_llm_provider': False,
    },
    'opencode': {
        'name': 'opencode',
        'env_var': 'OPENCODE_API_KEY',
        'requires_protocol': True,
        'supports_streaming': True,
        'required_params': {'api_key', 'model'},
        'optional_params': {
            'base_url',
            'timeout',
            'temperature',
            'max_tokens',
            'top_p',
            'seed',
            'drop_params',
        },
        'forbidden_params': {'custom_llm_provider'},
        'api_key_prefixes': [],
        'api_key_min_length': 10,
        'handles_own_routing': False,
        'requires_custom_llm_provider': False,
    },
    'opencode-go': {
        'name': 'opencode-go',
        'env_var': 'OPENCODE_API_KEY',
        'requires_protocol': True,
        'supports_streaming': True,
        'required_params': {'api_key', 'model'},
        'optional_params': {
            'base_url',
            'timeout',
            'temperature',
            'max_tokens',
            'top_p',
            'seed',
            'drop_params',
        },
        'forbidden_params': {'custom_llm_provider'},
        'api_key_prefixes': [],
        'api_key_min_length': 10,
        'handles_own_routing': False,
        'requires_custom_llm_provider': False,
    },
    'zai': {
        'name': 'zai',
        'env_var': 'ZAI_API_KEY',
        'requires_protocol': True,
        'supports_streaming': True,
        'required_params': {'api_key', 'model'},
        'optional_params': {
            'base_url',
            'timeout',
            'temperature',
            'max_tokens',
            'top_p',
            'seed',
            'drop_params',
        },
        'forbidden_params': {'custom_llm_provider'},
        'api_key_prefixes': [],
        'api_key_min_length': 10,
        'handles_own_routing': False,
        'requires_custom_llm_provider': False,
    },
}

UNKNOWN_PROVIDER_CONFIG: dict[str, Any] = {
    'name': 'unknown',
    'env_var': None,
    'requires_protocol': True,
    'supports_streaming': False,
    'required_params': {'model'},
    'optional_params': {
        'api_key',
        'base_url',
        'timeout',
        'temperature',
        'max_tokens',
        'top_p',
        'seed',
        'drop_params',
        'api_version',
    },
    'forbidden_params': set(),
    'api_key_prefixes': [],
    'api_key_min_length': 10,
    'handles_own_routing': False,
    'requires_custom_llm_provider': False,
}
