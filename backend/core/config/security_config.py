"""Security-related configuration schemas for Forge deployments."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend._canonical import CanonicalModelMetaclass


class SecurityConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for security related functionalities.

    Attributes:
        confirmation_mode: Whether to enable confirmation mode.
        security_analyzer: The security analyzer to use.
        enforce_security: Whether the security analyzer should block/confirm risky actions.
        block_high_risk: Whether HIGH-risk actions should be blocked outright (True)
            or require user confirmation (False, the default).
        validation_mode: Conversation access validation strictness.
            - ``permissive``: No ownership check, anonymous access auto-creates metadata
              (default — suitable for single-user / local-first usage).
            - ``strict``: Enforces conversation ownership — user_id must match the
              conversation creator, and anonymous (None) user_id is rejected.

    """

    confirmation_mode: bool = Field(default=True)
    security_analyzer: str | None = Field(default=None)
    enforce_security: bool = Field(
        default=True,
        description="When True, HIGH-risk actions are blocked or require confirmation. "
        "When False, the analyzer only logs classifications.",
    )
    block_high_risk: bool = Field(
        default=False,
        description="When True, HIGH-risk actions are rejected outright. When False, they require user confirmation.",
    )
    validation_mode: Literal["permissive", "strict"] = Field(
        default="permissive",
        description=(
            "Conversation access validation strictness. "
            "'permissive' skips ownership checks (single-user default). "
            "'strict' enforces conversation ownership and rejects anonymous access."
        ),
    )
    model_config = ConfigDict(extra="ignore")

    @classmethod
    def from_toml_section(cls, data: dict) -> dict[str, SecurityConfig]:
        """Create a mapping of SecurityConfig instances from a toml dictionary representing the [security] section.

        The configuration is built from all keys in data.

        Returns:
            dict[str, SecurityConfig]: A mapping where the key "security" corresponds to the [security] configuration

        """
        security_mapping: dict[str, SecurityConfig] = {}
        try:
            security_mapping["security"] = cls.model_validate(data)
        except ValidationError as e:
            msg = f"Invalid security configuration: {e}"
            raise ValueError(msg) from e
        return security_mapping
