"""Tests for backend.telemetry.models — audit logging data models."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from backend.ledger.action import ActionSecurityRisk
from backend.telemetry.models import AuditEntry


class TestAuditEntryCreation:
    """Tests for AuditEntry instantiation."""

    def test_create_minimal_entry(self):
        """Test creating audit entry with minimal required fields."""
        entry = AuditEntry(
            id="entry_123",
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            session_id="session_456",
            iteration=5,
            action_type="CmdRunAction",
            action_content="ls -la",
            risk_level=ActionSecurityRisk.LOW,
            validation_result="allowed",
        )
        assert entry.id == "entry_123"
        assert entry.session_id == "session_456"
        assert entry.iteration == 5
        assert entry.action_type == "CmdRunAction"
        assert entry.risk_level == ActionSecurityRisk.LOW

    def test_create_full_entry(self):
        """Test creating audit entry with all fields."""
        entry = AuditEntry(
            id="entry_123",
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            session_id="session_456",
            iteration=5,
            action_type="CmdRunAction",
            action_content="rm -rf /tmp/test",
            risk_level=ActionSecurityRisk.HIGH,
            validation_result="blocked",
            execution_result=None,
            blocked_reason="High risk command detected",
            filesystem_snapshot_id="snap_789",
            rollback_available=True,
            matched_risk_patterns=["rm.*-rf", "recursive.*delete"],
            environment="production",
            agent_state="running",
        )
        assert entry.blocked_reason == "High risk command detected"
        assert entry.filesystem_snapshot_id == "snap_789"
        assert entry.rollback_available is True
        assert len(entry.matched_risk_patterns) == 2

    def test_default_optional_fields(self):
        """Test optional fields have correct defaults."""
        entry = AuditEntry(
            id="entry_123",
            timestamp=datetime.now(),
            session_id="session_456",
            iteration=0,
            action_type="CmdRunAction",
            action_content="echo test",
            risk_level=ActionSecurityRisk.LOW,
            validation_result="allowed",
        )
        assert entry.execution_result is None
        assert entry.blocked_reason is None
        assert entry.filesystem_snapshot_id is None
        assert entry.rollback_available is False
        assert entry.matched_risk_patterns == []
        assert entry.environment == "development"
        assert entry.agent_state == "unknown"


class TestAuditEntryValidation:
    """Tests for AuditEntry field validation."""

    def test_empty_id_fails(self):
        """Test empty id fails validation."""
        with pytest.raises(ValidationError):
            AuditEntry(
                id="",
                timestamp=datetime.now(),
                session_id="session_456",
                iteration=0,
                action_type="CmdRunAction",
                action_content="test",
                risk_level=ActionSecurityRisk.LOW,
                validation_result="allowed",
            )

    def test_empty_session_id_fails(self):
        """Test empty session_id fails validation."""
        with pytest.raises(ValidationError):
            AuditEntry(
                id="entry_123",
                timestamp=datetime.now(),
                session_id="",
                iteration=0,
                action_type="CmdRunAction",
                action_content="test",
                risk_level=ActionSecurityRisk.LOW,
                validation_result="allowed",
            )

    def test_negative_iteration_fails(self):
        """Test negative iteration fails validation."""
        with pytest.raises(ValidationError):
            AuditEntry(
                id="entry_123",
                timestamp=datetime.now(),
                session_id="session_456",
                iteration=-1,
                action_type="CmdRunAction",
                action_content="test",
                risk_level=ActionSecurityRisk.LOW,
                validation_result="allowed",
            )

    def test_zero_iteration_allowed(self):
        """Test iteration=0 is valid."""
        entry = AuditEntry(
            id="entry_123",
            timestamp=datetime.now(),
            session_id="session_456",
            iteration=0,
            action_type="CmdRunAction",
            action_content="test",
            risk_level=ActionSecurityRisk.LOW,
            validation_result="allowed",
        )
        assert entry.iteration == 0

    def test_empty_action_type_fails(self):
        """Test empty action_type fails validation."""
        with pytest.raises(ValidationError):
            AuditEntry(
                id="entry_123",
                timestamp=datetime.now(),
                session_id="session_456",
                iteration=0,
                action_type="",
                action_content="test",
                risk_level=ActionSecurityRisk.LOW,
                validation_result="allowed",
            )

    def test_invalid_validation_result(self):
        """Test validation_result must be allowed/blocked/requires_review."""
        with pytest.raises(ValidationError, match="allowed, blocked, requires_review"):
            AuditEntry(
                id="entry_123",
                timestamp=datetime.now(),
                session_id="session_456",
                iteration=0,
                action_type="CmdRunAction",
                action_content="test",
                risk_level=ActionSecurityRisk.LOW,
                validation_result="invalid_status",
            )

    def test_valid_validation_results(self):
        """Test all valid validation_result values."""
        for result in ["allowed", "blocked", "requires_review"]:
            entry = AuditEntry(
                id=f"entry_{result}",
                timestamp=datetime.now(),
                session_id="session_456",
                iteration=0,
                action_type="CmdRunAction",
                action_content="test",
                risk_level=ActionSecurityRisk.LOW,
                validation_result=result,
            )
            assert entry.validation_result == result

    def test_empty_environment_fails(self):
        """Test empty environment fails validation."""
        with pytest.raises(ValidationError):
            AuditEntry(
                id="entry_123",
                timestamp=datetime.now(),
                session_id="session_456",
                iteration=0,
                action_type="CmdRunAction",
                action_content="test",
                risk_level=ActionSecurityRisk.LOW,
                validation_result="allowed",
                environment="",
            )

    def test_empty_agent_state_fails(self):
        """Test empty agent_state fails validation."""
        with pytest.raises(ValidationError):
            AuditEntry(
                id="entry_123",
                timestamp=datetime.now(),
                session_id="session_456",
                iteration=0,
                action_type="CmdRunAction",
                action_content="test",
                risk_level=ActionSecurityRisk.LOW,
                validation_result="allowed",
                agent_state="",
            )


class TestAuditEntryRiskLevels:
    """Tests for risk level handling."""

    def test_all_risk_levels(self):
        """Test all ActionSecurityRisk levels."""
        for risk in [
            ActionSecurityRisk.UNKNOWN,
            ActionSecurityRisk.LOW,
            ActionSecurityRisk.MEDIUM,
            ActionSecurityRisk.HIGH,
        ]:
            entry = AuditEntry(
                id=f"entry_{risk.name}",
                timestamp=datetime.now(),
                session_id="session_456",
                iteration=0,
                action_type="CmdRunAction",
                action_content="test",
                risk_level=risk,
                validation_result="allowed",
            )
            assert entry.risk_level == risk

    def test_risk_level_is_enum(self):
        """Test risk_level is ActionSecurityRisk enum."""
        entry = AuditEntry(
            id="entry_123",
            timestamp=datetime.now(),
            session_id="session_456",
            iteration=0,
            action_type="CmdRunAction",
            action_content="test",
            risk_level=ActionSecurityRisk.MEDIUM,
            validation_result="allowed",
        )
        assert isinstance(entry.risk_level, ActionSecurityRisk)


class TestAuditEntryToDict:
    """Tests for AuditEntry.to_dict() method."""

    def test_to_dict_basic(self):
        """Test to_dict returns dictionary with all fields."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        entry = AuditEntry(
            id="entry_123",
            timestamp=timestamp,
            session_id="session_456",
            iteration=5,
            action_type="CmdRunAction",
            action_content="ls -la",
            risk_level=ActionSecurityRisk.LOW,
            validation_result="allowed",
        )
        result = entry.to_dict()

        assert isinstance(result, dict)
        assert result["id"] == "entry_123"
        assert result["session_id"] == "session_456"
        assert result["iteration"] == 5
        assert result["action_type"] == "CmdRunAction"
        assert result["action_content"] == "ls -la"
        assert result["validation_result"] == "allowed"

    def test_to_dict_timestamp_isoformat(self):
        """Test timestamp is converted to ISO format string."""
        timestamp = datetime(2024, 1, 1, 12, 30, 45)
        entry = AuditEntry(
            id="entry_123",
            timestamp=timestamp,
            session_id="session_456",
            iteration=0,
            action_type="CmdRunAction",
            action_content="test",
            risk_level=ActionSecurityRisk.LOW,
            validation_result="allowed",
        )
        result = entry.to_dict()

        assert result["timestamp"] == "2024-01-01T12:30:45"

    def test_to_dict_risk_level_name(self):
        """Test risk_level is converted to name string."""
        entry = AuditEntry(
            id="entry_123",
            timestamp=datetime.now(),
            session_id="session_456",
            iteration=0,
            action_type="CmdRunAction",
            action_content="test",
            risk_level=ActionSecurityRisk.HIGH,
            validation_result="allowed",
        )
        result = entry.to_dict()

        assert result["risk_level"] == "HIGH"

    def test_to_dict_with_optional_fields(self):
        """Test to_dict includes optional fields when set."""
        entry = AuditEntry(
            id="entry_123",
            timestamp=datetime.now(),
            session_id="session_456",
            iteration=0,
            action_type="CmdRunAction",
            action_content="test",
            risk_level=ActionSecurityRisk.MEDIUM,
            validation_result="blocked",
            execution_result="Command was blocked",
            blocked_reason="High risk pattern matched",
            filesystem_snapshot_id="snap_123",
            rollback_available=True,
            matched_risk_patterns=["pattern1", "pattern2"],
        )
        result = entry.to_dict()

        assert result["execution_result"] == "Command was blocked"
        assert result["blocked_reason"] == "High risk pattern matched"
        assert result["filesystem_snapshot_id"] == "snap_123"
        assert result["rollback_available"] is True
        assert result["matched_risk_patterns"] == ["pattern1", "pattern2"]

    def test_to_dict_with_none_optional_fields(self):
        """Test to_dict includes None for unset optional fields."""
        entry = AuditEntry(
            id="entry_123",
            timestamp=datetime.now(),
            session_id="session_456",
            iteration=0,
            action_type="CmdRunAction",
            action_content="test",
            risk_level=ActionSecurityRisk.LOW,
            validation_result="allowed",
        )
        result = entry.to_dict()

        assert result["execution_result"] is None
        assert result["blocked_reason"] is None
        assert result["filesystem_snapshot_id"] is None


class TestAuditEntryFromDict:
    """Tests for AuditEntry.from_dict() class method."""

    def test_from_dict_basic(self):
        """Test creating AuditEntry from dictionary."""
        data = {
            "id": "entry_123",
            "timestamp": datetime(2024, 1, 1, 12, 0, 0),
            "session_id": "session_456",
            "iteration": 5,
            "action_type": "CmdRunAction",
            "action_content": "ls -la",
            "risk_level": ActionSecurityRisk.LOW,
            "validation_result": "allowed",
        }
        entry = AuditEntry.from_dict(data)

        assert entry.id == "entry_123"
        assert entry.session_id == "session_456"
        assert entry.iteration == 5

    def test_from_dict_with_timestamp_string(self):
        """Test from_dict converts timestamp string to datetime."""
        data = {
            "id": "entry_123",
            "timestamp": "2024-01-01T12:30:45",
            "session_id": "session_456",
            "iteration": 0,
            "action_type": "CmdRunAction",
            "action_content": "test",
            "risk_level": ActionSecurityRisk.LOW,
            "validation_result": "allowed",
        }
        entry = AuditEntry.from_dict(data)

        assert isinstance(entry.timestamp, datetime)
        assert entry.timestamp == datetime(2024, 1, 1, 12, 30, 45)

    def test_from_dict_with_risk_level_string(self):
        """Test from_dict converts risk_level string to enum."""
        data = {
            "id": "entry_123",
            "timestamp": datetime.now(),
            "session_id": "session_456",
            "iteration": 0,
            "action_type": "CmdRunAction",
            "action_content": "test",
            "risk_level": "MEDIUM",
            "validation_result": "allowed",
        }
        entry = AuditEntry.from_dict(data)

        assert entry.risk_level == ActionSecurityRisk.MEDIUM
        assert isinstance(entry.risk_level, ActionSecurityRisk)

    def test_from_dict_roundtrip(self):
        """Test to_dict -> from_dict roundtrip."""
        original = AuditEntry(
            id="entry_123",
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            session_id="session_456",
            iteration=5,
            action_type="CmdRunAction",
            action_content="ls -la",
            risk_level=ActionSecurityRisk.LOW,
            validation_result="allowed",
            execution_result="Success",
            matched_risk_patterns=["pattern1"],
        )

        dict_form = original.to_dict()
        restored = AuditEntry.from_dict(dict_form)

        assert restored.id == original.id
        assert restored.session_id == original.session_id
        assert restored.iteration == original.iteration
        assert restored.action_type == original.action_type
        assert restored.risk_level == original.risk_level
        assert restored.validation_result == original.validation_result
        assert restored.execution_result == original.execution_result
        assert restored.matched_risk_patterns == original.matched_risk_patterns

    def test_from_dict_with_all_fields(self):
        """Test from_dict with all fields populated."""
        data = {
            "id": "entry_123",
            "timestamp": "2024-01-01T12:00:00",
            "session_id": "session_456",
            "iteration": 5,
            "action_type": "CmdRunAction",
            "action_content": "rm -rf /tmp/test",
            "risk_level": "HIGH",
            "validation_result": "blocked",
            "execution_result": None,
            "blocked_reason": "High risk",
            "filesystem_snapshot_id": "snap_789",
            "rollback_available": True,
            "matched_risk_patterns": ["rm.*-rf"],
            "environment": "production",
            "agent_state": "running",
        }

        entry = AuditEntry.from_dict(data)

        assert entry.id == "entry_123"
        assert entry.risk_level == ActionSecurityRisk.HIGH
        assert entry.blocked_reason == "High risk"
        assert entry.rollback_available is True
        assert entry.environment == "production"


class TestAuditEntryImmutability:
    """Tests for AuditEntry immutability expectations."""

    def test_matched_risk_patterns_is_list(self):
        """Test matched_risk_patterns is a list."""
        entry = AuditEntry(
            id="entry_123",
            timestamp=datetime.now(),
            session_id="session_456",
            iteration=0,
            action_type="CmdRunAction",
            action_content="test",
            risk_level=ActionSecurityRisk.LOW,
            validation_result="allowed",
        )
        assert isinstance(entry.matched_risk_patterns, list)

    def test_matched_risk_patterns_can_be_populated(self):
        """Test matched_risk_patterns can be set during creation."""
        patterns = ["pattern1", "pattern2", "pattern3"]
        entry = AuditEntry(
            id="entry_123",
            timestamp=datetime.now(),
            session_id="session_456",
            iteration=0,
            action_type="CmdRunAction",
            action_content="test",
            risk_level=ActionSecurityRisk.LOW,
            validation_result="allowed",
            matched_risk_patterns=patterns,
        )
        assert entry.matched_risk_patterns == patterns


class TestAuditEntryActionContent:
    """Tests for action_content field."""

    def test_action_content_can_be_empty_string(self):
        """Test action_content can be empty string."""
        entry = AuditEntry(
            id="entry_123",
            timestamp=datetime.now(),
            session_id="session_456",
            iteration=0,
            action_type="CmdRunAction",
            action_content="",
            risk_level=ActionSecurityRisk.LOW,
            validation_result="allowed",
        )
        assert entry.action_content == ""

    def test_action_content_long_string(self):
        """Test action_content can handle long strings."""
        long_content = "cmd " * 1000
        entry = AuditEntry(
            id="entry_123",
            timestamp=datetime.now(),
            session_id="session_456",
            iteration=0,
            action_type="CmdRunAction",
            action_content=long_content,
            risk_level=ActionSecurityRisk.LOW,
            validation_result="allowed",
        )
        assert entry.action_content == long_content

    def test_action_content_special_characters(self):
        """Test action_content handles special characters."""
        special_content = "rm -rf /tmp/* && echo 'done' | tee log.txt"
        entry = AuditEntry(
            id="entry_123",
            timestamp=datetime.now(),
            session_id="session_456",
            iteration=0,
            action_type="CmdRunAction",
            action_content=special_content,
            risk_level=ActionSecurityRisk.LOW,
            validation_result="allowed",
        )
        assert entry.action_content == special_content
