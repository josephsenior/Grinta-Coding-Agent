"""Render human-readable session.txt from session.jsonl events."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _header_line(width: int = 80) -> str:
    return '=' * width


def _block_header(ts: str, label: str, event_id: int | None = None) -> str:
    suffix = f' (event {event_id})' if event_id is not None else ''
    return f'{_header_line()}\n{ts} | {label}{suffix}\n{"-" * 80}'


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
            text = str(payload.get('text', '') or '').strip()
            if not text:
                continue
            eid = payload.get('event_id')
            lines.append(
                _block_header(
                    ts, 'USER', event_id=eid if isinstance(eid, int) else None
                )
            )
            lines.append(text)
            lines.append('')

        elif event == 'AGENT_STEP':
            parts: list[str] = []
            text = str(payload.get('text', '') or '').strip()
            thinking = str(payload.get('thinking', '') or '').strip()
            if text:
                parts.append(text)
            if thinking:
                parts.append(f'[thinking]\n{thinking}')
            if not parts:
                continue
            label = (
                'AGENT final-response'
                if payload.get('final_response')
                else 'AGENT step'
            )
            if payload.get('tool_step'):
                label = 'AGENT step (tools)'
            elif payload.get('stream_final'):
                label = 'AGENT stream-final'
            eid = payload.get('event_id')
            lines.append(
                _block_header(
                    ts,
                    label,
                    event_id=eid if isinstance(eid, int) else None,
                )
            )
            lines.append('\n\n'.join(parts))
            lines.append('')

        elif event == 'AGENT_THINK':
            thought = str(payload.get('thought', '') or '').strip()
            if not thought:
                continue
            eid = payload.get('event_id')
            lines.append(
                _block_header(
                    ts, 'AGENT think', event_id=eid if isinstance(eid, int) else None
                )
            )
            lines.append(thought)
            lines.append('')

        elif event == 'TOOL_RESULT':
            tool = payload.get('tool', '?')
            ok = payload.get('ok')
            preview = str(payload.get('preview', '') or '').strip()
            latency = payload.get('latency_ms')
            status = 'ok' if ok else 'FAIL'
            lat = f' {latency}ms' if latency is not None else ''
            lines.append(f'--- TOOL {tool} [{status}{lat}] {ts} ---')
            if preview:
                lines.append(preview)
            lines.append('')

    return '\n'.join(lines).rstrip() + '\n'


def write_session_transcript(events: list[dict[str, Any]], path: Path) -> None:
    path.write_text(render_session_transcript(events), encoding='utf-8')
