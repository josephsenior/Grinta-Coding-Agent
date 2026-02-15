"""Safety configuration for Forge security controls."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class SafetyConfig(BaseModel):
    """Configurable safety knobs for the security analyser pipeline."""

    blocked_patterns: list[str] = Field(default_factory=list)
    allowed_exceptions: list[str] = Field(default_factory=list)
    risk_threshold: str = "HIGH"
    enable_audit_logging: bool = False
    audit_log_path: str = Field(
        default="audit.log",
        description="Path for the audit log file (relative or absolute).",
    )
    environment: str = "production"
    enable_mandatory_validation: bool = True
    block_in_production: bool = Field(
        default=True, description="Block high-risk actions in production"
    )
    require_review_for_high_risk: bool = Field(
        default=False, description="Require review for high-risk actions"
    )
    enable_risk_alerts: bool = Field(
        default=False, description="Enable risk alert notifications"
    )
    alert_webhook_url: str | None = Field(
        default=None, description="Webhook URL for risk alerts"
    )

    @field_validator("audit_log_path")
    @classmethod
    def _validate_audit_path(cls, v: str) -> str:
        """Ensure the audit log path is inside the working directory."""
        resolved = Path(v).resolve()
        cwd = Path.cwd().resolve()
        # Allow absolute paths only if they're under cwd or /tmp
        if resolved.is_absolute() and not (
            str(resolved).startswith(str(cwd))
            or str(resolved).startswith("/tmp")
            or str(resolved).startswith("C:\\Users")
        ):
            raise ValueError(
                f"audit_log_path must be relative or under the working directory, got: {v}"
            )
        return v


__all__ = ["SafetyConfig"]
