"""Provider resolution and local endpoint discovery.

Provider resolution is intentionally strict for configured models: App trusts
an explicit provider prefix (``provider/model``) or an exact catalog entry, and
does not infer providers from model-name patterns.
"""

from __future__ import annotations

import socket
import time

import httpx

from backend.core.logger import app_logger as logger
from backend.inference.catalog_loader import ModelEntry, lookup

_PROVIDER_DEFAULT_URLS: dict[str, str] = {
    'groq': 'https://api.groq.com/openai/v1',
    'xai': 'https://api.x.ai/v1',
    'deepseek': 'https://api.deepseek.com/v1',
    'openrouter': 'https://openrouter.ai/api/v1',
    'openhands': 'https://llm-proxy.app.all-hands.dev/v1',
    'nvidia': 'https://integrate.api.nvidia.com/v1',
    'lightning': 'https://api.lightning.ai/v1',
}

KNOWN_PROVIDER_PREFIXES: set[str] = {
    'anthropic',
    'deepinfra',
    'deepseek',
    'fireworks',
    'google',
    'groq',
    'lightning',
    'lm_studio',
    'mistral',
    'nvidia',
    'ollama',
    'openai',
    'openhands',
    'openrouter',
    'perplexity',
    'replicate',
    'together',
    'vllm',
    'xai',
}


def normalize_provider_name(provider: str | None) -> str | None:
    """Normalize provider names for stable comparisons."""
    if provider is None:
        return None
    normalized = str(provider).strip().lower()
    if not normalized:
        return None
    return normalized


def extract_provider_prefix(model_name: str | None) -> str | None:
    """Extract a known provider prefix from a model string if present."""
    if not model_name or '/' not in model_name:
        return None
    prefix = normalize_provider_name(model_name.split('/', 1)[0])
    if prefix in KNOWN_PROVIDER_PREFIXES:
        return prefix
    return None


def _catalog_entry_matches_exactly(model_name: str, entry: ModelEntry) -> bool:
    """Return True when a catalog hit came from an exact name or alias match."""
    model_lower = model_name.strip().lower()
    if model_lower == entry.name.lower():
        return True
    return any(model_lower == alias.lower() for alias in entry.aliases)


def canonicalize_model_selection(
    model_name: str | None, provider: str | None
) -> tuple[str | None, str | None]:
    """Canonicalize a settings-level provider/model pair.

    Returns a tuple of (model, provider) where model is prefixed with the
    explicit provider when possible, and provider is inferred from a known
    prefix if the caller omitted it.
    """
    if model_name is None:
        return None, normalize_provider_name(provider)

    model = str(model_name).strip()
    if not model:
        return None, normalize_provider_name(provider)

    normalized_provider = normalize_provider_name(provider)
    prefixed_provider = extract_provider_prefix(model)

    if normalized_provider:
        if prefixed_provider:
            prefix = model.split('/', 1)[0]
            stripped = model[len(prefix) + 1 :]
        else:
            stripped = model
        return f'{normalized_provider}/{stripped}', normalized_provider

    if prefixed_provider:
        return model, prefixed_provider

    return model, None


def _resolve_ollama_env_url() -> str | None:
    """Return OLLAMA_HOST or OLLAMA_BASE_URL if set, with /v1 suffix if missing."""
    import os

    env_url = os.getenv('OLLAMA_HOST') or os.getenv('OLLAMA_BASE_URL')
    if not env_url:
        return None
    return env_url if '/v1' in env_url else f'{env_url}/v1'


# Common local provider endpoints
LOCAL_ENDPOINTS = {
    'ollama': ['http://localhost:11434', 'http://127.0.0.1:11434'],
    'lm_studio': ['http://localhost:1234', 'http://127.0.0.1:1234'],
    'vllm': ['http://localhost:8000', 'http://127.0.0.1:8000'],
}


class ProviderResolver:
    """Resolves models to providers and discovers local endpoints."""

    def __init__(self):
        self._discovered_endpoints: dict[str, str] = {}
        self._discovery_cache_ttl = 300  # 5 minutes
        self._last_discovery = 0.0

    def resolve_provider(self, model_name: str) -> str:
        """Determine the provider for a given model.

        Args:
            model_name: Model name (e.g., "gpt-4o", "claude-opus-4", "llama3")

        Returns:
            Provider name (e.g., "openai", "anthropic", "ollama")

        Raises:
            ValueError: When provider is not explicit and the model is not an
                exact catalog entry.
        """
        prefixed_provider = extract_provider_prefix(model_name)
        if prefixed_provider:
            return prefixed_provider

        entry = lookup(model_name)
        if entry:
            if '/' in model_name and not _catalog_entry_matches_exactly(
                model_name, entry
            ):
                raise ValueError(
                    'Provider is ambiguous for model '
                    f"'{model_name}'. Use an explicit provider prefix like 'openai/{model_name}' "
                    'or configure llm_provider alongside llm_model.'
                )
            return entry.provider

        raise ValueError(
            'Provider is ambiguous for model '
            f"'{model_name}'. Use an explicit provider prefix like 'openai/{model_name}' "
            'or configure llm_provider alongside llm_model.'
        )

    def is_local_model(self, model_name: str) -> bool:
        """Check if a model is intended for local execution.

        Args:
            model_name: Model name

        Returns:
            True if model should run locally
        """
        model_lower = model_name.lower()
        return any(
            provider in model_lower
            for provider in ['ollama', 'lm_studio', 'vllm', 'local']
        )

    def resolve_base_url(
        self, model_name: str, explicit_base_url: str | None = None
    ) -> str | None:
        """Resolve the base URL for a model.

        Priority:
        1. Explicit base_url parameter
        2. Environment variables (OLLAMA_HOST, etc.)
        3. Auto-discovered local endpoints
        4. Provider default (None for cloud APIs)

        Args:
            model_name: Model name
            explicit_base_url: User-provided base URL

        Returns:
            Base URL or None for default cloud endpoints
        """
        if explicit_base_url:
            return explicit_base_url

        provider = self.resolve_provider(model_name)

        if provider == 'ollama' and (url := _resolve_ollama_env_url()):
            return url

        if self.is_local_model(model_name) or provider in (
            'ollama',
            'lm_studio',
            'vllm',
        ):
            discovered = self.discover_local_endpoint(provider)
            if discovered:
                return discovered

        return _PROVIDER_DEFAULT_URLS.get(provider)

    def discover_local_endpoint(self, provider: str) -> str | None:
        """Discover a local endpoint for a provider.

        Probes common ports to find running services.

        Args:
            provider: Provider name (e.g., "ollama", "lm_studio")

        Returns:
            Discovered endpoint URL or None
        """
        # Check cache first, respecting TTL
        now = time.monotonic()
        if provider in self._discovered_endpoints:
            if now - self._last_discovery < self._discovery_cache_ttl:
                return self._discovered_endpoints[provider]
            # TTL expired — re-probe
            del self._discovered_endpoints[provider]

        endpoints = LOCAL_ENDPOINTS.get(provider, [])

        for url in endpoints:
            if self._probe_endpoint(url):
                logger.info('Discovered %s endpoint at %s', provider, url)
                self._discovered_endpoints[provider] = url
                self._last_discovery = now
                return url

        logger.debug('No local endpoint found for %s', provider)
        return None

    def _probe_endpoint(self, url: str, timeout: float = 2.0) -> bool:
        """Check if an endpoint is reachable.

        Args:
            url: Endpoint URL to probe
            timeout: Connection timeout in seconds

        Returns:
            True if endpoint is reachable
        """
        try:
            # First try a socket connection (faster)
            if 'localhost' in url or '127.0.0.1' in url:
                # Extract port
                port_str = url.split(':')[-1].split('/')[0]
                port = int(port_str)

                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                result = sock.connect_ex(('127.0.0.1', port))
                sock.close()

                if result == 0:
                    # Port is open, verify it's actually an LLM endpoint
                    return self._verify_llm_endpoint(url, timeout)
                return False
        except Exception:
            pass

        return False

    def _verify_llm_endpoint(self, url: str, timeout: float = 2.0) -> bool:
        """Verify an endpoint is actually an LLM API.

        Args:
            url: Endpoint URL
            timeout: Request timeout

        Returns:
            True if endpoint responds to /v1/models or similar
        """
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                test_urls = [
                    f'{url}/v1/models',
                    f'{url}/models',
                    f'{url}/api/tags',  # Ollama specific
                ]

                for test_url in test_urls:
                    try:
                        response = client.get(test_url)
                        if response.status_code in (200, 401, 403):
                            # 200 = success, 401/403 = auth required but endpoint exists
                            return True
                    except Exception:
                        continue
        except Exception:
            pass

        return False

    def get_available_local_models(self, provider: str = 'ollama') -> list[str]:
        """Query available models from a local provider.

        Args:
            provider: Provider name (e.g., "ollama")

        Returns:
            List of available model names
        """
        endpoint = self.discover_local_endpoint(provider)
        if not endpoint:
            return []

        try:
            with httpx.Client(timeout=5.0) as client:
                if provider == 'ollama':
                    # Ollama API
                    response = client.get(f'{endpoint.replace("/v1", "")}/api/tags')
                    if response.status_code == 200:
                        data = response.json()
                        return [m['name'] for m in data.get('models', [])]
                else:
                    # OpenAI-compatible /v1/models
                    response = client.get(f'{endpoint}/v1/models')
                    if response.status_code == 200:
                        data = response.json()
                        return [m['id'] for m in data.get('data', [])]
        except Exception as e:
            logger.debug('Failed to query %s models: %s', provider, e)

        return []

    def strip_provider_prefix(self, model_name: str) -> str:
        """Remove provider prefix from model name.

        Args:
            model_name: Model name (e.g., "ollama/llama3", "anthropic/claude-opus-4")

        Returns:
            Stripped model name (e.g., "llama3", "claude-opus-4")
        """
        if '/' in model_name:
            parts = model_name.split('/', 1)
            # Only strip if the prefix is actually a known provider
            prefix = normalize_provider_name(parts[0])
            if prefix in KNOWN_PROVIDER_PREFIXES:
                return parts[1]
        return model_name


# Global resolver instance
_resolver: ProviderResolver | None = None


def get_resolver() -> ProviderResolver:
    """Get the global provider resolver instance."""
    global _resolver
    if _resolver is None:
        _resolver = ProviderResolver()
    return _resolver


def discover_all_local_models() -> dict[str, list[str]]:
    """Discover all available local models from all providers.

    Returns:
        Dictionary mapping provider names to lists of available models
    """
    resolver = get_resolver()
    results = {}

    for provider in ['ollama', 'lm_studio', 'vllm']:
        models = resolver.get_available_local_models(provider)
        if models:
            results[provider] = models

    return results


def check_local_providers() -> dict[str, bool]:
    """Check which local providers are currently running.

    Returns:
        Dictionary mapping provider names to availability status
    """
    resolver = get_resolver()
    status = {}

    for provider, endpoints in LOCAL_ENDPOINTS.items():
        for url in endpoints:
            if resolver._probe_endpoint(url):
                status[provider] = True
                break
        else:
            status[provider] = False

    return status
