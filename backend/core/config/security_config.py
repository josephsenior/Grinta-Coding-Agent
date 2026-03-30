"""Security-related configuration schemas for App deployments."""

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

    confirmation_mode: bool = Field(default=False)
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
    execution_profile: Literal["standard", "hardened_local"] = Field(
        default="standard",
        description=(
            "Runtime execution profile. 'standard' preserves current local behavior. "
            "'hardened_local' adds stricter local policy gates for commands and file access."
        ),
    )
    allow_network_commands: bool = Field(
        default=False,
        description=(
            "When execution_profile='hardened_local', allow network-capable shell commands "
            "such as curl, wget, scp, rsync, and netcat."
        ),
    )
    allow_package_installs: bool = Field(
        default=False,
        description=(
            "When execution_profile='hardened_local', allow package installation commands "
            "such as pip install, npm install, and Install-Module."
        ),
    )
    allow_background_processes: bool = Field(
        default=False,
        description=(
            "When execution_profile='hardened_local', allow starting background processes."
        ),
    )
    allow_sensitive_path_access: bool = Field(
        default=False,
        description=(
            "When execution_profile='hardened_local', allow read/write access to sensitive "
            "workspace files such as .env, .ssh, and credential stores."
        ),
    )
    hardened_local_git_allowlist: list[str] = Field(
        default_factory=lambda: [
            "status",
            "diff",
            "log",
            "show",
            "branch",
            "rev-parse",
            "ls-files",
        ],
        description=(
            "When execution_profile='hardened_local', git subcommands allowed to run "
            "inside the workspace without broad git write/network permission."
        ),
    )
    hardened_local_package_allowlist: list[str] = Field(
        default_factory=list,
        description=(
            "When execution_profile='hardened_local', package-management operations "
            "allowed inside the workspace, e.g. ['npm_install', 'pnpm_add']."
        ),
    )
    hardened_local_network_allowlist: list[str] = Field(
        default_factory=list,
        description=(
            "When execution_profile='hardened_local', network-capable command families "
            "allowed inside the workspace, e.g. ['curl', 'invoke-webrequest']."
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
