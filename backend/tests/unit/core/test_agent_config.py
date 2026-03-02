"""Tests for backend.core.config.agent_config — AgentConfig model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.core.config.agent_config import AgentConfig
from backend.core.constants import FORGE_DEFAULT_AGENT


class TestAgentConfigDefaults:
    def test_default_name(self):
        cfg = AgentConfig()
        assert cfg.name == FORGE_DEFAULT_AGENT

    def test_default_memory_enabled(self):
        cfg = AgentConfig()
        assert isinstance(cfg.memory_enabled, bool)

    def test_default_memory_max_threads(self):
        cfg = AgentConfig()
        assert cfg.memory_max_threads >= 1

    def test_default_enable_browsing(self):
        cfg = AgentConfig()
        assert isinstance(cfg.enable_browsing, bool)

    def test_default_enable_cmd(self):
        cfg = AgentConfig()
        assert isinstance(cfg.enable_cmd, bool)

    def test_default_condenser_config(self):
        cfg = AgentConfig()
        assert cfg.condenser_config is not None

    def test_default_autonomy_level(self):
        cfg = AgentConfig()
        assert cfg.autonomy_level in {"supervised", "balanced", "full"}

    def test_default_circuit_breaker(self):
        cfg = AgentConfig()
        assert cfg.enable_circuit_breaker is True

    def test_default_graceful_shutdown(self):
        cfg = AgentConfig()
        assert cfg.enable_graceful_shutdown is True


class TestAgentConfigValidation:
    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            AgentConfig(name="")

    def test_empty_autonomy_rejected(self):
        with pytest.raises(ValidationError):
            AgentConfig(autonomy_level="")

    def test_empty_system_prompt_rejected(self):
        with pytest.raises(ValidationError):
            AgentConfig(system_prompt_filename="")

    def test_memory_max_threads_min(self):
        with pytest.raises(ValidationError):
            AgentConfig(memory_max_threads=0)

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            AgentConfig(**{"nonexistent_field": "value"})


class TestAgentConfigCustom:
    def test_custom_name(self):
        cfg = AgentConfig(name="Navigator")
        assert cfg.name == "Navigator"

    def test_custom_autonomy(self):
        cfg = AgentConfig(autonomy_level="full")
        assert cfg.autonomy_level == "full"

    def test_disabled_playbooks(self):
        cfg = AgentConfig(disabled_playbooks=["playbook1"])
        assert "playbook1" in cfg.disabled_playbooks

    def test_max_iterations_override(self):
        cfg = AgentConfig(max_iterations_override=50)
        assert cfg.max_iterations_override == 50

    def test_max_iterations_default_none(self):
        cfg = AgentConfig()
        assert cfg.max_iterations_override is None


class TestGetLlmConfig:
    def test_returns_none_when_not_set(self):
        cfg = AgentConfig()
        assert cfg.get_llm_config() is None

    def test_returns_config_when_set(self):
        from backend.core.config.llm_config import LLMConfig

        llm = LLMConfig()
        cfg = AgentConfig(llm_config=llm)
        assert cfg.get_llm_config() is llm


class TestResolvedSystemPromptFilename:
    def test_default(self):
        cfg = AgentConfig()
        assert cfg.resolved_system_prompt_filename.endswith(".j2")

    def test_custom(self):
        cfg = AgentConfig(system_prompt_filename="custom.j2")
        assert cfg.resolved_system_prompt_filename == "custom.j2"

    def test_none_filename_uses_default(self):
        """Test that None filename falls back to default."""
        cfg = AgentConfig()
        # Bypass validation by setting directly
        object.__setattr__(cfg, "system_prompt_filename", None)
        assert cfg.resolved_system_prompt_filename == "system_prompt.j2"

    def test_non_string_filename_uses_default(self):
        """Test that non-string filename falls back to default."""
        cfg = AgentConfig()
        # Bypass validation by setting directly
        object.__setattr__(cfg, "system_prompt_filename", 123)
        assert cfg.resolved_system_prompt_filename == "system_prompt.j2"


class TestSeparateBaseAndCustomSections:
    def test_simple(self):
        data = {
            "name": "test",
            "enable_cmd": True,
            "Navigator": {"name": "nav", "enable_cmd": False},
        }
        base, custom = AgentConfig._separate_base_and_custom_sections(data)
        assert base["name"] == "test"
        assert base["enable_cmd"] is True
        assert "Navigator" in custom
        assert custom["Navigator"]["enable_cmd"] is False

    def test_llm_config_not_custom(self):
        """llm_config dict should stay in base, not be treated as custom section."""
        data = {"llm_config": {"model": "gpt-4"}}
        base, custom = AgentConfig._separate_base_and_custom_sections(data)
        assert "llm_config" in base
        assert not custom


class TestCreateBaseConfig:
    def test_valid(self):
        cfg = AgentConfig._create_base_config({"name": "test_agent"})
        assert cfg.name == "test_agent"

    def test_unknown_fields_ignored(self):
        cfg = AgentConfig._create_base_config({"name": "agent", "bogus_field": 123})
        assert cfg.name == "agent"

    def test_empty_gives_defaults(self):
        cfg = AgentConfig._create_base_config({})
        assert cfg.name == FORGE_DEFAULT_AGENT

    def test_invalid_field_value_recovery(self):
        """Test that invalid field values trigger recovery logic."""
        # Pass invalid value for memory_max_threads (must be >= 1)
        cfg = AgentConfig._create_base_config(
            {
                "name": "test",
                "memory_max_threads": -5,  # Invalid: must be >= 1
            }
        )
        # Should fall back to default
        assert cfg.name == "test"
        assert cfg.memory_max_threads >= 1

    def test_multiple_invalid_fields_recovery(self):
        """Test recovery with multiple invalid field values."""
        cfg = AgentConfig._create_base_config(
            {
                "name": "",  # Invalid: non-empty string required
                "memory_max_threads": 0,  # Invalid: must be >= 1
            }
        )
        # Should use defaults for invalid fields
        assert cfg.name == FORGE_DEFAULT_AGENT
        assert cfg.memory_max_threads >= 1


class TestCreateCustomConfig:
    def test_override_fields(self):
        base = AgentConfig()
        custom = AgentConfig._create_custom_config(
            "MyAgent", base, {"enable_cmd": False}
        )
        assert custom.name == "MyAgent"
        assert custom.enable_cmd is False

    def test_unknown_overrides_ignored(self):
        base = AgentConfig()
        custom = AgentConfig._create_custom_config("MyAgent", base, {"unknown_key": 42})
        assert custom.name == "MyAgent"

    def test_invalid_override_values(self):
        """Test that invalid override values are skipped."""
        base = AgentConfig()
        custom = AgentConfig._create_custom_config(
            "MyAgent",
            base,
            {"memory_max_threads": -10},  # Invalid value
        )
        assert custom.name == "MyAgent"
        # Should use base value, not invalid override
        assert custom.memory_max_threads == base.memory_max_threads


class TestFromTomlSection:
    def test_simple_section(self):
        data = {"name": "default_agent", "enable_cmd": True}
        mapping = AgentConfig.from_toml_section(data)
        assert "agent" in mapping
        assert mapping["agent"].enable_cmd is True

    def test_with_custom_agent(self):
        data = {
            "name": "base",
            "CustomBot": {"enable_browsing": True},
        }
        mapping = AgentConfig.from_toml_section(data)
        assert "agent" in mapping
        assert "CustomBot" in mapping
        assert mapping["CustomBot"].name == "CustomBot"
        assert mapping["CustomBot"].enable_browsing is True

    def test_schema_version_accepted(self):
        data = {"schema_version": "1", "name": "v_agent"}
        mapping = AgentConfig.from_toml_section(data)
        assert mapping["agent"].name == "v_agent"

    def test_invalid_custom_agent_raises_error(self):
        """Test that invalid custom agent configurations raise ValueError."""
        from unittest.mock import patch

        data = {
            "name": "base",
            "BadAgent": {"enable_browsing": True},
        }

        # Mock _create_custom_config to raise an exception
        with patch.object(
            AgentConfig,
            "_create_custom_config",
            side_effect=ValidationError.from_exception_data("test", []),
        ):
            with pytest.raises(ValueError, match="Invalid custom agent configuration"):
                AgentConfig.from_toml_section(data)

    def test_multiple_invalid_custom_agents_combined_error(self):
        """Test that multiple invalid custom agents create combined error message."""
        from unittest.mock import patch

        data = {
            "name": "base",
            "BadAgent1": {"enable_browsing": True},
            "BadAgent2": {"enable_cmd": False},
        }

        # Mock to raise for both custom agents
        with patch.object(
            AgentConfig, "_create_custom_config", side_effect=ValueError("Config error")
        ):
            with pytest.raises(ValueError, match="Invalid custom agent configuration"):
                AgentConfig.from_toml_section(data)
