"""Tests for backend/core/workspace_resolution.py helpers."""

from __future__ import annotations

from backend.core.workspace_resolution import (
    WORKSPACE_NOT_OPEN_ERROR_ID,
    WORKSPACE_NOT_OPEN_MESSAGE,
    is_workspace_not_open_error,
    normalize_user_workspace_path,
    resolve_existing_directory,
)


def test_is_workspace_not_open_error_matches_exact_valueerror() -> None:
    exc = ValueError(WORKSPACE_NOT_OPEN_MESSAGE)
    assert is_workspace_not_open_error(exc) is True


def test_is_workspace_not_open_error_rejects_other_valueerror() -> None:
    assert is_workspace_not_open_error(ValueError("other")) is False


def test_workspace_constants_stable() -> None:
    assert "Open workspace" in WORKSPACE_NOT_OPEN_MESSAGE
    assert WORKSPACE_NOT_OPEN_ERROR_ID.startswith("WORKSPACE$")


def test_normalize_user_workspace_path_strips_quotes() -> None:
    assert normalize_user_workspace_path('  "/tmp/my project"  ') == "/tmp/my project"


def test_normalize_user_workspace_path_file_url_windows(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    assert normalize_user_workspace_path("file:///C:/Users/me/repo") == "C:/Users/me/repo"


def test_resolve_existing_directory_after_normalization(tmp_path) -> None:
    d = tmp_path / "w"
    d.mkdir()
    quoted = f'"{d}"'
    assert resolve_existing_directory(quoted) == d.resolve()
