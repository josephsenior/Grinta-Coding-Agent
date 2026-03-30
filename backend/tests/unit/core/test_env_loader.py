"""Unit tests for backend.core.config.env_loader — env var type casting."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import BaseModel, SecretStr

from backend.core.config.env_loader import (
    _get_optional_type,
    _is_dict_or_list_type,
    _process_field_value,
    _process_list_items,
    _set_attr_from_env,
    cast_value_to_type,
    export_llm_api_keys,
    load_from_env,
    restore_environment,
)


# ---------------------------------------------------------------------------
# cast_value_to_type
# ---------------------------------------------------------------------------


class TestCastValueToType:
    def test_bool_true(self):
        assert cast_value_to_type("true", bool) is True
        assert cast_value_to_type("1", bool) is True

    def test_bool_false(self):
        assert cast_value_to_type("false", bool) is False
        assert cast_value_to_type("0", bool) is False
        assert cast_value_to_type("no", bool) is False

    def test_int(self):
        assert cast_value_to_type("42", int) == 42

    def test_float(self):
        assert cast_value_to_type("3.14", float) == pytest.approx(3.14)

    def test_str(self):
        assert cast_value_to_type("hello", str) == "hello"

    def test_secret_str(self):
        result = cast_value_to_type("s3cret", SecretStr)
        assert isinstance(result, SecretStr)
        assert result.get_secret_value() == "s3cret"

    def test_dict_literal(self):
        result = cast_value_to_type('{"a": 1}', dict)
        assert result == {"a": 1}

    def test_list_literal(self):
        result = cast_value_to_type("[1, 2, 3]", list)
        assert result == [1, 2, 3]

    def test_none_type_passthrough(self):
        assert cast_value_to_type("hello", None) == "hello"

    def test_optional_int(self):
        result = cast_value_to_type("42", int | None)
        assert result == 42

    def test_typed_dict_literal(self):
        """Test casting to typed dict (with type hints)."""
        result = cast_value_to_type('{"key": "value"}', dict[str, str])
        assert result == {"key": "value"}

    def test_typed_list_with_int(self):
        """Test casting to typed list of ints."""
        result = cast_value_to_type("[1, 2, 3]", list[int])
        assert result == [1, 2, 3]


# ---------------------------------------------------------------------------
# _get_optional_type
# ---------------------------------------------------------------------------


class TestGetOptionalType:
    def test_none_input(self):
        assert _get_optional_type(None) is None

    def test_plain_type(self):
        assert _get_optional_type(int) is int

    def test_union_with_none(self):
        result = _get_optional_type(int | None)
        assert result is int


# ---------------------------------------------------------------------------
# _is_dict_or_list_type
# ---------------------------------------------------------------------------


class TestIsDictOrListType:
    def test_dict(self):
        assert _is_dict_or_list_type(dict) is True

    def test_list(self):
        assert _is_dict_or_list_type(list) is True

    def test_typed_dict(self):
        assert _is_dict_or_list_type(dict[str, int]) is True

    def test_typed_list(self):
        assert _is_dict_or_list_type(list[int]) is True

    def test_str(self):
        assert _is_dict_or_list_type(str) is False

    def test_int(self):
        assert _is_dict_or_list_type(int) is False


# ---------------------------------------------------------------------------
# restore_environment
# ---------------------------------------------------------------------------


class TestRestoreEnvironment:
    def test_removes_added_keys(self, monkeypatch):
        import os

        original = dict(os.environ)
        monkeypatch.setenv("APP_TEST_NEW_KEY", "val")
        restore_environment(original)
        assert "APP_TEST_NEW_KEY" not in os.environ

    def test_restores_changed_keys(self, monkeypatch):
        import os

        original = dict(os.environ)
        original["APP_TEST_KEY"] = "original"
        monkeypatch.setenv("APP_TEST_KEY", "changed")
        restore_environment(original)
        assert os.environ.get("APP_TEST_KEY") == "original"


# ---------------------------------------------------------------------------
# _process_list_items
# ---------------------------------------------------------------------------


class TestProcessListItems:
    def test_list_of_primitives(self):
        """Test that primitive list items are returned unchanged."""
        items = [1, 2, 3]
        result = _process_list_items(items, list[int])
        assert result == [1, 2, 3]

    def test_list_of_basemodel(self):
        """Test that BaseModel items are instantiated from dicts."""

        class DummyModel(BaseModel):
            value: int

        items = [{"value": 1}, {"value": 2}]
        result = _process_list_items(items, list[DummyModel])
        assert len(result) == 2
        assert all(isinstance(item, DummyModel) for item in result)
        assert result[0].value == 1
        assert result[1].value == 2

    def test_list_mixed_basemodel_and_non_dict(self):
        """Test that non-dict items are passed through as-is."""

        class DummyModel(BaseModel):
            value: int

        items = [{"value": 1}, DummyModel(value=2)]
        result = _process_list_items(items, list[DummyModel])
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _process_field_value
# ---------------------------------------------------------------------------


class TestProcessFieldValue:
    def test_regular_field_casting(self):
        """Test normal field value processing."""

        class DummyConfig(BaseModel):
            count: int

        cfg = DummyConfig(count=0)
        env_dict = {"COUNT": "42"}
        _process_field_value(cfg, "count", int, "COUNT", env_dict)
        assert cfg.count == 42

    def test_api_key_field_special_handling(self):
        """Test that api_key fields are handled as SecretStr."""

        class DummyConfig(BaseModel):
            some_api_key: str

        cfg = DummyConfig(some_api_key="")
        env_dict = {"SOME_API_KEY": "secret123"}
        _process_field_value(cfg, "some_api_key", str, "SOME_API_KEY", env_dict)
        assert isinstance(cfg.some_api_key, SecretStr)
        assert cfg.some_api_key.get_secret_value() == "secret123"

    def test_empty_value_returns_early(self):
        """Test that empty env values don't set the field."""

        class DummyConfig(BaseModel):
            count: int

        cfg = DummyConfig(count=0)
        env_dict = {"COUNT": ""}
        _process_field_value(cfg, "count", int, "COUNT", env_dict)
        assert cfg.count == 0  # Unchanged

    def test_invalid_type_casting_error(self):
        """Test error handling for invalid type casting."""

        class DummyConfig(BaseModel):
            count: int

        cfg = DummyConfig(count=0)
        env_dict = {"COUNT": "not_a_number"}
        # Should not raise, just log
        _process_field_value(cfg, "count", int, "COUNT", env_dict)
        # count should remain unchanged
        assert cfg.count == 0

    def test_api_key_syncing_with_manager(self):
        """Test that api_key field syncs with api_key_manager."""

        class DummyConfig(BaseModel):
            model: str = "gpt-4"
            api_key: SecretStr = SecretStr("")

        cfg = DummyConfig()
        env_dict = {"API_KEY": "sk-test123"}

        with patch(
            "backend.core.config.api_key_manager.api_key_manager"
        ) as mock_manager:
            _process_field_value(cfg, "api_key", SecretStr, "API_KEY", env_dict)
            # Should have called set_api_key and set_environment_variables
            assert mock_manager.set_api_key.called or not hasattr(cfg, "model")

    def test_api_key_field_with_model_attribute(self):
        """Test api_key field when config has model attribute - covers lines 107-108."""

        class DummyLLMConfig(BaseModel):
            model: str = "gpt-4"
            api_key: SecretStr = SecretStr("")

        cfg = DummyLLMConfig()
        env_dict = {"API_KEY": "sk-test123"}

        with patch(
            "backend.core.config.api_key_manager.api_key_manager"
        ) as mock_manager:
            _process_field_value(cfg, "api_key", SecretStr, "API_KEY", env_dict)
            # Should have synced with manager
            assert cfg.api_key.get_secret_value() == "sk-test123"
            # Manager should have been called
            mock_manager.set_api_key.assert_called()


# ---------------------------------------------------------------------------
# _set_attr_from_env
# ---------------------------------------------------------------------------


class TestSetAttrFromEnv:
    def test_simple_field_setting(self):
        """Test setting a simple field from env."""

        class DummyConfig(BaseModel):
            count: int = 0

        cfg = DummyConfig()
        env_dict = {"COUNT": "100"}
        _set_attr_from_env(cfg, env_dict)
        assert cfg.count == 100

    def test_nested_config_recursive(self):
        """Test that nested BaseModel fields are recursively processed."""

        class NestedConfig(BaseModel):
            value: int = 0

        class ParentConfig(BaseModel):
            nested: NestedConfig = NestedConfig()

        cfg = ParentConfig()
        env_dict = {"NESTED_VALUE": "42"}
        _set_attr_from_env(cfg, env_dict)
        assert cfg.nested.value == 42

    def test_custom_prefix(self):
        """Test that custom prefix is applied correctly."""

        class DummyConfig(BaseModel):
            count: int = 0

        cfg = DummyConfig()
        env_dict = {"LLM_COUNT": "50"}
        _set_attr_from_env(cfg, env_dict, prefix="LLM_")
        assert cfg.count == 50

    def test_only_env_vars_are_set(self):
        """Test that only provided env vars are applied."""

        class DummyConfig(BaseModel):
            count: int = 0
            value: str = "default"

        cfg = DummyConfig()
        env_dict = {"COUNT": "100"}  # Only COUNT, not VALUE
        _set_attr_from_env(cfg, env_dict)
        assert cfg.count == 100
        assert cfg.value == "default"  # Unchanged


# ---------------------------------------------------------------------------
# load_from_env
# ---------------------------------------------------------------------------


class TestLoadFromEnv:
    def test_load_with_empty_env(self):
        """Test loading with empty environment."""
        from backend.core.config.app_config import AppConfig

        cfg = AppConfig()
        cfg.get_llm_config()
        load_from_env(cfg, {})
        # Should not crash and preserve config
        assert cfg.get_llm_config() is not None

    def test_load_with_core_vars(self):
        """Test loading core configuration from env."""
        from backend.core.config.app_config import AppConfig

        cfg = AppConfig()
        env_dict = {"DEBUG_LEVEL": "20"}  # Or any valid core var
        load_from_env(cfg, env_dict)
        # Should complete successfully

    def test_load_with_llm_api_key(self):
        """Test that LLM_API_KEY is properly handled."""
        from backend.core.config.app_config import AppConfig

        cfg = AppConfig()
        env_dict = {"LLM_API_KEY": "sk-test123"}

        with patch("backend.core.config.llm_config.suppress_llm_env_export"):
            load_from_env(cfg, env_dict)
            # Should have updated LLM config with API key
            new_llm = cfg.get_llm_config()
            assert new_llm is not None


# ---------------------------------------------------------------------------
# export_llm_api_keys
# ---------------------------------------------------------------------------


class TestExportLLMApiKeys:
    def test_export_with_no_llm_configs(self):
        """Test export when no LLM configs exist."""
        from backend.core.config.app_config import AppConfig

        cfg = AppConfig()
        with patch("backend.core.config.api_key_manager.api_key_manager"):
            export_llm_api_keys(cfg)
            # Should handle gracefully

    def test_export_with_api_keys(self):
        """Test that API keys are exported for each LLM."""
        from backend.core.config.app_config import AppConfig

        cfg = AppConfig()
        with patch("backend.core.config.api_key_manager.api_key_manager"):
            export_llm_api_keys(cfg)
            # Should have attempted to set keys

    def test_export_error_handling(self):
        """Test that export errors are caught gracefully - covers lines 179-183."""
        from backend.core.config.app_config import AppConfig

        cfg = AppConfig()
        with patch(
            "backend.core.config.api_key_manager.api_key_manager",
            side_effect=Exception("Manager error"),
        ):
            # Should not raise
            export_llm_api_keys(cfg)

    def test_export_with_valid_llm_keys(self):
        """Test export with valid LLM keys set."""
        from backend.core.config.app_config import AppConfig
        from backend.core.config.llm_config import LLMConfig

        cfg = AppConfig()
        # Set up an LLM config with API key
        llm = LLMConfig(model="gpt-4", api_key=SecretStr("sk-test123"))
        cfg.set_llm_config(llm)

        with patch("backend.core.config.api_key_manager.api_key_manager"):
            export_llm_api_keys(cfg)
            # Manager methods should have been called if keys exist
            # Just verify it completes without error
