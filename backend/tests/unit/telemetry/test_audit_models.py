"""Unit tests for backend.telemetry.models — AuditEntry pydantic model."""

from __future__ import annotations

from datetime import datetime

import pytest

from backend.ledger.action import ActionSecurityRisk
from backend.telemetry.models import AuditEntry

# ── helpers ──────────────────────────────────────────────────────────


def _make_entry(**overrides) -> AuditEntry:
    defaults = {
        'id': 'audit-1',
        'timestamp': datetime(2025, 1, 15, 10, 0, 0),
        'session_id': 'sess-1',
        'iteration': 5,
        'action_type': 'CmdRunAction',
        'action_content': 'echo hello',
        'risk_level': ActionSecurityRisk.LOW,
        'validation_result': 'allowed',
    }
    defaults.update(overrides)
    return AuditEntry(**defaults)


# ── Construction ─────────────────────────────────────────────────────


class TestAuditEntryConstruction:
    def test_minimal(self):
        e = _make_entry()
        assert e.id == 'audit-1'
        assert e.session_id == 'sess-1'
        assert e.iteration == 5
        assert e.risk_level == ActionSecurityRisk.LOW
        assert e.validation_result == 'allowed'

    def test_defaults(self):
        e = _make_entry()
        assert e.execution_result is None
        assert e.blocked_reason is None
        assert e.filesystem_snapshot_id is None
        assert e.rollback_available is False
        assert e.matched_risk_patterns == []
        assert e.environment == 'development'
        assert e.agent_state == 'unknown'

    def test_full_entry(self):
        e = _make_entry(
            execution_result='success',
            blocked_reason=None,
            filesystem_snapshot_id='snap-1',
            rollback_available=True,
            matched_risk_patterns=['sudo'],
            environment='production',
            agent_state='running',
        )
        assert e.rollback_available is True
        assert e.matched_risk_patterns == ['sudo']
        assert e.environment == 'production'
        assert e.agent_state == 'running'


# ── Validation ───────────────────────────────────────────────────────


class TestAuditEntryValidation:
    def test_empty_id_rejected(self):
        with pytest.raises(Exception):
            _make_entry(id='')

    def test_empty_session_id_rejected(self):
        with pytest.raises(Exception):
            _make_entry(session_id='')

    def test_empty_action_type_rejected(self):
        with pytest.raises(Exception):
            _make_entry(action_type='')

    def test_invalid_validation_result(self):
        with pytest.raises(ValueError):
            _make_entry(validation_result='invalid_status')

    def test_valid_validation_results(self):
        for vr in ('allowed', 'blocked', 'requires_review'):
            e = _make_entry(validation_result=vr)
            assert e.validation_result == vr

    def test_negative_iteration_rejected(self):
        with pytest.raises(Exception):
            _make_entry(iteration=-1)


# ── to_dict ──────────────────────────────────────────────────────────


class TestAuditEntryToDict:
    def test_basic_roundtrip_keys(self):
        e = _make_entry()
        d = e.to_dict()
        assert d['id'] == 'audit-1'
        assert d['session_id'] == 'sess-1'
        assert d['iteration'] == 5
        assert d['action_type'] == 'CmdRunAction'
        assert d['action_content'] == 'echo hello'
        assert d['risk_level'] == 'LOW'
        assert d['validation_result'] == 'allowed'

    def test_timestamp_serialized(self):
        e = _make_entry()
        d = e.to_dict()
        assert d['timestamp'] == '2025-01-15T10:00:00'

    def test_optional_fields_serialized(self):
        e = _make_entry(execution_result='ok', blocked_reason='danger')
        d = e.to_dict()
        assert d['execution_result'] == 'ok'
        assert d['blocked_reason'] == 'danger'


# ── from_dict ────────────────────────────────────────────────────────


class TestAuditEntryFromDict:
    def test_roundtrip(self):
        original = _make_entry(
            matched_risk_patterns=['rm -rf'],
            environment='staging',
            agent_state='running',
        )
        d = original.to_dict()
        restored = AuditEntry.from_dict(d)
        assert restored.id == original.id
        assert restored.session_id == original.session_id
        assert restored.risk_level == original.risk_level
        assert restored.validation_result == original.validation_result
        assert restored.matched_risk_patterns == original.matched_risk_patterns
        assert restored.environment == original.environment
        assert restored.agent_state == original.agent_state

    def test_from_dict_with_string_timestamp(self):
        d = {
            'id': 'a2',
            'timestamp': '2025-06-01T12:00:00',
            'session_id': 's2',
            'iteration': 0,
            'action_type': 'FileEditAction',
            'action_content': 'Edit file.py',
            'risk_level': 'LOW',
            'validation_result': 'allowed',
        }
        e = AuditEntry.from_dict(d)
        assert isinstance(e.timestamp, datetime)
        assert e.risk_level == ActionSecurityRisk.LOW

    def test_from_dict_blocked(self):
        d = {
            'id': 'a3',
            'timestamp': '2025-06-01T12:00:00',
            'session_id': 's3',
            'iteration': 2,
            'action_type': 'CmdRunAction',
            'action_content': 'rm -rf /',
            'risk_level': 'HIGH',
            'validation_result': 'blocked',
            'blocked_reason': 'Critical risk',
        }
        e = AuditEntry.from_dict(d)
        assert e.validation_result == 'blocked'
        assert e.blocked_reason == 'Critical risk'
        assert e.risk_level == ActionSecurityRisk.HIGH
