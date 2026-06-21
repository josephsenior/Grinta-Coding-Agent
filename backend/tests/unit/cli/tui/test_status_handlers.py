"""Unit tests for TUI status/error observation handlers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.cli.tui.renderer.handlers.status import (
    _handle_error_observation,
    notify_ui_only_error,
)
from backend.ledger.observation.error import ERROR_CATEGORY_RATE_LIMIT
from backend.ledger.observation import ErrorObservation


class TestNotifyUiOnlyError:
    def test_dedupes_identical_toast(self) -> None:
        tui = SimpleNamespace(
            notify_error=MagicMock(),
            notify_warning=MagicMock(),
            notify=MagicMock(),
            set_runtime_status=MagicMock(),
            _last_notify_ui_only_signature=None,
        )

        notify_ui_only_error(
            tui,
            'Invalid request: bad temperature',
            'bad_request',
            error_id='LLM_BAD_REQUEST',
        )
        notify_ui_only_error(
            tui,
            'Invalid request: bad temperature',
            'bad_request',
            error_id='LLM_BAD_REQUEST',
        )

        assert tui.notify_error.call_count == 1
        tui.set_runtime_status.assert_called_once_with(
            'Invalid request',
            meta='Invalid request: bad temperature',
            active=True,
        )

    def test_rate_limit_is_hud_only_without_toast(self) -> None:
        tui = SimpleNamespace(
            notify_error=MagicMock(),
            notify_warning=MagicMock(),
            notify=MagicMock(),
            set_runtime_status=MagicMock(),
            _last_notify_ui_only_signature=None,
        )

        notify_ui_only_error(
            tui,
            '⚠️ Too many requests per minute (RPM limit).',
            ERROR_CATEGORY_RATE_LIMIT,
            error_id='AGENT_STEP_EXCEPTION',
        )

        tui.notify_warning.assert_not_called()
        tui.notify_error.assert_not_called()
        tui.set_runtime_status.assert_not_called()

    def test_circuit_breaker_warning_is_toast_not_transcript_panel(self) -> None:
        tui = SimpleNamespace(
            notify_warning=MagicMock(),
            notify=MagicMock(),
            add_error_panel=MagicMock(),
            _last_notify_ui_only_signature=None,
        )
        orch = SimpleNamespace(_tui=tui)
        event = ErrorObservation(
            content=(
                'CIRCUIT_BREAKER_WARNING: Too many consecutive errors (5). '
                'Try a different approach. (1/3)'
            ),
            error_id='CIRCUIT_BREAKER_WARNING',
        )

        _handle_error_observation(orch, event)
        _handle_error_observation(
            orch,
            ErrorObservation(
                content=(
                    'CIRCUIT_BREAKER_WARNING: Too many consecutive errors (6). '
                    'Try a different approach. (2/3)'
                ),
                error_id='CIRCUIT_BREAKER_WARNING',
            ),
        )

        tui.add_error_panel.assert_not_called()
        assert tui.notify_warning.call_count == 1
