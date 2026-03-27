"""Focused tests for settings response helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

import backend.api.routes.settings as settings_routes
from backend.api.routes.settings import (
    _build_default_settings_response,
    _build_recovery_snapshot,
    _ensure_secrets_store,
    _looks_like_model_identifier,
    _provider_token_key_for,
    _secret_value,
    invalidate_settings_cache,
)
from backend.storage.data_models.settings import Settings


def test_build_default_settings_response_includes_startup_snapshot() -> None:
    fake_app_state = MagicMock()
    fake_app_state.get_startup_snapshot.return_value = {
        "resolved_port": 3000,
        "runtime": "local",
    }
    fake_app_state.get_state_restore_snapshot.return_value = {
        "count": 1,
        "recent": [{"source": "checkpoint", "path": "state.checkpoint.json"}],
    }

    with (
        patch("backend.api.routes.settings.get_app_state", return_value=fake_app_state),
        patch(
            "backend.events.stream_stats.get_aggregated_event_stream_stats",
            return_value={"persist_failures": 0, "durable_writer_errors": 0, "streams": 1},
        ),
    ):
        response = _build_default_settings_response()

    assert response.startup_snapshot is not None
    assert response.startup_snapshot["resolved_port"] == 3000
    assert response.recovery_snapshot is not None
    assert response.recovery_snapshot["state_restores"]["recent"][0]["source"] == "checkpoint"
    assert response.llm_api_key is None


def test_secret_value_none_and_str_and_secretstr() -> None:
    assert _secret_value(None) is None
    assert _secret_value("plain") == "plain"
    assert _secret_value(SecretStr("hunter2")) == "hunter2"


def test_looks_like_model_identifier() -> None:
    assert _looks_like_model_identifier("anthropic/claude-x") is True
    assert _looks_like_model_identifier("https://api.example/v1") is False
    assert _looks_like_model_identifier("not-a-model") is False


def test_provider_token_key_for_none_model() -> None:
    assert _provider_token_key_for(None) == (None, None)


def test_provider_token_key_for_known_provider() -> None:
    with patch(
        "backend.api.routes.settings.api_key_manager._extract_provider",
        return_value="openai",
    ):
        key, provider = _provider_token_key_for("openai/gpt-4o")

    assert provider == "openai"
    assert key == "OPENAI_API_KEY"


def test_validate_llm_provider_selection_requires_provider_for_unprefixed_model() -> None:
    settings = Settings.model_construct(llm_model="gpt-4o", llm_provider=None)

    with pytest.raises(ValueError, match="llm_provider is required"):
        settings_routes._validate_llm_provider_selection(settings)


def test_resolve_settings_provider_prefers_explicit_provider() -> None:
    settings = Settings(llm_model="gpt-4o", llm_provider="openai")
    assert settings_routes._resolve_settings_provider(settings) == "openai"


def test_ensure_secrets_store_adds_empty_when_missing() -> None:
    bare = Settings.model_construct(agent="Orchestrator", secrets_store=None)
    merged = _ensure_secrets_store(bare)

    assert merged.secrets_store is not None
    assert merged.secrets_store.provider_tokens == {}
    assert merged.agent == "Orchestrator"


def test_ensure_secrets_store_returns_same_when_present() -> None:
    full = Settings(llm_model="x")
    assert full.secrets_store is not None
    out = _ensure_secrets_store(full)
    assert out is full


def test_build_recovery_snapshot_ok_and_degraded() -> None:
    fake_state = MagicMock()
    fake_state.get_state_restore_snapshot.return_value = {
        "count": 0,
        "recent": [],
    }
    with (
        patch("backend.api.routes.settings.get_app_state", return_value=fake_state),
        patch(
            "backend.events.stream_stats.get_aggregated_event_stream_stats",
            return_value={"persist_failures": 0, "durable_writer_errors": 0},
        ),
    ):
        snap = _build_recovery_snapshot(limit=3)

    assert snap is not None
    assert snap["status"] == "ok"
    fake_state.get_state_restore_snapshot.assert_called_once_with(limit=3)

    with (
        patch("backend.api.routes.settings.get_app_state", return_value=fake_state),
        patch(
            "backend.events.stream_stats.get_aggregated_event_stream_stats",
            return_value={"persist_failures": 1, "durable_writer_errors": 0},
        ),
    ):
        snap2 = _build_recovery_snapshot()

    assert snap2["status"] == "degraded"


def test_build_recovery_snapshot_on_app_state_error() -> None:
    with patch(
        "backend.api.routes.settings.get_app_state",
        side_effect=RuntimeError("no state"),
    ):
        snap = _build_recovery_snapshot()

    assert snap is not None
    assert snap["status"] == "error"
    assert "no state" in snap["detail"]


def test_invalidate_settings_cache_clears_all_or_one_user() -> None:
    mock_response = MagicMock()
    settings_routes._settings_cache.clear()
    settings_routes._settings_cache["alice"] = (mock_response, 0.0)
    settings_routes._settings_cache["bob"] = (mock_response, 0.0)

    invalidate_settings_cache("alice")

    assert "alice" not in settings_routes._settings_cache
    assert "bob" in settings_routes._settings_cache

    invalidate_settings_cache(None)
    assert settings_routes._settings_cache == {}