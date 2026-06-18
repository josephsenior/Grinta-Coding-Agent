"""Custom exceptions for Windows-specific runtime issues."""

from __future__ import annotations


class DotNetMissingError(Exception):
    """Exception raised when .NET SDK or CoreCLR is missing or cannot be loaded.

    This is used to provide a cleaner error message to users without a full stack trace.
    """

    def __init__(self, message: str, details: str | None = None) -> None:
        """Store the primary error message and optional detail text."""
        self.message = message
        self.details = details
        super().__init__(message)
