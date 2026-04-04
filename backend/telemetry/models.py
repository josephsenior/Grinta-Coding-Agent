"""Data models for audit logging system."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from backend.ledger.action import ActionSecurityRisk


class AuditEntry(BaseModel):
    """Immutable audit log entry for an agent action."""

    id: str = Field(
        ..., min_length=1, description='Unique identifier for this audit entry'
    )

    timestamp: datetime = Field(..., description='When the action occurred')

    session_id: str = Field(..., min_length=1, description='Session ID of the agent')

    iteration: int = Field(
        ..., ge=0, description='Iteration number when action occurred'
    )

    action_type: str = Field(
        ...,
        min_length=1,
        description='Type of action (CmdRunAction, FileEditAction, etc.)',
    )

    action_content: str = Field(..., description='Content/details of the action')

    risk_level: ActionSecurityRisk = Field(
        ..., description='Assessed risk level of the action'
    )

    validation_result: str = Field(
        ...,
        min_length=1,
        description="Result of validation: 'allowed', 'blocked', 'requires_review'",
    )

    execution_result: str | None = Field(
        default=None, description='Result of action execution if it was allowed'
    )

    blocked_reason: str | None = Field(
        default=None, description='Reason for blocking if action was blocked'
    )

    filesystem_snapshot_id: str | None = Field(
        default=None,
        description='ID of filesystem snapshot if taken before high-risk action',
    )

    rollback_available: bool = Field(
        default=False, description='Whether rollback is available for this action'
    )

    matched_risk_patterns: list[str] = Field(
        default_factory=list, description='Risk patterns that matched this action'
    )

    environment: str = Field(
        default='development',
        min_length=1,
        description='Environment where action occurred',
    )

    agent_state: str = Field(
        default='unknown',
        min_length=1,
        description='State of agent when action occurred',
    )

    @field_validator(
        'id',
        'session_id',
        'action_type',
        'validation_result',
        'environment',
        'agent_state',
    )
    @classmethod
    def validate_required_strings(cls, v: str) -> str:
        """Validate required string fields are non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name='field')

    @field_validator('validation_result')
    @classmethod
    def validate_validation_result(cls, v: str) -> str:
        """Validate validation_result is one of the allowed values."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        validated = validate_non_empty_string(v, name='validation_result')
        if validated not in ['allowed', 'blocked', 'requires_review']:
            raise ValueError(
                'validation_result must be one of: allowed, blocked, requires_review'
            )
        return validated

    def to_dict(self) -> dict:
        """Convert audit entry to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat(),
            'session_id': self.session_id,
            'iteration': self.iteration,
            'action_type': self.action_type,
            'action_content': self.action_content,
            'risk_level': self.risk_level.name,
            'validation_result': self.validation_result,
            'execution_result': self.execution_result,
            'blocked_reason': self.blocked_reason,
            'filesystem_snapshot_id': self.filesystem_snapshot_id,
            'rollback_available': self.rollback_available,
            'matched_risk_patterns': self.matched_risk_patterns,
            'environment': self.environment,
            'agent_state': self.agent_state,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AuditEntry:
        """Create audit entry from dictionary."""
        # Convert timestamp string back to datetime
        if isinstance(data.get('timestamp'), str):
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])

        # Convert risk_level string back to enum
        if isinstance(data.get('risk_level'), str):
            data['risk_level'] = ActionSecurityRisk[data['risk_level']]

        return cls(**data)
