"""Transport-specific model listing backends for the unified registry."""

from __future__ import annotations

from typing import Protocol

import httpx

from backend.core.logger import app_logger as logger

LOCAL_PROVIDERS: frozenset[str] = frozenset({'ollama', 'lm_studio', 'vllm'})

NATIVE_LIST_PROVIDERS: frozenset[str] = frozenset({'anthropic', 'google', 'openai'})

OPENAI_COMPAT_PROVIDERS: frozenset[str] = frozenset(
    {
        'openai',
        'groq',
        'xai',
        'deepseek',
        'vercel',
        'openrouter',
        'nvidia',
        'lightning',
        'cerebras',
        'mistral',
        'digitalocean',
        'deepinfra',
        'fireworks',
        'together',
        'perplexity',
        'opencode',
        'opencode-go',
    }
)


def normalize_provider_name(provider: str | None) -> str | None:
    if provider is None:
        return None
    normalized = str(provider).strip().lower()
    return normalized or None


class ModelListBackend(Protocol):
    def list_models(
        self,
        provider: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> list[str]: ...


def _openai_compat_list(
    provider: str,
    api_key: str | None,
    base_url: str | None,
) -> list[str]:
    key = (api_key or '').strip()
    if not key:
        return []
    resolved = (base_url or _default_base_url(provider) or '').rstrip('/')
    if not resolved:
        return []
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            response = client.get(
                f'{resolved}/models',
                headers={'Authorization': f'Bearer {key}'},
            )
            if response.status_code != 200:
                logger.debug(
                    'OpenAI-compat model list for %s returned HTTP %s',
                    provider,
                    response.status_code,
                )
                return []
            payload = response.json()
            raw = payload.get('data', []) if isinstance(payload, dict) else []
            models: list[str] = []
            for item in raw:
                if isinstance(item, dict):
                    model_id = item.get('id')
                    if isinstance(model_id, str) and model_id.strip():
                        models.append(model_id.strip())
            return sorted(set(models))
    except Exception as exc:
        logger.debug('OpenAI-compat model list failed for %s: %s', provider, exc)
        return []


def _anthropic_list(api_key: str | None) -> list[str]:
    key = (api_key or '').strip()
    if not key:
        return []
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                'https://api.anthropic.com/v1/models',
                headers={
                    'x-api-key': key,
                    'anthropic-version': '2023-06-01',
                },
            )
            if response.status_code != 200:
                logger.debug('Anthropic model list returned HTTP %s', response.status_code)
                return []
            payload = response.json()
            raw = payload.get('data', []) if isinstance(payload, dict) else []
            models: list[str] = []
            for item in raw:
                if isinstance(item, dict):
                    model_id = item.get('id')
                    if isinstance(model_id, str) and model_id.strip():
                        models.append(model_id.strip())
            return sorted(set(models))
    except Exception as exc:
        logger.debug('Anthropic model list failed: %s', exc)
        return []


def _google_list(api_key: str | None) -> list[str]:
    key = (api_key or '').strip()
    if not key:
        return []
    try:
        from google import genai

        client = genai.Client(api_key=key)
        pager = client.models.list()
        models: list[str] = []
        for model in pager:
            name = getattr(model, 'name', None) or ''
            if not name:
                continue
            bare = name.split('/')[-1] if '/' in name else name
            if bare and 'embed' not in bare.lower():
                models.append(bare)
        return sorted(set(models))
    except Exception as exc:
        logger.debug('Google model list failed: %s', exc)
        return []


def _local_list(provider: str) -> list[str]:
    from backend.inference.provider_resolver import get_resolver

    return get_resolver().get_available_local_models(provider)


def list_models_for_provider(
    provider: str | None,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
) -> list[str]:
    """Unified dynamic model listing for all providers."""
    normalized = normalize_provider_name(provider)
    if normalized is None:
        return []

    if normalized in LOCAL_PROVIDERS:
        return _local_list(normalized)
    if normalized == 'anthropic':
        return _anthropic_list(api_key)
    if normalized == 'google':
        return _google_list(api_key)
    if normalized in OPENAI_COMPAT_PROVIDERS or normalized == 'openai':
        return _openai_compat_list(normalized, api_key, base_url)
    if base_url and api_key:
        return _openai_compat_list(normalized, api_key, base_url)
    return []


def _default_base_url(provider: str) -> str | None:
    from backend.inference.registry import get_default_base_url

    return get_default_base_url(provider)
