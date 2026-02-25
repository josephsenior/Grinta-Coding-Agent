"""Tests for backend.core.config.config_sections."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr, ValidationError

from backend.core.config.config_sections import (
    check_unknown_sections,
    process_agent_section,
    process_condenser_section,
    process_core_section,
    process_extended_section,
    process_llm_section,
    process_mcp_section,
    process_runtime_section,
    process_security_section,
)
from backend.core.config.forge_config import ForgeConfig


class TestCheckUnknownSections:
    def test_known_sections_no_warning(self):
        """All known sections should not trigger any warnings."""
        toml = {
            "core": {},
            "agent": {},
            "llm": {},
            "security": {},
            "runtime": {},
            "condenser": {},
            "mcp": {},
            "extended": {},
        }
        # Should not raise
        check_unknown_sections(toml, "config.toml")

    def test_unknown_section_logged(self):
        """Unknown sections do not raise but get logged."""
        toml = {"core": {}, "custom_plugin": {}}
        # check_unknown_sections uses logger.debug — just ensure no exception
        check_unknown_sections(toml, "config.toml")

    def test_empty_config(self):
        check_unknown_sections({}, "config.toml")

    def test_case_insensitive(self):
        """Known section names are matched case-insensitively."""
        toml = {"Core": {}, "LLM": {}, "SECURITY": {}}
        check_unknown_sections(toml, "config.toml")


class DummySummary:
    def __init__(self):
        self.records = []

    def record(self, section, reason, detail):
        self.records.append((section, reason, detail))


class DummyCfg:
    secret: SecretStr | None
    plain: int

    def __init__(self):
        self.secret = None
        self.plain = 0


class TestProcessCoreSection:
    def test_applies_secret_str(self):
        cfg = DummyCfg()
        summary = DummySummary()
        process_core_section({"secret": "value", "plain": 3}, cfg, summary)
        assert isinstance(cfg.secret, SecretStr)
        assert cfg.secret.get_secret_value() == "value"
        assert cfg.plain == 3

    def test_unknown_key_warning(self):
        """Test that unknown keys trigger warnings."""
        cfg = DummyCfg()
        summary = DummySummary()
        # Pass unknown key
        process_core_section({"unknown_field": "value"}, cfg, summary)
        # Should not raise, just log warning
        assert not hasattr(cfg, "unknown_field")

    def test_no_type_hints_fallback(self):
        """Test fallback when type hints aren't available."""

        class NoHintsCfg:
            def __init__(self):
                self.value = 0

        cfg = NoHintsCfg()
        summary = DummySummary()
        process_core_section({"value": 42}, cfg, summary)
        assert cfg.value == 42


class TestProcessAgentSection:
    def test_invalid_agent_section_records_summary(self):
        cfg = MagicMock()
        summary = DummySummary()
        with patch(
            "backend.core.config.config_sections.AgentConfig.from_toml_section",
            side_effect=ValidationError.from_exception_data("AgentConfig", []),
        ):
            process_agent_section({"agent": {"bad": True}}, cfg, summary)
        assert summary.records

    def test_valid_agent_section(self):
        """Test that valid agent section sets configs."""
        cfg = MagicMock()
        summary = DummySummary()
        fake_agent = MagicMock()
        with patch(
            "backend.core.config.config_sections.AgentConfig.from_toml_section",
            return_value={"agent": fake_agent},
        ):
            process_agent_section({"agent": {"name": "test"}}, cfg, summary)
        cfg.set_agent_config.assert_called_once_with(fake_agent, "agent")

    def test_no_agent_section_does_nothing(self):
        """Test that missing agent section doesn't cause errors."""
        cfg = MagicMock()
        summary = DummySummary()
        process_agent_section({}, cfg, summary)
        cfg.set_agent_config.assert_not_called()

    def test_type_error_records_summary(self):
        """Test TypeError handling."""
        cfg = MagicMock()
        summary = DummySummary()
        with patch(
            "backend.core.config.config_sections.AgentConfig.from_toml_section",
            side_effect=TypeError("bad type"),
        ):
            process_agent_section({"agent": {"bad": True}}, cfg, summary)
        assert summary.records

    def test_key_error_records_summary(self):
        """Test KeyError handling."""
        cfg = MagicMock()
        summary = DummySummary()
        with patch(
            "backend.core.config.config_sections.AgentConfig.from_toml_section",
            side_effect=KeyError("missing_key"),
        ):
            process_agent_section({"agent": {"bad": True}}, cfg, summary)
        assert summary.records


class TestProcessLLMSection:
    def test_sets_base_and_custom_llm_configs(self):
        cfg = MagicMock()
        summary = DummySummary()

        @contextmanager
        def _no_env():
            yield

        fake_llm = MagicMock()
        fake_custom = MagicMock()
        with patch(
            "backend.core.config.llm_config.suppress_llm_env_export",
            _no_env,
        ):
            with patch.object(
                MagicMock(),
                "from_toml_section",
                return_value={"llm": fake_llm, "custom": fake_custom},
            ):
                with patch(
                    "backend.core.config.config_sections.LLMConfig"
                ) as mock_llm_class:
                    mock_instance = MagicMock()
                    mock_instance.from_toml_section.return_value = {
                        "llm": fake_llm,
                        "custom": fake_custom,
                    }
                    mock_llm_class.return_value = mock_instance
                    process_llm_section({"llm": {"model": "x"}}, cfg, summary)

        cfg.set_llm_config.assert_any_call(fake_custom, "custom")
        cfg.set_llm_config.assert_any_call(fake_llm, "llm")

    def test_llm_validation_error_records_summary(self):
        """Test that ValidationError in LLM section is caught and recorded."""
        cfg = MagicMock()
        summary = DummySummary()
        with patch(
            "backend.core.config.llm_config.suppress_llm_env_export",
            contextmanager(lambda: (yield))(),
        ):
            with patch(
                "backend.core.config.config_sections.LLMConfig"
            ) as mock_llm_class:
                mock_instance = MagicMock()
                mock_instance.from_toml_section.side_effect = (
                    ValidationError.from_exception_data("LLMConfig", [])
                )
                mock_llm_class.return_value = mock_instance
                process_llm_section({"llm": {"bad": True}}, cfg, summary)
        assert summary.records
        assert summary.records[0][0] == "llm"

    def test_llm_no_section_does_nothing(self):
        """Test that missing LLM section doesn't cause errors."""
        cfg = MagicMock()
        summary = DummySummary()
        process_llm_section({}, cfg, summary)
        # No calls should have been made
        cfg.set_llm_config.assert_not_called()


class TestProcessSecuritySection:
    def test_value_error_is_recorded_as_warning(self):
        cfg = MagicMock()
        summary = DummySummary()
        with patch(
            "backend.core.config.config_sections.SecurityConfig.from_toml_section",
            side_effect=ValueError("bad"),
        ):
            process_security_section({"security": {"bad": True}}, cfg, summary)
        assert summary.records
        assert summary.records[0][1] == "warning"

    def test_valid_security_section(self):
        """Test valid security section sets config."""
        cfg = MagicMock()
        summary = DummySummary()
        fake_security = MagicMock()
        with patch(
            "backend.core.config.config_sections.SecurityConfig.from_toml_section",
            return_value={"security": fake_security},
        ):
            process_security_section({"security": {"enabled": True}}, cfg, summary)
        assert cfg.security == fake_security

    def test_no_security_section_does_nothing(self):
        """Test that missing security section doesn't cause errors."""
        cfg = MagicMock()
        summary = DummySummary()
        original_security = cfg.security
        process_security_section({}, cfg, summary)
        assert cfg.security == original_security

    def test_validation_error_records_summary(self):
        """Test ValidationError handling."""
        cfg = MagicMock()
        summary = DummySummary()
        with patch(
            "backend.core.config.config_sections.SecurityConfig.from_toml_section",
            side_effect=ValidationError.from_exception_data("SecurityConfig", []),
        ):
            process_security_section({"security": {"bad": True}}, cfg, summary)
        assert summary.records

    def test_type_error_records_summary(self):
        """Test TypeError handling."""
        cfg = MagicMock()
        summary = DummySummary()
        with patch(
            "backend.core.config.config_sections.SecurityConfig.from_toml_section",
            side_effect=TypeError("bad type"),
        ):
            process_security_section({"security": {"bad": True}}, cfg, summary)
        assert summary.records


class TestProcessRuntimeSection:
    def test_value_error_is_raised(self):
        cfg = MagicMock()
        summary = DummySummary()
        with patch(
            "backend.core.config.config_sections.RuntimeConfig.from_toml_section",
            side_effect=ValueError("bad"),
        ):
            with pytest.raises(ValueError):
                process_runtime_section({"runtime": {"bad": True}}, cfg, summary)
        assert summary.records

    def test_valid_runtime_section(self):
        """Test valid runtime section sets config."""
        cfg = MagicMock()
        summary = DummySummary()
        fake_runtime = MagicMock()
        with patch(
            "backend.core.config.config_sections.RuntimeConfig.from_toml_section",
            return_value={"runtime_config": fake_runtime},
        ):
            process_runtime_section({"runtime": {"enabled": True}}, cfg, summary)
        assert cfg.runtime_config == fake_runtime

    def test_no_runtime_section_does_nothing(self):
        """Test that missing runtime section doesn't cause errors."""
        cfg = MagicMock()
        summary = DummySummary()
        original_runtime = cfg.runtime_config
        process_runtime_section({}, cfg, summary)
        assert cfg.runtime_config == original_runtime

    def test_validation_error_records_summary(self):
        """Test ValidationError handling."""
        cfg = MagicMock()
        summary = DummySummary()
        with patch(
            "backend.core.config.config_sections.RuntimeConfig.from_toml_section",
            side_effect=ValidationError.from_exception_data("RuntimeConfig", []),
        ):
            process_runtime_section({"runtime": {"bad": True}}, cfg, summary)
        assert summary.records


class TestProcessMcpSection:
    def test_value_error_is_raised(self):
        cfg = MagicMock()
        summary = DummySummary()
        with patch(
            "backend.core.config.config_sections.MCPConfig.from_toml_section",
            side_effect=ValueError("bad"),
        ):
            with pytest.raises(ValueError):
                process_mcp_section({"mcp": {"bad": True}}, cfg, summary)
        assert summary.records

    def test_valid_mcp_section(self):
        """Test valid MCP section sets config."""
        cfg = MagicMock()
        summary = DummySummary()
        fake_mcp = MagicMock()
        with patch(
            "backend.core.config.config_sections.MCPConfig.from_toml_section",
            return_value={"mcp": fake_mcp},
        ):
            process_mcp_section({"mcp": {"enabled": True}}, cfg, summary)
        assert cfg.mcp == fake_mcp

    def test_no_mcp_section_does_nothing(self):
        """Test that missing MCP section doesn't cause errors."""
        cfg = MagicMock()
        summary = DummySummary()
        original_mcp = cfg.mcp
        process_mcp_section({}, cfg, summary)
        assert cfg.mcp == original_mcp

    def test_validation_error_records_summary(self):
        """Test ValidationError handling."""
        cfg = MagicMock()
        summary = DummySummary()
        with patch(
            "backend.core.config.config_sections.MCPConfig.from_toml_section",
            side_effect=ValidationError.from_exception_data("MCPConfig", []),
        ):
            process_mcp_section({"mcp": {"bad": True}}, cfg, summary)
        assert summary.records


class TestProcessCondenserSection:
    def test_default_condenser_assigned_when_missing(self):
        cfg = ForgeConfig()
        cfg.enable_default_condenser = True
        summary = DummySummary()

        class DummyCondenser:
            def __init__(self, llm_config, type):
                self.llm_config = llm_config
                self.type = type

        with patch(
            "backend.core.config.condenser_config.LLMSummarizingCondenserConfig",
            DummyCondenser,
        ):
            process_condenser_section({}, cfg, summary)

        assert cfg.get_agent_config().condenser_config is not None

    def test_condenser_mapping_applied(self):
        cfg = ForgeConfig()
        summary = DummySummary()
        dummy_condenser = MagicMock()

        with patch(
            "backend.core.config.condenser_config.condenser_config_from_toml_section",
            return_value={"condenser": dummy_condenser},
        ):
            process_condenser_section({"condenser": {"type": "noop"}}, cfg, summary)

        assert cfg.get_agent_config().condenser_config is dummy_condenser

    def test_condenser_validation_error_records_summary(self):
        """Test ValidationError in condenser section."""
        cfg = ForgeConfig()
        summary = DummySummary()
        with patch(
            "backend.core.config.condenser_config.condenser_config_from_toml_section",
            side_effect=ValidationError.from_exception_data("CondenserConfig", []),
        ):
            process_condenser_section({"condenser": {"bad": True}}, cfg, summary)
        assert summary.records

    def test_condenser_no_default_when_disabled(self):
        """Test that no default condenser is assigned when disabled."""
        cfg = ForgeConfig()
        cfg.enable_default_condenser = False
        summary = DummySummary()
        # Don't create default condenser
        process_condenser_section({}, cfg, summary)
        # Original config should be unchanged (no condenser added)
        # This just tests the path doesn't crash


class TestProcessExtendedSection:
    def test_extended_validation_error_records_summary(self):
        cfg = MagicMock()
        summary = DummySummary()
        with patch(
            "backend.core.config.config_sections.ExtendedConfig",
            side_effect=ValidationError.from_exception_data("ExtendedConfig", []),
        ):
            process_extended_section({"extended": {"bad": True}}, cfg, summary)
        assert summary.records

    def test_valid_extended_section(self):
        """Test valid extended section sets config."""
        cfg = MagicMock()
        summary = DummySummary()
        fake_extended = MagicMock()
        with patch(
            "backend.core.config.config_sections.ExtendedConfig",
            return_value=fake_extended,
        ):
            process_extended_section({"extended": {"key": "value"}}, cfg, summary)
        assert cfg.extended == fake_extended

    def test_no_extended_section_does_nothing(self):
        """Test that missing extended section doesn't cause errors."""
        cfg = MagicMock()
        summary = DummySummary()
        original_extended = cfg.extended
        process_extended_section({}, cfg, summary)
        assert cfg.extended == original_extended

    def test_type_error_records_summary(self):
        """Test TypeError handling in extended section."""
        cfg = MagicMock()
        summary = DummySummary()
        with patch(
            "backend.core.config.config_sections.ExtendedConfig",
            side_effect=TypeError("bad type"),
        ):
            process_extended_section({"extended": {"bad": True}}, cfg, summary)
        assert summary.records
