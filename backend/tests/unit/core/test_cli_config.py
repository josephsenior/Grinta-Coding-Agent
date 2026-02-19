"""Tests for backend.core.config.cli_config — CLI configuration helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.core.config.cli_config import (
    _load_toml_config,
    apply_additional_overrides,
    apply_llm_config_override,
    get_llm_config_arg,
)
from backend.core.config.forge_config import ForgeConfig
from backend.core.config.llm_config import LLMConfig


# ── _load_toml_config ────────────────────────────────────────────────


class TestLoadTomlConfig:
    def test_file_not_found(self, tmp_path):
        result = _load_toml_config(str(tmp_path / "nonexistent.toml"))
        assert result is None

    def test_invalid_toml(self, tmp_path):
        bad_file = tmp_path / "bad.toml"
        bad_file.write_text("{{invalid toml")
        result = _load_toml_config(str(bad_file))
        assert result is None

    def test_valid_toml(self, tmp_path):
        good_file = tmp_path / "good.toml"
        good_file.write_text('[section]\nkey = "value"\n')
        result = _load_toml_config(str(good_file))
        assert result is not None
        assert result["section"]["key"] == "value"


# ── get_llm_config_arg ──────────────────────────────────────────────


class TestGetLlmConfigArg:
    def test_found_config(self, tmp_path):
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text('[llm.custom]\nmodel = "gpt-4"\n')
        result = get_llm_config_arg("custom", str(cfg_file))
        assert result is not None
        assert result.model == "gpt-4"

    def test_not_found(self, tmp_path):
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text('[llm.other]\nmodel = "gpt-3"\n')
        result = get_llm_config_arg("missing", str(cfg_file))
        assert result is None

    def test_no_llm_section(self, tmp_path):
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text('[agent]\nname = "test"\n')
        result = get_llm_config_arg("custom", str(cfg_file))
        assert result is None

    def test_strips_bracket_prefix(self, tmp_path):
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text('[llm.mymodel]\nmodel = "claude"\n')
        result = get_llm_config_arg("[llm.mymodel]", str(cfg_file))
        assert result is not None
        assert result.model == "claude"

    def test_missing_file(self):
        result = get_llm_config_arg("any", "nonexistent_file.toml")
        assert result is None


# ── apply_additional_overrides ───────────────────────────────────────


class TestApplyAdditionalOverrides:
    def test_agent_cls_override(self):
        config = ForgeConfig()
        args = SimpleNamespace(
            agent_cls="CustomAgent", max_iterations=None, max_budget_per_task=None
        )
        apply_additional_overrides(config, args)
        assert config.default_agent == "CustomAgent"

    def test_max_iterations_override(self):
        config = ForgeConfig()
        args = SimpleNamespace(
            agent_cls=None, max_iterations=50, max_budget_per_task=None
        )
        apply_additional_overrides(config, args)
        assert config.max_iterations == 50

    def test_max_budget_override(self):
        config = ForgeConfig()
        args = SimpleNamespace(
            agent_cls=None, max_iterations=None, max_budget_per_task=10.0
        )
        apply_additional_overrides(config, args)
        assert config.max_budget_per_task == 10.0

    def test_no_overrides(self):
        config = ForgeConfig()
        original_agent = config.default_agent
        original_iter = config.max_iterations
        args = SimpleNamespace()
        apply_additional_overrides(config, args)
        assert config.default_agent == original_agent
        assert config.max_iterations == original_iter

    def test_none_values_not_applied(self):
        config = ForgeConfig()
        original_iter = config.max_iterations
        args = SimpleNamespace(
            agent_cls=None, max_iterations=None, max_budget_per_task=None
        )
        apply_additional_overrides(config, args)
        assert config.max_iterations == original_iter


# ── apply_llm_config_override ───────────────────────────────────────


class TestApplyLlmConfigOverride:
    def test_no_config_no_change(self):
        config = ForgeConfig()
        args = SimpleNamespace(llm_config=None, config_file="config.toml")
        apply_llm_config_override(config, args)
        # No changes should occur

    def test_config_from_loaded(self):
        config = ForgeConfig()
        llm = LLMConfig(model="gpt-4")
        config.llms["custom"] = llm
        args = SimpleNamespace(llm_config="custom", config_file="config.toml")
        apply_llm_config_override(config, args)
        assert config.get_llm_config().model == "gpt-4"

    def test_missing_config_raises(self):
        config = ForgeConfig()
        args = SimpleNamespace(llm_config="nonexistent", config_file="nonexistent.toml")
        with pytest.raises(ValueError, match="Cannot find"):
            apply_llm_config_override(config, args)

    def test_config_from_user_fallback(self, tmp_path):
        """Test fallback to user config when not found in main config."""
        # Create main config without the LLM config
        main_config = tmp_path / "main.toml"
        main_config.write_text('[llm.other]\nmodel = "gpt-3"\n')

        # Create user config with the desired LLM config
        user_config_dir = tmp_path / ".Forge"
        user_config_dir.mkdir()
        user_config = user_config_dir / "config.toml"
        user_config.write_text('[llm.custom]\nmodel = "gpt-4-user"\n')

        # Mock the user config path
        with patch("os.path.expanduser", return_value=str(tmp_path)):
            config = ForgeConfig()
            args = SimpleNamespace(llm_config="custom", config_file=str(main_config))
            apply_llm_config_override(config, args)
            assert config.get_llm_config().model == "gpt-4-user"
