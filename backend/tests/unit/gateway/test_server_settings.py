"""Tests for backend.gateway.settings Pydantic models."""

from __future__ import annotations

import logging
from typing import Any as TypingAny

import pytest


class TestMcpConfigImportFallback:
    def test_mcp_config_type_fallback_logs_and_returns_any(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When the MCPConfig import fails, fall back to typing.Any and log a warning."""
        import backend.gateway.settings as settings_mod

        def _raise() -> type:
            raise ImportError("simulated MCP import failure")

        monkeypatch.setattr(settings_mod, "_import_mcp_config_class", _raise)
        with caplog.at_level(logging.WARNING, logger="backend.gateway.settings"):
            out = settings_mod._mcp_config_type_with_fallback()
        assert out is TypingAny
        assert any(
            "Failed to import MCPConfig" in r.getMessage() for r in caplog.records
        )


class TestPOSTProviderModel:
    def test_defaults(self):
        from backend.gateway.settings import POSTProviderModel

        model = POSTProviderModel()
        assert model.mcp_config is None
        assert model.provider_tokens == {}

    def test_with_tokens(self):
        from backend.gateway.settings import POSTProviderModel

        model = POSTProviderModel(provider_tokens={"openai": {"token": "sk-123"}})
        assert "openai" in model.provider_tokens


class TestPOSTCustomSecrets:
    def test_defaults(self):
        from backend.gateway.settings import POSTCustomSecrets

        model = POSTCustomSecrets()
        assert model.custom_secrets == {}


class TestCustomSecretModels:
    def test_without_value(self):
        from backend.gateway.settings import CustomSecretWithoutValueModel

        model = CustomSecretWithoutValueModel(name="MY_SECRET")
        assert model.name == "MY_SECRET"
        assert model.description is None

    def test_with_description(self):
        from backend.gateway.settings import CustomSecretWithoutValueModel

        model = CustomSecretWithoutValueModel(name="API_KEY", description="My API key")
        assert model.description == "My API key"

    def test_with_value(self):
        from backend.gateway.settings import CustomSecretModel

        model = CustomSecretModel(
            name="TOKEN", value="secret-value", description="A token"
        )
        assert model.name == "TOKEN"
        assert model.value.get_secret_value() == "secret-value"

    def test_inheritance(self):
        from backend.gateway.settings import (
            CustomSecretModel,
            CustomSecretWithoutValueModel,
        )

        assert issubclass(CustomSecretModel, CustomSecretWithoutValueModel)


class TestGETCustomSecrets:
    def test_defaults(self):
        from backend.gateway.settings import GETCustomSecrets

        model = GETCustomSecrets()
        assert model.custom_secrets is None

    def test_with_secrets(self):
        from backend.gateway.settings import (
            CustomSecretWithoutValueModel,
            GETCustomSecrets,
        )

        model = GETCustomSecrets(
            custom_secrets=[
                CustomSecretWithoutValueModel(name="KEY1"),
                CustomSecretWithoutValueModel(name="KEY2", description="desc"),
            ]
        )
        assert model.custom_secrets is not None
        assert len(model.custom_secrets) == 2
        assert model.custom_secrets[0].name == "KEY1"
