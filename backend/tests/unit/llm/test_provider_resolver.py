"""Unit tests for backend.llm.provider_resolver."""

from __future__ import annotations

import socket
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

import httpx

from backend.llm.provider_resolver import (
    LOCAL_ENDPOINTS,
    ProviderResolver,
    check_local_providers,
    discover_all_local_models,
    get_resolver,
)


class TestProviderResolver(TestCase):
    """Test ProviderResolver class."""

    def setUp(self):
        """Set up test fixtures."""
        self.resolver = ProviderResolver()

    def test_init(self):
        """Test ProviderResolver initialization."""
        resolver = ProviderResolver()
        self.assertEqual(resolver._discovered_endpoints, {})
        self.assertEqual(resolver._discovery_cache_ttl, 300)
        self.assertEqual(resolver._last_discovery, 0.0)

    def test_resolve_provider_from_catalog(self):
        """Test resolve_provider uses catalog lookup."""
        with patch("backend.llm.provider_resolver.lookup") as mock_lookup:
            mock_entry = MagicMock()
            mock_entry.provider = "openai"
            mock_lookup.return_value = mock_entry

            result = self.resolver.resolve_provider("gpt-4o")

            mock_lookup.assert_called_once_with("gpt-4o")
            self.assertEqual(result, "openai")

    def test_resolve_provider_claude(self):
        """Test resolve_provider identifies Claude models."""
        with patch("backend.llm.provider_resolver.lookup", return_value=None):
            self.assertEqual(
                self.resolver.resolve_provider("claude-3-7-sonnet"), "anthropic"
            )
            self.assertEqual(
                self.resolver.resolve_provider("claude-opus-4"), "anthropic"
            )
            self.assertEqual(
                self.resolver.resolve_provider("anthropic-model"), "anthropic"
            )

    def test_resolve_provider_gemini(self):
        """Test resolve_provider identifies Gemini models."""
        with patch("backend.llm.provider_resolver.lookup", return_value=None):
            self.assertEqual(
                self.resolver.resolve_provider("gemini-2.0-flash"), "google"
            )
            self.assertEqual(self.resolver.resolve_provider("google-model"), "google")

    def test_resolve_provider_xai(self):
        """Test resolve_provider identifies xAI models."""
        with patch("backend.llm.provider_resolver.lookup", return_value=None):
            self.assertEqual(self.resolver.resolve_provider("grok-3"), "xai")
            self.assertEqual(self.resolver.resolve_provider("xai-model"), "xai")

    def test_resolve_provider_ollama(self):
        """Test resolve_provider identifies Ollama models."""
        with patch("backend.llm.provider_resolver.lookup", return_value=None):
            self.assertEqual(
                self.resolver.resolve_provider("ollama/llama3.2"), "ollama"
            )
            self.assertEqual(
                self.resolver.resolve_provider("ollama-model"), "ollama"
            )

    def test_resolve_provider_deepseek(self):
        """Test resolve_provider identifies DeepSeek models."""
        with patch("backend.llm.provider_resolver.lookup", return_value=None):
            self.assertEqual(
                self.resolver.resolve_provider("deepseek-chat"), "deepseek"
            )
            self.assertEqual(
                self.resolver.resolve_provider("deepseek-coder"), "deepseek"
            )

    def test_resolve_provider_mistral(self):
        """Test resolve_provider identifies Mistral models."""
        with patch("backend.llm.provider_resolver.lookup", return_value=None):
            self.assertEqual(
                self.resolver.resolve_provider("mistral-large"), "mistral"
            )
            self.assertEqual(
                self.resolver.resolve_provider("codestral-latest"), "mistral"
            )

    def test_resolve_provider_default_openai(self):
        """Test resolve_provider defaults to openai for unknown models."""
        with patch("backend.llm.provider_resolver.lookup", return_value=None):
            self.assertEqual(
                self.resolver.resolve_provider("unknown-model"), "openai"
            )

    def test_is_local_model_true(self):
        """Test is_local_model identifies local models."""
        self.assertTrue(self.resolver.is_local_model("ollama/llama3.2"))
        self.assertTrue(self.resolver.is_local_model("lm-studio/qwen"))
        self.assertTrue(self.resolver.is_local_model("lmstudio/model"))
        self.assertTrue(self.resolver.is_local_model("vllm/mistral"))
        self.assertTrue(self.resolver.is_local_model("local-model"))

    def test_is_local_model_false(self):
        """Test is_local_model returns False for cloud models."""
        self.assertFalse(self.resolver.is_local_model("gpt-4o"))
        self.assertFalse(self.resolver.is_local_model("claude-3-7-sonnet"))
        self.assertFalse(self.resolver.is_local_model("gemini-2.0-flash"))

    def test_resolve_base_url_explicit(self):
        """Test resolve_base_url returns explicit URL if provided."""
        result = self.resolver.resolve_base_url(
            "any-model", explicit_base_url="https://custom.api"
        )
        self.assertEqual(result, "https://custom.api")

    def test_resolve_base_url_xai(self):
        """Test resolve_base_url returns xAI endpoint."""
        with patch("backend.llm.provider_resolver.lookup", return_value=None):
            result = self.resolver.resolve_base_url("grok-3")
            self.assertEqual(result, "https://api.x.ai/v1")

    def test_resolve_base_url_deepseek(self):
        """Test resolve_base_url returns DeepSeek endpoint."""
        with patch("backend.llm.provider_resolver.lookup", return_value=None):
            result = self.resolver.resolve_base_url("deepseek-chat")
            self.assertEqual(result, "https://api.deepseek.com/v1")

    def test_resolve_base_url_cloud_providers(self):
        """Test resolve_base_url returns None for cloud providers."""
        with patch("backend.llm.provider_resolver.lookup", return_value=None):
            self.assertIsNone(self.resolver.resolve_base_url("gpt-4o"))
            self.assertIsNone(self.resolver.resolve_base_url("claude-3-7-sonnet"))
            self.assertIsNone(self.resolver.resolve_base_url("gemini-2.0-flash"))

    def test_resolve_base_url_ollama_from_env(self):
        """Test resolve_base_url uses OLLAMA_HOST environment variable."""
        with patch("backend.llm.provider_resolver.lookup", return_value=None):
            with patch.dict("os.environ", {"OLLAMA_HOST": "http://custom:11434"}):
                result = self.resolver.resolve_base_url("ollama/llama3.2")
                self.assertEqual(result, "http://custom:11434/v1")

    def test_resolve_base_url_ollama_env_with_v1(self):
        """Test resolve_base_url preserves /v1 if already in env var."""
        with patch("backend.llm.provider_resolver.lookup", return_value=None):
            with patch.dict(
                "os.environ", {"OLLAMA_HOST": "http://custom:11434/v1"}
            ):
                result = self.resolver.resolve_base_url("ollama/llama3.2")
                self.assertEqual(result, "http://custom:11434/v1")

    def test_resolve_base_url_ollama_auto_discover(self):
        """Test resolve_base_url auto-discovers Ollama endpoint."""
        with patch("backend.llm.provider_resolver.lookup", return_value=None):
            with patch.object(
                self.resolver, "discover_local_endpoint", return_value="http://localhost:11434/v1"
            ) as mock_discover:
                result = self.resolver.resolve_base_url("ollama/llama3.2")
                mock_discover.assert_called_once_with("ollama")
                self.assertEqual(result, "http://localhost:11434/v1")

    def test_discover_local_endpoint_cached(self):
        """Test discover_local_endpoint returns cached result."""
        self.resolver._discovered_endpoints["ollama"] = "http://localhost:11434"

        result = self.resolver.discover_local_endpoint("ollama")

        self.assertEqual(result, "http://localhost:11434")

    def test_discover_local_endpoint_probes_endpoints(self):
        """Test discover_local_endpoint probes configured endpoints."""
        with patch.object(
            self.resolver, "_probe_endpoint", return_value=True
        ) as mock_probe:
            result = self.resolver.discover_local_endpoint("ollama")

            mock_probe.assert_called()
            self.assertEqual(result, LOCAL_ENDPOINTS["ollama"][0])

    def test_discover_local_endpoint_not_found(self):
        """Test discover_local_endpoint returns None when not found."""
        with patch.object(self.resolver, "_probe_endpoint", return_value=False):
            result = self.resolver.discover_local_endpoint("ollama")
            self.assertIsNone(result)

    def test_discover_local_endpoint_unknown_provider(self):
        """Test discover_local_endpoint handles unknown provider."""
        result = self.resolver.discover_local_endpoint("unknown-provider")
        self.assertIsNone(result)

    def test_probe_endpoint_success(self):
        """Test _probe_endpoint returns True when endpoint is reachable."""
        with patch.object(socket, "socket") as mock_socket:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 0
            mock_socket.return_value = mock_sock

            with patch.object(
                self.resolver, "_verify_llm_endpoint", return_value=True
            ) as mock_verify:
                result = self.resolver._probe_endpoint("http://localhost:11434")

                self.assertTrue(result)
                mock_verify.assert_called_once()

    def test_probe_endpoint_port_closed(self):
        """Test _probe_endpoint returns False when port is closed."""
        with patch.object(socket, "socket") as mock_socket:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 1  # Connection refused
            mock_socket.return_value = mock_sock

            result = self.resolver._probe_endpoint("http://localhost:11434")

            self.assertFalse(result)

    def test_probe_endpoint_invalid_url(self):
        """Test _probe_endpoint handles invalid URLs gracefully."""
        result = self.resolver._probe_endpoint("invalid-url")
        self.assertFalse(result)

    def test_verify_llm_endpoint_success(self):
        """Test _verify_llm_endpoint identifies valid LLM endpoint."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(httpx, "Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value = mock_client

            result = self.resolver._verify_llm_endpoint("http://localhost:11434")

            self.assertTrue(result)
            mock_client.close.assert_called_once()

    def test_verify_llm_endpoint_auth_required(self):
        """Test _verify_llm_endpoint accepts 401/403 as valid endpoints."""
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch.object(httpx, "Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value = mock_client

            result = self.resolver._verify_llm_endpoint("http://localhost:11434")

            self.assertTrue(result)

    def test_verify_llm_endpoint_not_found(self):
        """Test _verify_llm_endpoint returns False for 404."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch.object(httpx, "Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value = mock_client

            result = self.resolver._verify_llm_endpoint("http://localhost:11434")

            self.assertFalse(result)

    def test_verify_llm_endpoint_connection_error(self):
        """Test _verify_llm_endpoint handles connection errors."""
        with patch.object(httpx, "Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.side_effect = httpx.ConnectError("Connection failed")
            mock_client_class.return_value = mock_client

            result = self.resolver._verify_llm_endpoint("http://localhost:11434")

            self.assertFalse(result)

    def test_get_available_local_models_ollama(self):
        """Test get_available_local_models for Ollama."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [{"name": "llama3.2"}, {"name": "codellama"}]
        }

        with patch.object(
            self.resolver,
            "discover_local_endpoint",
            return_value="http://localhost:11434/v1",
        ):
            with patch.object(httpx, "Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.get.return_value = mock_response
                mock_client_class.return_value = mock_client

                result = self.resolver.get_available_local_models("ollama")

                self.assertEqual(result, ["llama3.2", "codellama"])
                mock_client.close.assert_called_once()

    def test_get_available_local_models_openai_compatible(self):
        """Test get_available_local_models for OpenAI-compatible endpoints."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"id": "model1"}, {"id": "model2"}]
        }

        with patch.object(
            self.resolver,
            "discover_local_endpoint",
            return_value="http://localhost:1234/v1",
        ):
            with patch.object(httpx, "Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.get.return_value = mock_response
                mock_client_class.return_value = mock_client

                result = self.resolver.get_available_local_models("lm_studio")

                self.assertEqual(result, ["model1", "model2"])

    def test_get_available_local_models_no_endpoint(self):
        """Test get_available_local_models returns empty list when no endpoint."""
        with patch.object(self.resolver, "discover_local_endpoint", return_value=None):
            result = self.resolver.get_available_local_models("ollama")
            self.assertEqual(result, [])

    def test_get_available_local_models_error(self):
        """Test get_available_local_models handles errors gracefully."""
        with patch.object(
            self.resolver,
            "discover_local_endpoint",
            return_value="http://localhost:11434/v1",
        ):
            with patch.object(httpx, "Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.get.side_effect = httpx.ConnectError("Failed")
                mock_client_class.return_value = mock_client

                result = self.resolver.get_available_local_models("ollama")

                self.assertEqual(result, [])

    def test_strip_provider_prefix_with_known_prefix(self):
        """Test strip_provider_prefix removes known provider prefixes."""
        self.assertEqual(
            self.resolver.strip_provider_prefix("ollama/llama3.2"), "llama3.2"
        )
        self.assertEqual(
            self.resolver.strip_provider_prefix("anthropic/claude-opus-4"),
            "claude-opus-4",
        )
        self.assertEqual(
            self.resolver.strip_provider_prefix("openai/gpt-4o"), "gpt-4o"
        )
        self.assertEqual(
            self.resolver.strip_provider_prefix("google/gemini-2.0-flash"),
            "gemini-2.0-flash",
        )

    def test_strip_provider_prefix_with_unknown_prefix(self):
        """Test strip_provider_prefix preserves unknown prefixes."""
        self.assertEqual(
            self.resolver.strip_provider_prefix("custom/model"), "custom/model"
        )

    def test_strip_provider_prefix_no_prefix(self):
        """Test strip_provider_prefix returns original when no prefix."""
        self.assertEqual(
            self.resolver.strip_provider_prefix("llama3.2"), "llama3.2"
        )
        self.assertEqual(self.resolver.strip_provider_prefix("gpt-4o"), "gpt-4o")

    def test_strip_provider_prefix_case_insensitive(self):
        """Test strip_provider_prefix is case-insensitive."""
        self.assertEqual(
            self.resolver.strip_provider_prefix("OLLAMA/llama3.2"), "llama3.2"
        )
        self.assertEqual(
            self.resolver.strip_provider_prefix("Anthropic/claude-opus-4"),
            "claude-opus-4",
        )


class TestGetResolver(TestCase):
    """Test get_resolver singleton function."""

    def test_returns_provider_resolver(self):
        """Test get_resolver returns a ProviderResolver instance."""
        resolver = get_resolver()
        self.assertIsInstance(resolver, ProviderResolver)

    def test_returns_same_instance(self):
        """Test get_resolver returns the same instance (singleton)."""
        resolver1 = get_resolver()
        resolver2 = get_resolver()
        self.assertIs(resolver1, resolver2)

    def test_lru_cache_behavior(self):
        """Test that get_resolver is cached with lru_cache."""
        # Clear cache
        get_resolver.cache_clear()

        resolver1 = get_resolver()
        cache_info = get_resolver.cache_info()

        # First call should be a miss
        self.assertEqual(cache_info.misses, 1)

        resolver2 = get_resolver()
        cache_info = get_resolver.cache_info()

        # Second call should be a hit
        self.assertEqual(cache_info.hits, 1)
        self.assertIs(resolver1, resolver2)


class TestDiscoverAllLocalModels(TestCase):
    """Test discover_all_local_models function."""

    def test_discover_all_local_models_success(self):
        """Test discover_all_local_models returns models from all providers."""
        with patch("backend.llm.provider_resolver.get_resolver") as mock_get_resolver:
            mock_resolver = MagicMock()
            mock_resolver.get_available_local_models.side_effect = (
                lambda provider: {
                    "ollama": ["llama3.2", "codellama"],
                    "lm_studio": ["qwen"],
                    "vllm": [],
                }.get(provider, [])
            )
            mock_get_resolver.return_value = mock_resolver

            result = discover_all_local_models()

            self.assertEqual(
                result, {"ollama": ["llama3.2", "codellama"], "lm_studio": ["qwen"]}
            )

    def test_discover_all_local_models_no_models(self):
        """Test discover_all_local_models returns empty dict when no models."""
        with patch("backend.llm.provider_resolver.get_resolver") as mock_get_resolver:
            mock_resolver = MagicMock()
            mock_resolver.get_available_local_models.return_value = []
            mock_get_resolver.return_value = mock_resolver

            result = discover_all_local_models()

            self.assertEqual(result, {})


class TestCheckLocalProviders(TestCase):
    """Test check_local_providers function."""

    def test_check_local_providers_all_running(self):
        """Test check_local_providers when all providers are running."""
        with patch("backend.llm.provider_resolver.get_resolver") as mock_get_resolver:
            mock_resolver = MagicMock()
            mock_resolver._probe_endpoint.return_value = True
            mock_get_resolver.return_value = mock_resolver

            result = check_local_providers()

            self.assertTrue(result["ollama"])
            self.assertTrue(result["lm_studio"])
            self.assertTrue(result["vllm"])

    def test_check_local_providers_none_running(self):
        """Test check_local_providers when no providers are running."""
        with patch("backend.llm.provider_resolver.get_resolver") as mock_get_resolver:
            mock_resolver = MagicMock()
            mock_resolver._probe_endpoint.return_value = False
            mock_get_resolver.return_value = mock_resolver

            result = check_local_providers()

            self.assertFalse(result["ollama"])
            self.assertFalse(result["lm_studio"])
            self.assertFalse(result["vllm"])

    def test_check_local_providers_partial(self):
        """Test check_local_providers with some providers running."""
        with patch("backend.llm.provider_resolver.get_resolver") as mock_get_resolver:
            mock_resolver = MagicMock()

            def probe_side_effect(url):
                return "11434" in url  # Only Ollama port

            mock_resolver._probe_endpoint.side_effect = probe_side_effect
            mock_get_resolver.return_value = mock_resolver

            result = check_local_providers()

            self.assertTrue(result["ollama"])
            self.assertFalse(result["lm_studio"])
            self.assertFalse(result["vllm"])


class TestLocalEndpoints(TestCase):
    """Test LOCAL_ENDPOINTS constant."""

    def test_local_endpoints_structure(self):
        """Test LOCAL_ENDPOINTS has expected structure."""
        self.assertIsInstance(LOCAL_ENDPOINTS, dict)
        self.assertIn("ollama", LOCAL_ENDPOINTS)
        self.assertIn("lm_studio", LOCAL_ENDPOINTS)
        self.assertIn("vllm", LOCAL_ENDPOINTS)

    def test_local_endpoints_ollama(self):
        """Test Ollama endpoints."""
        self.assertIsInstance(LOCAL_ENDPOINTS["ollama"], list)
        self.assertTrue(any("11434" in url for url in LOCAL_ENDPOINTS["ollama"]))

    def test_local_endpoints_lm_studio(self):
        """Test LM Studio endpoints."""
        self.assertIsInstance(LOCAL_ENDPOINTS["lm_studio"], list)
        self.assertTrue(any("1234" in url for url in LOCAL_ENDPOINTS["lm_studio"]))

    def test_local_endpoints_vllm(self):
        """Test vLLM endpoints."""
        self.assertIsInstance(LOCAL_ENDPOINTS["vllm"], list)
        self.assertTrue(any("8000" in url for url in LOCAL_ENDPOINTS["vllm"]))


if __name__ == "__main__":
    import unittest

    unittest.main()
