"""Tests for backend/core/workspace_resolution.py helpers."""

from __future__ import annotations

from backend.core.workspace_resolution import (
    WORKSPACE_NOT_OPEN_ERROR_ID,
    WORKSPACE_NOT_OPEN_MESSAGE,
    is_workspace_not_open_error,
)


def test_is_workspace_not_open_error_matches_exact_valueerror() -> None:
    exc = ValueError(WORKSPACE_NOT_OPEN_MESSAGE)
    assert is_workspace_not_open_error(exc) is True


def test_is_workspace_not_open_error_rejects_other_valueerror() -> None:
    assert is_workspace_not_open_error(ValueError("other")) is False


def test_workspace_constants_stable() -> None:
    assert "Open workspace" in WORKSPACE_NOT_OPEN_MESSAGE
    assert WORKSPACE_NOT_OPEN_ERROR_ID.startswith("WORKSPACE$")
