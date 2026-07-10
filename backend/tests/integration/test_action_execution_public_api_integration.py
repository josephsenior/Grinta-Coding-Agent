"""Surface-level integration checks for public helpers on ``action_execution_server``."""

from __future__ import annotations

from pathlib import Path

import pytest

import backend.execution.server.action_execution_server as aes


@pytest.mark.integration
def test_resolve_workspace_path_relative_and_absolute(tmp_path: Path) -> None:
    workspace = tmp_path / 'ws'
    nest = workspace / 'nest'
    (nest / 'more').mkdir(parents=True)
    (nest / 'more' / 'x.txt').write_text('b', encoding='utf-8')
    top = workspace / 'top.txt'
    top.write_text('a', encoding='utf-8')
    rel = aes.resolve_workspace_path('more/x.txt', str(nest), str(workspace))
    assert rel == (nest / 'more' / 'x.txt').resolve()
    abs_path = aes.resolve_workspace_path(str(top), str(nest), str(workspace))
    assert abs_path == top.resolve()


@pytest.mark.integration
def test_try_compile_user_regex_accepts_and_rejects_patterns() -> None:
    ok, err = aes.try_compile_user_regex(r'foo\d+bar')
    assert err is None
    assert ok is not None
    assert ok.search('foo99bar') is not None
    bad, bad_err = aes.try_compile_user_regex('(')
    assert bad is None
    assert bad_err
