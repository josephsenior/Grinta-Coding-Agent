"""Outside-workspace read policy tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.type_safety.path_validation import (
    PathValidationError,
    is_denied_sensitive_read_path,
    validate_readable_path,
)


def test_sensitive_path_always_denied() -> None:
    assert is_denied_sensitive_read_path('C:/Users/me/.ssh/id_rsa') is True


def test_outside_path_blocked_without_opt_in(tmp_path: Path) -> None:
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    target = outside / 'readme.txt'
    target.write_text('hi', encoding='utf-8')

    with pytest.raises(PathValidationError, match='outside workspace boundary'):
        validate_readable_path(str(target), workspace, must_exist=True)


def test_outside_path_allowed_with_extra_root(tmp_path: Path) -> None:
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    target = outside / 'readme.txt'
    target.write_text('hi', encoding='utf-8')

    resolved = validate_readable_path(
        str(target),
        workspace,
        must_exist=True,
        extra_read_roots=(outside.resolve(),),
    )
    assert resolved == target.resolve()
