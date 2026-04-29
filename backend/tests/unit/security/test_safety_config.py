"""Unit tests for backend.security.safety_config — Pydantic safety model."""

from __future__ import annotations

from backend.security.safety_config import SafetyConfig


def _assert_safety_attrs(cfg: SafetyConfig, expected: dict[str, object]) -> None:
    for attr, value in expected.items():
        assert getattr(cfg, attr) == value

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_default_construction(self):
        cfg = SafetyConfig()
        _assert_safety_attrs(
            cfg,
            {
                'blocked_patterns': [],
                'allowed_exceptions': [],
                'risk_threshold': 'HIGH',
                'enable_audit_logging': False,
                'audit_log_path': 'audit.log',
                'environment': 'production',
                'enable_mandatory_validation': True,
                'block_in_production': True,
                'require_review_for_high_risk': False,
                'enable_risk_alerts': False,
                'alert_webhook_url': None,
            },
        )


# ---------------------------------------------------------------------------
# Custom values
# ---------------------------------------------------------------------------


class TestCustomValues:
    def test_custom_patterns(self):
        cfg = SafetyConfig(
            blocked_patterns=['rm -rf', 'DROP TABLE'],
            allowed_exceptions=['rm -rf /tmp/cache'],
        )
        assert len(cfg.blocked_patterns) == 2
        assert 'rm -rf' in cfg.blocked_patterns

    def test_custom_environment(self):
        cfg = SafetyConfig(environment='staging')
        assert cfg.environment == 'staging'

    def test_custom_risk_threshold(self):
        cfg = SafetyConfig(risk_threshold='CRITICAL')
        assert cfg.risk_threshold == 'CRITICAL'

    def test_webhook_url(self):
        cfg = SafetyConfig(
            enable_risk_alerts=True,
            alert_webhook_url='https://hooks.slack.com/test',
        )
        assert cfg.alert_webhook_url == 'https://hooks.slack.com/test'


# ---------------------------------------------------------------------------
# Audit log path validation
# ---------------------------------------------------------------------------


class TestAuditLogPathValidation:
    def test_relative_path_allowed(self):
        cfg = SafetyConfig(audit_log_path='logs/audit.log')
        assert cfg.audit_log_path == 'logs/audit.log'

    def test_simple_filename_allowed(self):
        cfg = SafetyConfig(audit_log_path='audit.log')
        assert cfg.audit_log_path == 'audit.log'

    def test_empty_path(self):
        """Empty string should still be accepted (Pydantic default)."""
        cfg = SafetyConfig(audit_log_path='')
        assert cfg.audit_log_path == ''


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_dict_roundtrip(self):
        cfg = SafetyConfig(
            blocked_patterns=['rm -rf'],
            environment='staging',
            enable_audit_logging=True,
        )
        d = cfg.model_dump()
        cfg2 = SafetyConfig(**d)
        assert cfg2.blocked_patterns == ['rm -rf']
        assert cfg2.environment == 'staging'
        assert cfg2.enable_audit_logging is True

    def test_json_roundtrip(self):
        cfg = SafetyConfig(risk_threshold='MEDIUM')
        json_str = cfg.model_dump_json()
        cfg2 = SafetyConfig.model_validate_json(json_str)
        assert cfg2.risk_threshold == 'MEDIUM'


# ---------------------------------------------------------------------------
# Type coercion / validation
# ---------------------------------------------------------------------------


class TestTypeValidation:
    def test_bool_coercion(self):
        cfg = SafetyConfig(enable_audit_logging=1)  # type: ignore[arg-type]
        assert cfg.enable_audit_logging is True

    def test_list_type(self):
        cfg = SafetyConfig(blocked_patterns=['a', 'b'])
        assert isinstance(cfg.blocked_patterns, list)
