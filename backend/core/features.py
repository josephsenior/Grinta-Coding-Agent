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
            message = f"Feature '{feature_name}' is not available."
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
        """Check if security risk assessment is enabled."""
        return False


def get_feature_flags(config: AppConfig | None = None) -> FeatureFlags:
    """Get feature flags instance.

    Args:
        config: AppConfig instance.

    Returns:
        FeatureFlags instance.
    """
    return FeatureFlags(config)
