"""Provider resolution and local endpoint discovery.

This module implements the "Provider Auto-Resolver" pattern, automatically
detecting local LLM endpoints (Ollama, LM Studio, vLLM) and routing models
to the correct provider without manual configuration.
"""

from __future__ import annotations

import functools
import socket
from typing import Any

import httpx

from backend.core.logger import FORGE_logger as logger
from backend.llm.catalog_loader import lookup

# Common local provider endpoints
LOCAL_ENDPOINTS = {
    "ollama": ["http://localhost:11434", "http://127.0.0.1:11434"],
    "lm_studio": ["http://localhost:1234", "http://127.0.0.1:1234"],
    "vllm": ["http://localhost:8000", "http://127.0.0.1:8000"],
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
        """
        # Check catalog first
        entry = lookup(model_name)
        if entry:
            return entry.provider

        # Heuristic fallback for unknown models
        model_lower = model_name.lower()

        if "claude" in model_lower or "anthropic" in model_lower:
            return "anthropic"
        if "gemini" in model_lower or "google" in model_lower:
            return "google"
        if "grok" in model_lower or "xai" in model_lower:
            return "xai"
        if "ollama" in model_lower:
            return "ollama"
        if "deepseek" in model_lower:
            return "deepseek"
        if "mistral" in model_lower or "codestral" in model_lower:
            return "mistral"

        # Default to OpenAI-compatible
        return "openai"

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
            for provider in ["ollama", "lm-studio", "lmstudio", "vllm", "local"]
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

        # Check environment variables
        import os

        if provider == "ollama":
            env_url = os.getenv("OLLAMA_HOST") or os.getenv("OLLAMA_BASE_URL")
            if env_url:
                # Ensure it has /v1 suffix for OpenAI compatibility
                return env_url if "/v1" in env_url else f"{env_url}/v1"

        # Auto-discover local endpoints if not already done
        if self.is_local_model(model_name) or provider in [
            "ollama",
            "lm_studio",
            "vllm",
        ]:
            discovered = self.discover_local_endpoint(provider)
            if discovered:
                return discovered

        # Provider-specific defaults
        if provider == "xai":
            return "https://api.x.ai/v1"
        if provider == "deepseek":
            return "https://api.deepseek.com/v1"

        # Cloud providers use default endpoints (None)
        return None

    def discover_local_endpoint(self, provider: str) -> str | None:
        """Discover a local endpoint for a provider.

        Probes common ports to find running services.

        Args:
            provider: Provider name (e.g., "ollama", "lm_studio")

        Returns:
            Discovered endpoint URL or None
        """
        # Check cache first
        if provider in self._discovered_endpoints:
            return self._discovered_endpoints[provider]

        endpoints = LOCAL_ENDPOINTS.get(provider, [])

        for url in endpoints:
            if self._probe_endpoint(url):
                logger.info("Discovered %s endpoint at %s", provider, url)
                self._discovered_endpoints[provider] = url
                return url

        logger.debug("No local endpoint found for %s", provider)
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
            if "localhost" in url or "127.0.0.1" in url:
                # Extract port
                port_str = url.split(":")[-1].split("/")[0]
                port = int(port_str)

                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                result = sock.connect_ex(("127.0.0.1", port))
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
            client = httpx.Client(timeout=timeout, follow_redirects=True)
            test_urls = [
                f"{url}/v1/models",
                f"{url}/models",
                f"{url}/api/tags",  # Ollama specific
            ]

            for test_url in test_urls:
                try:
                    response = client.get(test_url)
                    if response.status_code in (200, 401, 403):
                        # 200 = success, 401/403 = auth required but endpoint exists
                        client.close()
                        return True
                except Exception:
                    continue

            client.close()
        except Exception:
            pass

        return False

    def get_available_local_models(self, provider: str = "ollama") -> list[str]:
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
            client = httpx.Client(timeout=5.0)

            if provider == "ollama":
                # Ollama API
                response = client.get(f"{endpoint.replace('/v1', '')}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    models = [m["name"] for m in data.get("models", [])]
                    client.close()
                    return models
            else:
                # OpenAI-compatible /v1/models
                response = client.get(f"{endpoint}/v1/models")
                if response.status_code == 200:
                    data = response.json()
                    models = [m["id"] for m in data.get("data", [])]
                    client.close()
                    return models

            client.close()
        except Exception as e:
            logger.debug("Failed to query %s models: %s", provider, e)

        return []

    def strip_provider_prefix(self, model_name: str) -> str:
        """Remove provider prefix from model name.

        Args:
            model_name: Model name (e.g., "ollama/llama3", "anthropic/claude-opus-4")

        Returns:
            Stripped model name (e.g., "llama3", "claude-opus-4")
        """
        if "/" in model_name:
            parts = model_name.split("/", 1)
            # Only strip if the prefix is actually a known provider
            prefix = parts[0].lower()
            if prefix in [
                "ollama",
                "openai",
                "anthropic",
                "google",
                "gemini",
                "xai",
                "deepseek",
                "mistral",
            ]:
                return parts[1]
        return model_name


# Global resolver instance
_resolver: ProviderResolver | None = None


@functools.lru_cache(maxsize=1)
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

    for provider in ["ollama", "lm_studio", "vllm"]:
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
