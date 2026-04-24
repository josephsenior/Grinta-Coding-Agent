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
        assert cfg.validation_mode == 'permissive'
        assert cfg.execution_profile == 'standard'
        assert cfg.allow_network_commands is False
        assert cfg.allow_package_installs is False
        assert cfg.allow_background_processes is False
        assert cfg.allow_sensitive_path_access is False
        assert 'diff' in cfg.hardened_local_git_allowlist
        assert cfg.hardened_local_package_allowlist == []
        assert cfg.hardened_local_network_allowlist == []


class TestSecurityConfigValidation:
    def test_extra_field_ignored(self):
        cfg = SecurityConfig(unknown_field='x')
        assert isinstance(cfg, SecurityConfig)
        assert not hasattr(cfg, 'unknown_field')

    def test_invalid_validation_mode(self):
        with pytest.raises(Exception):
            SecurityConfig(validation_mode='invalid')

    def test_valid_strict_mode(self):
        cfg = SecurityConfig(validation_mode='strict')
        assert cfg.validation_mode == 'strict'

    def test_valid_sandboxed_local_profile(self):
        cfg = SecurityConfig(execution_profile='sandboxed_local')
        assert cfg.execution_profile == 'sandboxed_local'

    def test_custom_values(self):
        cfg = SecurityConfig(
            confirmation_mode=True,
            security_analyzer='custom_analyzer',
            enforce_security=False,
            block_high_risk=True,
            validation_mode='strict',
            execution_profile='sandboxed_local',
            allow_network_commands=True,
            allow_package_installs=True,
            allow_background_processes=True,
            allow_sensitive_path_access=True,
            hardened_local_git_allowlist=['status', 'diff'],
            hardened_local_package_allowlist=['npm_install'],
            hardened_local_network_allowlist=['curl'],
        )
        assert cfg.confirmation_mode is True
        assert cfg.security_analyzer == 'custom_analyzer'
        assert cfg.enforce_security is False
        assert cfg.block_high_risk is True
        assert cfg.execution_profile == 'sandboxed_local'
        assert cfg.allow_network_commands is True
        assert cfg.allow_package_installs is True
        assert cfg.allow_background_processes is True
        assert cfg.allow_sensitive_path_access is True
        assert cfg.hardened_local_git_allowlist == ['status', 'diff']
        assert cfg.hardened_local_package_allowlist == ['npm_install']
        assert cfg.hardened_local_network_allowlist == ['curl']


class TestSecurityConfigFromToml:
    def test_basic(self):
        data = {'confirmation_mode': True, 'enforce_security': False}
        mapping = SecurityConfig.from_toml_section(data)
        assert 'security' in mapping
        cfg = mapping['security']
        assert cfg.confirmation_mode is True
        assert cfg.enforce_security is False

    def test_empty_dict(self):
        mapping = SecurityConfig.from_toml_section({})
        cfg = mapping['security']
        # All defaults
        assert cfg.confirmation_mode is False

    def test_invalid_data_uses_defaults(self):
        mapping = SecurityConfig.from_toml_section({'unknown_field': 'bad'})
        cfg = mapping['security']
        assert cfg.confirmation_mode is False

    def test_invalid_validation_mode_raises_value_error(self):
        with pytest.raises(ValueError, match='Invalid security configuration'):
            SecurityConfig.from_toml_section({'validation_mode': 'nope'})
