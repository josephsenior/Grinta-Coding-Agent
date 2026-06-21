"""RendererDebuggerMixin: DAP debugger scan-line cards."""

from __future__ import annotations

import json
from typing import Any


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
    """DAP debugger scan-line cards."""

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

    def _handle_debugger_action_card(self, action: Any) -> None:
        detail = self._debugger_card_detail_from_action(action)
        self._create_and_append_debugger_scan_card(
            location=detail,
            function='',
            state='running',
        )

    def _handle_debugger_observation_card(self, observation: Any) -> None:
        payload = dict(getattr(observation, 'payload', None) or {})
        detail = self._debugger_card_detail_from_payload(payload)
        target = payload.get('target') or payload.get('state') or ''
        self._create_and_append_debugger_scan_card(
            location=detail,
            function=target,
            payload=payload,
            state='done',
        )

    @staticmethod
    def _extract_debugger_stack(payload: dict[str, Any]) -> list[str]:
        frames = payload.get('stackFrames')
        if not isinstance(frames, list):
            return []
        result: list[str] = []
        for frame in frames[:16]:
            if not isinstance(frame, dict):
                continue
            name = frame.get('name', '?')
            source = frame.get('source', {})
            if isinstance(source, dict):
                sname = source.get('name', '?')
                line = source.get('line', '')
                result.append(
                    f'{name}()  {sname}:{line}' if line else f'{name}()  {sname}'
                )
            else:
                result.append(f'{name}()')
        return result

    @staticmethod
    def _extract_debugger_variables(payload: dict[str, Any]) -> list[tuple[str, str]]:
        variables = payload.get('variables')
        if not isinstance(variables, list):
            return []
        result: list[tuple[str, str]] = []
        for item in variables[:20]:
            if isinstance(item, dict):
                result.append((str(item.get('name', '?')), str(item.get('value', '?'))))
        return result

    def _create_and_append_debugger_scan_card(
        self,
        location: str,
        function: str,
        *,
        payload: dict[str, Any] | None = None,
        state: str = 'done',
    ) -> Any:
        from backend.cli.tui.widgets.scan_line import DebuggerCard

        p = payload or {}
        stack = self._extract_debugger_stack(p)
        variables = self._extract_debugger_variables(p)

        self.commit_live_thinking()
        card = DebuggerCard(
            location=location,
            function=function,
            stack=stack or None,
            variables=variables or None,
        )
        card.set_state(state)
        self._append_scan_line_card(card)
        return card
