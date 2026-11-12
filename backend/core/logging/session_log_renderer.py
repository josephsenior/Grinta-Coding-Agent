"""Render human-readable session.txt from session.jsonl events."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _header_line(width: int = 80) -> str:
    return '=' * width


def _block_header(ts: str, label: str, event_id: int | None = None) -> str:
    suffix = f' (event {event_id})' if event_id is not None else ''
    return f'{_header_line()}\n{ts} | {label}{suffix}\n{"-" * 80}'


def _payload_event_id(payload: dict[str, Any]) -> int | None:
    event_id = payload.get('event_id')
    return event_id if isinstance(event_id, int) else None


def _render_user_turn(ts: str, payload: dict[str, Any]) -> list[str]:
    text = str(payload.get('text', '') or '').strip()
    if not text:
        return []
    return [
        _block_header(ts, 'USER', event_id=_payload_event_id(payload)),
        text,
        '',
    ]


def _agent_step_label(payload: dict[str, Any]) -> str:
    if payload.get('tool_step'):
        return 'AGENT step (tools)'
    if payload.get('stream_final'):
        return 'AGENT stream-final'
    if payload.get('final_response'):
        return 'AGENT final-response'
    return 'AGENT step'


def _render_agent_step(ts: str, payload: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    text = str(payload.get('text', '') or '').strip()
    thinking = str(payload.get('thinking', '') or '').strip()
    if text:
        parts.append(text)
    if thinking:
        parts.append(f'[thinking]\n{thinking}')
    if not parts:
        return []
    return [
        _block_header(
            ts,
            _agent_step_label(payload),
            event_id=_payload_event_id(payload),
        ),
        '\n\n'.join(parts),
        '',
    ]


def _render_agent_think(ts: str, payload: dict[str, Any]) -> list[str]:
    thought = str(payload.get('thought', '') or '').strip()
    if not thought:
        return []
    return [
        _block_header(ts, 'AGENT think', event_id=_payload_event_id(payload)),
        thought,
        '',
    ]


def _render_tool_result(ts: str, payload: dict[str, Any]) -> list[str]:
    tool = payload.get('tool', '?')
    ok = payload.get('ok')
    preview = str(payload.get('preview', '') or '').strip()
    latency = payload.get('latency_ms')
    status = 'ok' if ok else 'FAIL'
    lat = f' {latency}ms' if latency is not None else ''
    lines = [f'--- TOOL {tool} [{status}{lat}] {ts} ---']
    if preview:
        lines.append(preview)
    lines.append('')
    return lines


def render_session_transcript(events: list[dict[str, Any]]) -> str:
    """Build session.txt content from parsed session.jsonl records."""
    lines: list[str] = [
        '# Grinta session transcript — derived from session.jsonl',
        '# User prompts, agent responses, thinking, and tool outcomes.',
        '',
    ]
    for record in events:
        event = record.get('event')
        ts = record.get('ts', '')
        payload = record.get('payload')
        if not isinstance(payload, dict):
            continue

        if event == 'USER_TURN':
            lines.extend(_render_user_turn(ts, payload))
        elif event == 'AGENT_STEP':
            lines.extend(_render_agent_step(ts, payload))
        elif event == 'AGENT_THINK':
            lines.extend(_render_agent_think(ts, payload))
        elif event == 'TOOL_RESULT':
            lines.extend(_render_tool_result(ts, payload))

    return '\n'.join(lines).rstrip() + '\n'


def write_session_transcript(events: list[dict[str, Any]], path: Path) -> None:
    path.write_text(render_session_transcript(events), encoding='utf-8')
