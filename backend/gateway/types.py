"""Type abstractions and enums shared across the server stack."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Protocol

from backend.core.errors import UserActionRequiredError
from backend.core.schemas import AppMode


class SessionMiddlewareInterface(Protocol):
    """Protocol for session middleware classes."""


class ServerConfigInterface(ABC):
    """Abstract interface describing server configuration requirements."""

    CONFIG_PATH: ClassVar[str | None]
    APP_MODE: ClassVar[AppMode]
    POSTHOG_CLIENT_KEY: ClassVar[str]
    GITHUB_CLIENT_ID: ClassVar[str]
    ATTACH_SESSION_MIDDLEWARE_PATH: ClassVar[str]

    @abstractmethod
    def verify_config(self) -> None:
        """Verify configuration settings."""
        raise NotImplementedError

    @abstractmethod
    def get_config(self) -> dict[str, Any]:
        """Configure attributes for client."""
        raise NotImplementedError


class MissingSettingsError(UserActionRequiredError, ValueError):
    """Raised when settings are missing or not found.

    Dual-inherits ``UserActionRequiredError`` (from the canonical ``AppError``
    tree) **and** ``ValueError`` for broad compatibility with caller error
    handling expectations.
    """


class LLMAuthenticationError(UserActionRequiredError, ValueError):
    """Raised when there is an issue with LLM authentication.

    Dual-inherits ``UserActionRequiredError`` and ``ValueError`` for consistent
    caller error handling behavior.
    """


__all__ = [
    "SessionMiddlewareInterface",
    "ServerConfigInterface",
    "MissingSettingsError",
    "LLMAuthenticationError",
]
