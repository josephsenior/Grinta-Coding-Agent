"""Unit tests for observation dispatch table."""

from __future__ import annotations

from types import SimpleNamespace

from backend.cli.event_rendering.observations.dispatch import _ObsDispatchMixin
from backend.ledger.observation import (
    ErrorObservation,
    GrepObservation,
    StatusObservation,
    SuccessObservation,
)


class _Host(_ObsDispatchMixin):
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._pending_shell_command = None
        self._pending_shell_action = None
        self._pending_shell_title = None
        self._pending_shell_is_internal = False

    def refresh(self) -> None:
        self.calls.append('refresh')

    def _render_error_observation(self, obs) -> None:
        self.calls.append('error')

    def _render_grep_observation(self, obs) -> None:
        self.calls.append('grep')

    def _render_status_observation(self, obs) -> None:
        self.calls.append('status')

    def _render_success_observation(self, obs) -> None:
        self.calls.append('success')


def test_handle_observation_dispatches_known_types() -> None:
    host = _Host()
    host._handle_observation(ErrorObservation(content='boom'))
    host._handle_observation(GrepObservation(pattern='x'))
    host._handle_observation(StatusObservation(content='ok'))
    host._handle_observation(SuccessObservation(content='done'))
    assert host.calls == ['error', 'grep', 'status', 'success']


def test_handle_observation_refreshes_on_unknown_type() -> None:
    host = _Host()
    host._handle_observation(SimpleNamespace())
    assert host.calls == ['refresh']


def test_observation_dispatch_table_contains_core_types() -> None:
    mapped = {name for _, name in _ObsDispatchMixin._OBSERVATION_DISPATCH}
    assert '_render_error_observation' in mapped
    assert '_render_mcp_observation' in mapped
    assert '_render_grep_observation' in mapped
