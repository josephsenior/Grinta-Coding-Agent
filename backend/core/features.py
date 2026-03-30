"""Feature flags for controlling advanced/proprietary features."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.config import AppConfig


class FeatureUnavailableError(Exception):
    """Raised when a feature is requested but not available/enabled."""

    def __init__(self, feature_name: str, message: str | None = None) -> None:
        """Initialize feature unavailable error.

        Args:
            feature_name: Name of the unavailable feature
            message: Optional custom error message
        """
        self.feature_name = feature_name
        if message is None:
            message = (
                f"Feature '{feature_name}' is not available in App Core. "
                "This feature is part of the App Pro/Enterprise editions."
            )
        super().__init__(message)


class FeatureFlags:
    """Centralized feature flag management.

    Reads feature flags from AppConfig and provides easy access to feature
    availability status.
    """

    def __init__(self, config: AppConfig | None = None) -> None:
        """Initialize feature flags from config.

        Args:
            config: AppConfig instance.
        """
        self._config = config

    @property
    def risk_assessment_enabled(self) -> bool:
        """Check if security risk assessment is enabled.

        Always False in App Core.
        """
        return False

    def get_flags_for_ui(self) -> dict[str, dict[str, str | bool]]:
        """Get feature flags formatted for client consumption.

        Returns:
            Dictionary of feature flags with metadata
        """
        return {
            "security_risk_assessment": {
                "enabled": self.risk_assessment_enabled,
                "coming_soon": True,
                "tier": "pro",
                "description": "Security risk assessment for agent actions",
            },
        }


def get_feature_flags(config: AppConfig | None = None) -> FeatureFlags:
    """Get feature flags instance.

    Args:
        config: AppConfig instance.

    Returns:
        FeatureFlags instance.
    """
    return FeatureFlags(config)
