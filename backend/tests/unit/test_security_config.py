"""Tests for backend.core.config.security_config — SecurityConfig model."""

from __future__ import annotations

import pytest

from backend.core.config.security_config import SecurityConfig


class TestSecurityConfigDefaults:
    def test_defaults(self):
        cfg = SecurityConfig()
        assert cfg.confirmation_mode is False
        assert cfg.security_analyzer is None
        assert cfg.enforce_security is True
        assert cfg.block_high_risk is False
        assert cfg.validation_mode == "permissive"


class TestSecurityConfigValidation:
    def test_extra_field_rejected(self):
        with pytest.raises(Exception):
            SecurityConfig(unknown_field="x")

    def test_invalid_validation_mode(self):
        with pytest.raises(Exception):
            SecurityConfig(validation_mode="invalid")

    def test_valid_strict_mode(self):
        cfg = SecurityConfig(validation_mode="strict")
        assert cfg.validation_mode == "strict"

    def test_custom_values(self):
        cfg = SecurityConfig(
            confirmation_mode=True,
            security_analyzer="custom_analyzer",
            enforce_security=False,
            block_high_risk=True,
            validation_mode="strict",
        )
        assert cfg.confirmation_mode is True
        assert cfg.security_analyzer == "custom_analyzer"
        assert cfg.enforce_security is False
        assert cfg.block_high_risk is True


class TestSecurityConfigFromToml:
    def test_basic(self):
        data = {"confirmation_mode": True, "enforce_security": False}
        mapping = SecurityConfig.from_toml_section(data)
        assert "security" in mapping
        cfg = mapping["security"]
        assert cfg.confirmation_mode is True
        assert cfg.enforce_security is False

    def test_empty_dict(self):
        mapping = SecurityConfig.from_toml_section({})
        cfg = mapping["security"]
        # All defaults
        assert cfg.confirmation_mode is False

    def test_invalid_data_raises(self):
        with pytest.raises(ValueError, match="Invalid security configuration"):
            SecurityConfig.from_toml_section({"unknown_field": "bad"})
