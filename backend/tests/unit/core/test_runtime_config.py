"""Tests for backend.core.config.runtime_config — RuntimeConfig model."""

from __future__ import annotations

import pytest

from backend.core.config.runtime_config import RuntimeConfig
from backend.core.constants import (
    DEFAULT_RUNTIME_AUTO_LINT_ENABLED,
    DEFAULT_RUNTIME_CLOSE_DELAY,
    DEFAULT_RUNTIME_KEEP_ALIVE,
    DEFAULT_RUNTIME_TIMEOUT,
)


class TestRuntimeConfigDefaults:
    def test_defaults(self):
        cfg = RuntimeConfig()
        assert cfg.timeout == DEFAULT_RUNTIME_TIMEOUT
        assert cfg.enable_auto_lint is DEFAULT_RUNTIME_AUTO_LINT_ENABLED
        assert cfg.runtime_startup_env_vars == {}
        assert cfg.selected_repo is None
        assert cfg.close_delay == DEFAULT_RUNTIME_CLOSE_DELAY
        assert cfg.keep_runtime_alive is DEFAULT_RUNTIME_KEEP_ALIVE


class TestRuntimeConfigValidation:
    def test_timeout_ge_1(self):
        with pytest.raises(Exception):
            RuntimeConfig(timeout=0)

    def test_timeout_valid(self):
        cfg = RuntimeConfig(timeout=1)
        assert cfg.timeout == 1

    def test_extra_field_rejected(self):
        with pytest.raises(Exception):
            RuntimeConfig(nonexistent="x")

    def test_custom_values(self):
        cfg = RuntimeConfig(
            timeout=300,
            enable_auto_lint=False,
            runtime_startup_env_vars={"FOO": "BAR"},
            selected_repo="owner/repo",
            close_delay=30,
            keep_runtime_alive=True,
        )
        assert cfg.timeout == 300
        assert cfg.enable_auto_lint is False
        assert cfg.runtime_startup_env_vars == {"FOO": "BAR"}
        assert cfg.selected_repo == "owner/repo"
        assert cfg.close_delay == 30
        assert cfg.keep_runtime_alive is True


class TestRuntimeConfigFromToml:
    def test_basic(self):
        mapping = RuntimeConfig.from_toml_section({"timeout": 60})
        assert "runtime_config" in mapping
        cfg = mapping["runtime_config"]
        assert cfg.timeout == 60

    def test_empty_dict(self):
        mapping = RuntimeConfig.from_toml_section({})
        cfg = mapping["runtime_config"]
        assert cfg.timeout == DEFAULT_RUNTIME_TIMEOUT

    def test_invalid_data_raises(self):
        with pytest.raises(ValueError, match="Invalid runtime configuration"):
            RuntimeConfig.from_toml_section({"unknown_key": True})
