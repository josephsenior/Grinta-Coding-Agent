"""RendererDebuggerMixin: DAP debugger activity cards."""

from __future__ import annotations

import json
from typing import Any

from backend.cli.event_rendering.unified_renderer import ActivityRenderer
from backend.cli.tui.helpers import _join_secondary_parts
from backend.cli.tui.widgets.activity_card import ActivityCard as TUIActivityCard

_ACTION_VERBS: dict[str, str] = {
    'start': 'Starting',
    'set_breakpoints': 'Breakpoints',
    'continue': 'Continuing',
    'next': 'Stepping',
    'step_in': 'Stepping',
    'step_out': 'Stepping',
    'pause': 'Pausing',
    'stack': 'Stack',
    'scopes': 'Scopes',
    'variables': 'Variables',
    'evaluate': 'Evaluate',
    'status': 'Status',
    'stop': 'Stopping',
}

_STATE_VERBS: dict[str, str] = {
    'started': 'Started',
    'breakpoints_set': 'Breakpoints',
    'continued': 'Continued',
    'next': 'Stepped',
    'stepIn': 'Stepped',
    'stepOut': 'Stepped',
    'paused': 'Paused',
    'stack': 'Stack',
    'scopes': 'Scopes',
    'variables': 'Variables',
    'evaluated': 'Evaluated',
    'status': 'Status',
    'stopped': 'Stopped',
}


def _truncate(text: str, limit: int = 100) -> str:
    text = text.replace('\n', ' ').strip()
    return text[: limit - 3] + '...' if len(text) > limit else text


def _json_preview(value: Any, limit: int = 160) -> str:
    try:
        text = json.dumps(value, default=str, separators=(',', ':'))
    except Exception:
        text = str(value)
    return _truncate(text, limit)


class RendererDebuggerMixin:
    """DAP debugger cards keyed by session."""

    @staticmethod
    def _debugger_session_label(session_id: str) -> str | None:
        return f'session {session_id}' if session_id else None

    @staticmethod
    def _debugger_status_from_kind(secondary_kind: str) -> str:
        if secondary_kind == 'ok':
            return 'ok'
        if secondary_kind == 'err':
            return 'err'
        return 'neutral'

    def _debugger_card_detail_from_action(self, action: Any) -> str:
        debug_action = str(getattr(action, 'debug_action', '') or 'debugger')
        if debug_action == 'start':
            target = (
                getattr(action, 'program', None)
                or getattr(action, 'adapter', None)
                or getattr(action, 'language', None)
                or 'session'
            )
            return _truncate(str(target), 90)
        if debug_action == 'set_breakpoints':
            file = getattr(action, 'file', None) or 'breakpoints'
            lines = getattr(action, 'lines', None) or []
            line_text = ','.join(str(line) for line in lines[:4])
            if len(lines) > 4:
                line_text += ',...'
            return _truncate(f'{file}:{line_text}' if line_text else str(file), 90)
        if debug_action == 'evaluate':
            return _truncate(str(getattr(action, 'expression', '') or 'expression'), 90)
        if debug_action in {'scopes', 'variables'}:
            return _truncate(debug_action.replace('_', ' '), 90)
        return _truncate(debug_action.replace('_', ' '), 90)

    def _debugger_card_detail_from_payload(self, payload: dict[str, Any]) -> str:
        target = payload.get('target') or payload.get('state') or 'debugger'
        return _truncate(str(target), 90)

    def _resolve_debugger_widget(self, session_key: str, session_id: str) -> Any:
        widget = self._debugger_cards_by_session.get(session_key)
        if widget is None and session_id and self._pending_debugger_card is not None:
            widget = self._pending_debugger_card
            self._debugger_cards_by_session[session_key] = widget
            self._pending_debugger_card = None
        return widget

    def _create_and_write_debugger_card(
        self,
        session_key: str,
        session_id: str,
        verb: str,
        detail: str,
        secondary: str | None,
        secondary_kind: str,
        extra_content: str | None,
    ) -> None:
        card = ActivityRenderer.debugger_action(
            verb,
            detail,
            secondary=secondary,
            secondary_kind=secondary_kind,
            extra_content=extra_content,
        )
        widget = self._write_card(card, collapsed=True)
        widget.enable_incremental_mode()
        widget.configure_terminal(
            command=TUIActivityCard._command_from_detail(detail),
            session_id=session_id,
            shell_kind='debugger',
        )
        if session_id:
            self._debugger_cards_by_session[session_key] = widget
        else:
            self._pending_debugger_card = widget

    def _apply_debugger_processing(
        self,
        widget: Any,
        processing: bool,
        verb: str,
        detail: str,
        secondary: str | None,
        session_key: str,
    ) -> None:
        if processing:
            self._activate_activity_card(widget)
            return

        widget.set_processing(False)
        if self._last_active_card is widget:
            self._last_active_card = None

    def _upsert_debugger_session_card(
        self,
        *,
        session_id: str,
        verb: str,
        detail: str,
        secondary: str | None = None,
        secondary_kind: str = 'neutral',
        extra_content: str | None = None,
        processing: bool = True,
    ) -> None:
        session_key = session_id or 'debugger'
        widget = self._resolve_debugger_widget(session_key, session_id)
        if widget is None:
            self._create_and_write_debugger_card(
                session_key,
                session_id,
                verb,
                detail,
                secondary,
                secondary_kind,
                extra_content,
            )
            return

        widget.set_verb(verb, detail=detail)
        widget.set_status(
            self._debugger_status_from_kind(secondary_kind),
            outcome=secondary,
        )
        widget.configure_terminal(
            command=TUIActivityCard._command_from_detail(detail),
            session_id=session_id,
            shell_kind='debugger',
        )
        if extra_content:
            widget.update_content(extra_content)

        self._apply_debugger_processing(
            widget,
            processing,
            verb,
            detail,
            secondary,
            session_key,
        )

    def _debugger_payload_output(self, payload: dict[str, Any]) -> str:
        lines: list[str] = []
        state = payload.get('state')
        if state:
            lines.append(f'state: {state}')
        target = payload.get('target')
        if target:
            lines.append(f'target: {target}')
        thread_id = payload.get('current_thread_id')
        if thread_id is not None:
            lines.append(f'thread: {thread_id}')

        events = payload.get('events')
        if isinstance(events, list) and events:
            names = [str(event.get('event') or '?') for event in events[:8]]
            lines.append(f'events: {", ".join(names)}')

        for key in ('stackFrames', 'scopes', 'variables', 'breakpoints'):
            value = payload.get(key)
            if isinstance(value, list):
                lines.append(f'{key}: {len(value)}')
                for item in value[:5]:
                    lines.append(f'  - {_json_preview(item, 140)}')
            elif isinstance(value, dict):
                lines.append(f'{key}: {_json_preview(value, 180)}')

        for key in ('result', 'response'):
            if key in payload:
                lines.append(f'{key}: {_json_preview(payload[key], 180)}')

        stderr = payload.get('adapter_stderr')
        if isinstance(stderr, list) and stderr:
            lines.append('adapter stderr:')
            lines.extend(f'  {str(line)}' for line in stderr[-6:])

        return '\n'.join(lines[:28])

    def _handle_debugger_action_card(self, action: Any) -> None:
        debug_action = str(getattr(action, 'debug_action', '') or '').strip().lower()
        session_id = getattr(action, 'session_id', '') or ''
        verb = _ACTION_VERBS.get(debug_action, 'Debugging')
        detail = self._debugger_card_detail_from_action(action)
        self._upsert_debugger_session_card(
            session_id=session_id,
            verb=verb,
            detail=detail,
            secondary=_join_secondary_parts(
                self._debugger_session_label(session_id),
                'running request',
            ),
            secondary_kind='neutral',
            processing=True,
        )

    def _handle_debugger_observation_card(self, observation: Any) -> None:
        payload = dict(getattr(observation, 'payload', None) or {})
        session_id = str(
            getattr(observation, 'session_id', None) or payload.get('session_id') or ''
        )
        state = str(getattr(observation, 'state', None) or payload.get('state') or '')
        verb = _STATE_VERBS.get(state, 'Debugger')
        detail = self._debugger_card_detail_from_payload(payload)
        output = self._debugger_payload_output(payload)
        content = str(getattr(observation, 'content', '') or '').strip()
        if content and content not in output:
            output = f'{output}\n{content}'.strip()
        secondary = _join_secondary_parts(
            self._debugger_session_label(session_id),
            state or 'updated',
        )
        self._upsert_debugger_session_card(
            session_id=session_id,
            verb=verb,
            detail=detail,
            secondary=secondary,
            secondary_kind='ok',
            extra_content=output or None,
            processing=False,
        )
