"""Tests for backend.core.config.agent_config — AgentConfig model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.core.config.agent_config import AgentConfig
from backend.core.config.compactor_config import AutoCompactorConfig
from backend.core.constants import (
    DEFAULT_AGENT_NAME,
    DEFAULT_AGENT_STREAMING_CHECKPOINT_DISCARD_STALE_ON_RECOVERY,
    DEFAULT_AGENT_STREAMING_CHECKPOINT_MAX_AGE_SECONDS,
)


class TestAgentConfigDefaults:
    def test_default_name(self):
        cfg = AgentConfig()
        assert cfg.name == DEFAULT_AGENT_NAME

    def test_default_memory_enabled(self):
        cfg = AgentConfig()
        assert isinstance(cfg.memory_enabled, bool)

    def test_default_memory_max_threads(self):
        cfg = AgentConfig()
        assert cfg.memory_max_threads >= 1

    def test_default_enable_browsing(self):
        cfg = AgentConfig()
        assert isinstance(cfg.enable_browsing, bool)

    def test_default_compactor_config(self):
        cfg = AgentConfig()
        assert isinstance(cfg.compactor_config, AutoCompactorConfig)

    def test_default_lsp_query_enabled(self):
        cfg = AgentConfig()
        assert cfg.enable_lsp_query is False

    def test_default_swarming_enabled(self):
        cfg = AgentConfig()
        assert cfg.enable_swarming is False

    def test_default_autonomy_level(self):
        cfg = AgentConfig()
        assert cfg.autonomy_level in {"supervised", "balanced", "full"}

    def test_default_circuit_breaker(self):
        cfg = AgentConfig()
        assert cfg.enable_circuit_breaker is True

    def test_default_graceful_shutdown(self):
        cfg = AgentConfig()
        assert cfg.enable_graceful_shutdown is True

    def test_default_streaming_checkpoint_policy(self):
        cfg = AgentConfig()
        assert (
            cfg.streaming_checkpoint_max_age_seconds
            == DEFAULT_AGENT_STREAMING_CHECKPOINT_MAX_AGE_SECONDS
        )
        assert (
            cfg.streaming_checkpoint_discard_stale_on_recovery
            is DEFAULT_AGENT_STREAMING_CHECKPOINT_DISCARD_STALE_ON_RECOVERY
        )


class TestAgentConfigValidation:
    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            AgentConfig(name="")

    def test_empty_autonomy_rejected(self):
        with pytest.raises(ValidationError):
            AgentConfig(autonomy_level="")

    def test_invalid_autonomy_value_rejected(self):
        with pytest.raises(ValidationError, match="autonomy_level must be one of"):
            AgentConfig(autonomy_level="aggressive")

    def test_autonomy_value_normalized_to_lowercase(self):
        cfg = AgentConfig(autonomy_level=" FULL ")
        assert cfg.autonomy_level == "full"

    def test_memory_max_threads_min(self):
        with pytest.raises(ValidationError):
            AgentConfig(memory_max_threads=0)

    def test_min_iterations_must_be_positive(self):
        with pytest.raises(ValidationError):
            AgentConfig(min_iterations=0)

    def test_max_iterations_override_must_be_positive_when_set(self):
        with pytest.raises(ValidationError):
            AgentConfig(max_iterations_override=0)

    def test_max_iterations_override_cannot_be_below_min_iterations(self):
        with pytest.raises(
            ValidationError,
            match="max_iterations_override must be greater than or equal to min_iterations",
        ):
            AgentConfig(min_iterations=50, max_iterations_override=10)

    def test_streaming_checkpoint_max_age_must_be_positive(self):
        with pytest.raises(ValidationError):
            AgentConfig(streaming_checkpoint_max_age_seconds=0)

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            AgentConfig(**{"nonexistent_field": "value"})

    def test_legacy_enable_prompt_caching_input_dropped(self):
        cfg = AgentConfig.model_validate({"enable_prompt_caching": False})
        assert not hasattr(cfg, "enable_prompt_caching")

    def test_legacy_enable_prompt_caching_in_model_validate_dropped(self):
        cfg = AgentConfig.model_validate({"enable_prompt_caching": True})
        assert not hasattr(cfg, "enable_prompt_caching")

    def test_legacy_system_prompt_filename_input_dropped(self):
        cfg = AgentConfig.model_validate({"system_prompt_filename": "custom.j2"})
        assert not hasattr(cfg, "system_prompt_filename")

    def test_legacy_condenser_config_kwarg_rejected(self):
        with pytest.raises(ValidationError):
            AgentConfig.model_validate({"condenser_config": {"type": "noop"}})


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

    def test_max_iterations_override_equal_to_min_iterations_allowed(self):
        cfg = AgentConfig(min_iterations=25, max_iterations_override=25)
        assert cfg.min_iterations == 25
        assert cfg.max_iterations_override == 25

    def test_disable_finish_warning_is_not_silent(self):
        from unittest.mock import patch

        with patch("backend.core.config.agent_config.logger.warning") as mock_warning:
            cfg = AgentConfig(enable_finish=False)

        assert cfg.enable_finish is False
        mock_warning.assert_called_once()
        warning_message = mock_warning.call_args.args[0]
        assert "enable_finish=False" in warning_message
        assert "normal task-completion signal" in warning_message

    def test_non_full_autonomy_warns_on_full_autonomy_only_knobs(self):
        from unittest.mock import patch

        with patch("backend.core.config.agent_config.logger.warning") as mock_warning:
            cfg = AgentConfig(
                autonomy_level="balanced",
                max_autonomous_iterations=10,
                stuck_threshold_iterations=5,
            )

        assert cfg.autonomy_level == "balanced"
        messages = [call.args[0] for call in mock_warning.call_args_list]
        assert any("max_autonomous_iterations=%s" in msg for msg in messages)
        assert any("stuck_threshold_iterations=%s" in msg for msg in messages)

    def test_dynamic_iteration_specific_knobs_warn_when_feature_disabled(self):
        from unittest.mock import patch

        with patch("backend.core.config.agent_config.logger.warning") as mock_warning:
            cfg = AgentConfig(
                enable_dynamic_iterations=False,
                min_iterations=60,
                max_iterations_override=80,
                complexity_iteration_multiplier=75.0,
            )

        assert cfg.enable_dynamic_iterations is False
        messages = [call.args[0] for call in mock_warning.call_args_list]
        assert any("max_iterations_override=%s" in msg for msg in messages)
        assert any("min_iterations=%s" in msg for msg in messages)
        assert any("complexity_iteration_multiplier=%s" in msg for msg in messages)

    def test_disabling_stale_checkpoint_auto_discard_warns(self):
        from unittest.mock import patch

        with patch("backend.core.config.agent_config.logger.warning") as mock_warning:
            cfg = AgentConfig(streaming_checkpoint_discard_stale_on_recovery=False)

        assert cfg.streaming_checkpoint_discard_stale_on_recovery is False
        messages = [call.args[0] for call in mock_warning.call_args_list]
        assert any(
            "streaming_checkpoint_discard_stale_on_recovery=False" in msg
            for msg in messages
        )


class TestGetLlmConfig:
    def test_returns_none_when_not_set(self):
        cfg = AgentConfig()
        assert cfg.get_llm_config() is None

    def test_returns_config_when_set(self):
        from backend.core.config.llm_config import LLMConfig

        llm = LLMConfig()
        cfg = AgentConfig(llm_config=llm)
        assert cfg.get_llm_config() is llm


class TestSeparateBaseAndCustomSections:
    def test_simple(self):
        data = {
            "name": "test",
            "enable_browsing": True,
            "Navigator": {"name": "nav", "enable_browsing": False},
        }
        base, custom = AgentConfig._separate_base_and_custom_sections(data)
        assert base["name"] == "test"
        assert base["enable_browsing"] is True
        assert "Navigator" in custom
        assert custom["Navigator"]["enable_browsing"] is False

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
        assert cfg.name == DEFAULT_AGENT_NAME

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
        assert cfg.name == DEFAULT_AGENT_NAME
        assert cfg.memory_max_threads >= 1


class TestCreateCustomConfig:
    def test_override_fields(self):
        base = AgentConfig()
        custom = AgentConfig._create_custom_config(
            "MyAgent", base, {"enable_browsing": True}
        )
        assert custom.name == "MyAgent"
        assert custom.enable_browsing is True

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
        data = {"name": "default_agent", "enable_browsing": True}
        mapping = AgentConfig.from_toml_section(data)
        assert "agent" in mapping
        assert mapping["agent"].enable_browsing is True

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
            "BadAgent2": {"enable_browsing": False},
        }

        # Mock to raise for both custom agents
        with patch.object(
            AgentConfig, "_create_custom_config", side_effect=ValueError("Config error")
        ):
            with pytest.raises(ValueError, match="Invalid custom agent configuration"):
                AgentConfig.from_toml_section(data)
