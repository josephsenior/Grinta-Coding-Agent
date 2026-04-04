"""Provider data models and type aliases.

These types were extracted from ``backend.integrations`` during the removal
of the GitHub integration layer.  They capture provider token management,
custom secret storage, and the enum of supported provider backends — all of
which are still required by the session, storage, and runtime subsystems for
secret masking and environment variable propagation.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    WithJsonSchema,
    field_validator,
)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ProviderType(Enum):
    """Git provider type enumeration.

    Kept as a single-member enum so that existing serialization round-trips
    and dictionary keys continue to work without code changes.
    """

    ENTERPRISE_SSO = 'enterprise_sso'


class TaskType(str, Enum):
    """Task type enumeration for suggested tasks."""

    MERGE_CONFLICTS = 'MERGE_CONFLICTS'
    FAILING_CHECKS = 'FAILING_CHECKS'
    UNRESOLVED_COMMENTS = 'UNRESOLVED_COMMENTS'
    OPEN_ISSUE = 'OPEN_ISSUE'
    OPEN_PR = 'OPEN_PR'
    CREATE_PLAYBOOK = 'CREATE_PLAYBOOK'


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ProviderToken(BaseModel):
    """Typed container for provider access tokens plus optional metadata."""

    token: SecretStr | None = Field(
        default=None, description='Provider access token (secret)'
    )
    user_id: str | None = Field(
        default=None, description='User ID associated with the token'
    )
    host: str | None = Field(
        default=None,
        description='Custom host/domain for the provider (e.g., github.company.com)',
    )
    model_config = ConfigDict(frozen=True, validate_assignment=True)

    @field_validator('user_id', 'host')
    @classmethod
    def validate_optional_strings(cls, v: str | None) -> str | None:
        """Validate optional string fields are non-empty if provided."""
        if v is not None:
            from backend.core.type_safety.type_safety import validate_non_empty_string

            return validate_non_empty_string(v, name='field')
        return v

    @classmethod
    def from_value(cls, token_value: object) -> ProviderToken:
        """Factory method to create a ProviderToken from various input types."""
        if isinstance(token_value, cls):
            return token_value
        if isinstance(token_value, dict):
            token_raw = token_value.get('token')
            token_str = token_raw if isinstance(token_raw, str) else ''
            user_id = token_value.get('user_id')
            host = token_value.get('host')
            return cls(token=SecretStr(token_str), user_id=user_id, host=host)
        msg = 'Unsupported Provider token type'
        raise ValueError(msg)


class CustomSecret(BaseModel):
    """Represents a user-defined secret (value plus description)."""

    secret: SecretStr = Field(
        default_factory=lambda: SecretStr(''),
        description='The secret value (encrypted)',
    )
    description: str = Field(
        default='', description='Description of what this secret is used for'
    )
    model_config = ConfigDict(frozen=True, validate_assignment=True)

    @classmethod
    def from_value(cls, secret_value: object) -> CustomSecret:
        """Factory method to create a CustomSecret from various input types."""
        if isinstance(secret_value, CustomSecret):
            return secret_value
        if isinstance(secret_value, dict):
            secret_raw = secret_value.get('secret')
            description_raw = secret_value.get('description')
            secret = secret_raw if isinstance(secret_raw, str) else ''
            description = description_raw if isinstance(description_raw, str) else ''
            return cls(secret=SecretStr(secret), description=description)
        msg = 'Unsupported Provider token type'
        raise ValueError(msg)


class SuggestedTask(BaseModel):
    """Model representing a suggested task from a git provider.

    Retained for API compatibility. The ``get_prompt_for_task`` method returns
    a simple string description since the Jinja2 templates were removed with
    the GitHub integration layer.
    """

    vcs_provider: ProviderType = Field(..., description='Git provider type')
    task_type: TaskType = Field(..., description='Type of suggested task')
    repo: str = Field(
        ..., min_length=1, description="Repository name in format 'owner/repo'"
    )
    issue_number: int = Field(..., ge=1, description='Issue or PR number')
    title: str = Field(..., min_length=1, description='Task title')

    @field_validator('repo', 'title')
    @classmethod
    def validate_required_strings(cls, v: str) -> str:
        """Validate required string fields are non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name='field')

    def get_prompt_for_task(self) -> str:
        """Generate a plain-text prompt for the suggested task."""
        return (
            f'[{self.task_type.value}] {self.title} '
            f'(#{self.issue_number} in {self.repo})'
        )


class CreatePlaybook(BaseModel):
    """Model for creating a new playbook."""

    repo: str = Field(
        ..., min_length=1, description="Repository name in format 'owner/repo'"
    )
    vcs_provider: ProviderType | None = Field(
        default=None, description='Git provider type (optional, will be auto-detected)'
    )
    title: str | None = Field(
        default=None, description='Optional title for the playbook'
    )

    @field_validator('repo')
    @classmethod
    def validate_repo(cls, v: str) -> str:
        """Validate repository name is non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name='repo')

    @field_validator('title')
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        """Validate title is non-empty if provided."""
        if v is not None:
            from backend.core.type_safety.type_safety import validate_non_empty_string

            return validate_non_empty_string(v, name='title')
        return v


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

ProviderTokenType = Mapping[ProviderType, ProviderToken]
CustomSecretsType = Mapping[str, CustomSecret]
ProviderTokenFieldType = dict[ProviderType, ProviderToken]
CustomSecretsFieldType = dict[str, CustomSecret]
ProviderTokenWithTypeSchema = Annotated[
    ProviderTokenFieldType,
    WithJsonSchema({'type': 'object', 'additionalProperties': {'type': 'string'}}),
]
CustomSecretsWithTypeSchema = Annotated[
    CustomSecretsFieldType,
    WithJsonSchema({'type': 'object', 'additionalProperties': {'type': 'string'}}),
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AuthenticationError(ValueError):
    """Raised when there is an issue with provider authentication."""
