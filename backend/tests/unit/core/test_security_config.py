"""Tests for backend.core.config.security_config — SecurityConfig model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.core.config.security_config import SecurityConfig


def _assert_security_attrs(cfg: SecurityConfig, expected: dict[str, object]) -> None:
    for attr, value in expected.items():
        assert getattr(cfg, attr) == value


class TestSecurityConfigDefaults:
    def test_defaults(self):
        cfg = SecurityConfig()
        _assert_security_attrs(
            cfg,
            {
                'confirmation_mode': False,
                'security_analyzer': None,
                'enforce_security': True,
                'block_high_risk': False,
                'validation_mode': 'permissive',
                'execution_profile': 'standard',
                'allow_network_commands': False,
                'allow_package_installs': False,
                'allow_background_processes': False,
                'allow_sensitive_path_access': False,
                'hardened_local_package_allowlist': [],
                'hardened_local_network_allowlist': [],
            },
        )
        assert 'diff' in cfg.hardened_local_git_allowlist


class TestSecurityConfigValidation:
    def test_extra_field_ignored(self):
        cfg = SecurityConfig(unknown_field='x')
        assert isinstance(cfg, SecurityConfig)
        assert not hasattr(cfg, 'unknown_field')

    def test_invalid_validation_mode(self):
        with pytest.raises(ValidationError):
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
        _assert_security_attrs(
            cfg,
            {
                'confirmation_mode': True,
                'security_analyzer': 'custom_analyzer',
                'enforce_security': False,
                'block_high_risk': True,
                'validation_mode': 'strict',
                'execution_profile': 'sandboxed_local',
                'allow_network_commands': True,
                'allow_package_installs': True,
                'allow_background_processes': True,
                'allow_sensitive_path_access': True,
                'hardened_local_git_allowlist': ['status', 'diff'],
                'hardened_local_package_allowlist': ['npm_install'],
                'hardened_local_network_allowlist': ['curl'],
            },
        )


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
