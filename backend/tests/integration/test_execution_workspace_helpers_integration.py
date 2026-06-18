"""Integration checks for workspace cwd helpers used by the runtime (real paths)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.execution.aes import helpers as h
from backend.ledger.observation import ErrorObservation


def _executor_for_workspace(root: Path) -> SimpleNamespace:
    root_s = str(root.resolve())
    ex = SimpleNamespace()
    ex.username = 'u'
    ex._initial_cwd = root_s
    ex.security_config = SimpleNamespace(execution_profile='hardened_local')
    ex.session_manager = SimpleNamespace(
        tool_registry=None, get_session=lambda _sid: None, close_session=MagicMock()
    )
    ex._terminal_session_seq = 0
    ex._terminal_sessions_awaiting_interaction = []
    ex._terminal_open_commands_no_interaction = []
    ex._terminal_read_cursor = {}
    ex._workspace_root = lambda: root.resolve()
    ex._is_workspace_restricted_profile = lambda: True
    ex._resolve_effective_cwd = (
        lambda requested_cwd, base_cwd=None: h.resolve_effective_cwd(
            ex, requested_cwd, base_cwd
        )
    )
    ex._clear_terminal_read_cursor = MagicMock()
    ex._normalize_terminal_command = h.normalize_terminal_command
    return ex


@pytest.mark.integration
def test_resolve_effective_cwd_nested_relative_to_workspace(tmp_path: Path) -> None:
    (tmp_path / 'pkg' / 'inner').mkdir(parents=True)
    ex = _executor_for_workspace(tmp_path)
    assert (
        h.resolve_effective_cwd(ex, 'pkg/inner')
        == (tmp_path / 'pkg' / 'inner').resolve()
    )


@pytest.mark.integration
def test_resolve_effective_cwd_none_is_workspace_root(tmp_path: Path) -> None:
    ex = _executor_for_workspace(tmp_path)
    assert h.resolve_effective_cwd(ex, None) == tmp_path.resolve()


@pytest.mark.integration
def test_validate_workspace_scoped_cwd_errors_when_outside_workspace(
    tmp_path: Path,
) -> None:
    ex = _executor_for_workspace(tmp_path)
    with patch(
        'backend.execution.aes.helpers.path_is_within_workspace',
        return_value=False,
    ):
        err = h.validate_workspace_scoped_cwd(ex, 'run', '../../outside')
    assert isinstance(err, ErrorObservation)
    assert err.content


@pytest.mark.integration
def test_predict_interactive_cwd_change_cd_into_subdirectory(tmp_path: Path) -> None:
    sub = tmp_path / 'pkg'
    sub.mkdir()
    ex = _executor_for_workspace(tmp_path)
    predicted, policy_err = h.predict_interactive_cwd_change(
        ex, 'cd pkg', tmp_path.resolve()
    )
    assert policy_err is None
    assert predicted == sub.resolve()


@pytest.mark.integration
def test_next_terminal_session_id_skips_colliding_ids(tmp_path: Path) -> None:
    ex = _executor_for_workspace(tmp_path)
    ex.session_manager.sessions = {  # type: ignore[attr-defined]
        'terminal_1': object(),
        'terminal_2': object(),
        'terminal_3': object(),
    }
    assert h.next_terminal_session_id(ex) == 'terminal_4'


@pytest.mark.integration
def test_apply_grep_filter_matches_and_regex_error(tmp_path: Path) -> None:
    assert tmp_path.exists()
    body = 'alpha\nbeta\nalpha again\n'
    hit = h.apply_grep_filter(body, r'alpha')
    assert 'alpha' in hit
    bad = h.apply_grep_filter(body, '(')
    assert 'Grep Error' in bad or 'Invalid' in bad
