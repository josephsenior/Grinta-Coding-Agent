"""Runtime execution configuration schemas and helpers."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend._canonical import CanonicalModelMetaclass
from backend.core.constants import (
    DEFAULT_RUNTIME_AUTO_LINT_ENABLED,
    DEFAULT_RUNTIME_CLOSE_DELAY,
    DEFAULT_RUNTIME_KEEP_ALIVE,
    DEFAULT_RUNTIME_TIMEOUT,
)


class RuntimeConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for the runtime.

    Simplified for App Core (LocalRuntime only).
    """

    timeout: int = Field(
        default=DEFAULT_RUNTIME_TIMEOUT,
        ge=1,
        description='The timeout in seconds for the default runtime action execution',
    )
    enable_auto_lint: bool = Field(
        default=DEFAULT_RUNTIME_AUTO_LINT_ENABLED,
        description='Whether to enable auto-lint',
    )
    runtime_startup_env_vars: dict[str, str] = Field(
        default_factory=dict,
        description='The environment variables to set at the launch of the runtime',
    )
    selected_repo: str | None = Field(
        default=None, description='Selected repository for runtime operations'
    )
    close_delay: int = Field(
        default=DEFAULT_RUNTIME_CLOSE_DELAY,
        description='Delay in seconds before closing runtime',
    )
    keep_runtime_alive: bool = Field(
        default=DEFAULT_RUNTIME_KEEP_ALIVE,
        description='Whether to keep runtime alive between requests',
    )
    model_config = ConfigDict(extra='forbid')

    @classmethod
    def from_toml_section(cls, data: dict) -> dict[str, RuntimeConfig]:
        """Create a mapping of RuntimeConfig instances from the [runtime] section."""
        runtime_mapping: dict[str, RuntimeConfig] = {}
        try:
            runtime_mapping['runtime_config'] = cls.model_validate(data)
        except ValidationError as e:
            msg = f'Invalid runtime configuration: {e}'
            raise ValueError(msg) from e
        return runtime_mapping
