"""Unit tests for backend.security.safety_config — Pydantic safety model."""

from __future__ import annotations

from backend.security.safety_config import SafetyConfig

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_default_construction(self):
        cfg = SafetyConfig()
        assert cfg.blocked_patterns == []
        assert cfg.allowed_exceptions == []
        assert cfg.risk_threshold == 'HIGH'
        assert cfg.enable_audit_logging is False
        assert cfg.audit_log_path == 'audit.log'
        assert cfg.environment == 'production'
        assert cfg.enable_mandatory_validation is True
        assert cfg.block_in_production is True
        assert cfg.require_review_for_high_risk is False
        assert cfg.enable_risk_alerts is False
        assert cfg.alert_webhook_url is None


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
