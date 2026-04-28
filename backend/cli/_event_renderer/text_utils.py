"""Reasoning / transcript text sanitisation helpers."""

from __future__ import annotations

import os
import textwrap
from typing import Any

from backend.cli._event_renderer.constants import (
    INTERNAL_THINK_LABELS,
    INTERNAL_THINK_TAG_RE,
    THINK_RESULT_JSON_RE,
    TOOL_RESULT_TAG_RE,
    VISIBLE_INTERNAL_BLOCK_TAG_RE,
    VISIBLE_INTERNAL_SECTION_RE,
    VISIBLE_SUPPRESSED_LINE_RE,
)
from backend.cli.layout_tokens import (
    ACTIVITY_CARD_TITLE_TERMINAL,
    TRANSCRIPT_LEFT_INSET,
    TRANSCRIPT_RIGHT_INSET,
)
from backend.cli.tool_call_display import (
    redact_internal_result_markers,
    redact_streamed_tool_call_markers,
    redact_task_list_json_blobs,
)
from backend.engine import prompt_role_debug as _prompt_role_debug


def show_reasoning_text() -> bool:
    """Whether to render model reasoning text in CLI.

    Default is on for backward compatibility.  Set
    ``APP_CLI_SHOW_REASONING_TEXT=0`` to suppress provider reasoning leakage.
    """
    raw = os.environ.get('APP_CLI_SHOW_REASONING_TEXT', '').strip().lower()
    return raw not in ('0', 'false', 'no', 'off')


def sync_reasoning_after_tool_line(
    reasoning: Any,
    tool_label: str,
    thought: str,
) -> None:
    """Live panel: spinner + optional dim thinking text after a tool line."""
    label = (tool_label or '').strip()
    t = (thought or '').strip()
    if not label and not t:
        return
    _prompt_role_debug.log_reasoning_transition('tool_line', label or t)
    reasoning.start()
    if label:
        _prompt_role_debug.log_reasoning_transition('update_action', label)
        reasoning.update_action(label)
    if t and show_reasoning_text():
        _prompt_role_debug.log_reasoning_transition('update_thought', t)
        reasoning.update_thought(t)


def normalize_reasoning_text(text: str) -> tuple[str | None, str | None]:
    """Split internal tagged thoughts into a label + optional short text."""
    stripped = (text or '').strip()
    if not stripped or stripped == 'Your thought has been logged.':
        return None, None

    stripped = THINK_RESULT_JSON_RE.sub('', stripped).strip()
    stripped = TOOL_RESULT_TAG_RE.sub('', stripped).strip()
    if not stripped:
        return None, None

    match = INTERNAL_THINK_TAG_RE.match(stripped)
    if not match:
        return None, stripped

    tag = match.group('tag')
    label = INTERNAL_THINK_LABELS.get(
        tag,
        tag.replace('_', ' ').capitalize() + '…',
    )
    # Internal tagged thoughts are state updates, not user-facing prose.
    return label, None


def _section_match_to_compact(compact: str) -> str:
    section_match = VISIBLE_INTERNAL_SECTION_RE.match(compact)
    if not section_match:
        return compact
    section_name = section_match.group(1).strip().capitalize()
    remainder = (section_match.group(2) or '').strip()
    return f'{section_name}: {remainder}' if remainder else f'{section_name}:'


_TASK_TRACKING_BLOCK_PREFIXES: tuple[str, ...] = (
    'task_tracker:',
    '**task_tracker**:',
    'allowed statuses:',
    '**syncing**:',
    '**completion (critical)**:',
)


def sanitize_visible_transcript_text(text: str) -> str:
    """Remove internal prompt scaffolding and protocol chatter."""
    stripped = redact_internal_result_markers(
        redact_task_list_json_blobs(
            redact_streamed_tool_call_markers((text or '').strip())
        )
    )
    if not stripped:
        return ''

    had_task_tracking_block = '<TASK_TRACKING>' in stripped.upper()
    stripped = VISIBLE_INTERNAL_BLOCK_TAG_RE.sub('', stripped)
    lines_out: list[str] = []
    previous_blank = False
    for raw_line in stripped.splitlines():
        line = raw_line.rstrip()
        compact = line.strip()
        if not compact:
            if lines_out and not previous_blank:
                lines_out.append('')
            previous_blank = True
            continue

        if _should_skip_visible_line(compact, had_task_tracking_block):
            continue

        compact = _section_match_to_compact(compact)
        lines_out.append(compact)
        previous_blank = False

    return '\n'.join(lines_out).strip()


def _should_skip_visible_line(compact: str, had_task_tracking_block: bool) -> bool:
    if VISIBLE_SUPPRESSED_LINE_RE.match(compact):
        return True
    if not had_task_tracking_block:
        return False
    lower_compact = compact.lower()
    return any(
        lower_compact.startswith(prefix)
        for prefix in _TASK_TRACKING_BLOCK_PREFIXES
    )


def reasoning_lines_skip_already_committed(
    prev: list[str] | None, new: list[str]
) -> list[str]:
    """Drop leading lines already printed in the previous reasoning snapshot."""
    if not new:
        return []
    if not prev:
        return new
    n = min(len(prev), len(new))
    i = 0
    while i < n and prev[i] == new[i]:
        i += 1
    return new[i:]


def contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    """Return True when any pattern appears in *text* (already lower-cased)."""
    return any(pattern in text for pattern in patterns)


def pty_output_transcript_caption(
    *,
    session_id: str,
    n_lines: int,
    truncated: bool,
    has_output: bool,
    has_new_output: bool | None = None,
) -> str:
    """One line for the transcript: session and line count."""
    parts: list[str] = [f'{ACTIVITY_CARD_TITLE_TERMINAL.lower()} output']
    if session_id:
        parts.append(session_id)
    if has_output and n_lines:
        parts.append(f'{n_lines} line{"s" if n_lines != 1 else ""}')
    if truncated:
        parts.append('truncated')
    if has_new_output is False:
        parts.append('no new bytes since last read')
    return ' · '.join(parts)


def strip_pty_echo(text: str, sent_cmd: str) -> str:
    """Remove PTY character-echo lines from a terminal delta."""
    cmd = sent_cmd.strip().rstrip('\r\n')
    if not cmd or not text:
        return text
    lines = text.split('\n')
    filtered = [ln for ln in lines if not ln.rstrip().endswith(cmd)]
    if len(filtered) < len(lines):
        result = '\n'.join(filtered).strip()
        return result if result else text
    return text


def wrap_panel_text_block(text: str, *, wrap_width: int | None) -> str:
    """Hard-wrap lines so long API / exception strings stay inside the panel."""
    if wrap_width is None or not text:
        return text
    lines_out: list[str] = []
    for raw in text.splitlines():
        if not raw:
            lines_out.append('')
            continue
        chunk = textwrap.wrap(
            raw,
            width=wrap_width,
            replace_whitespace=False,
            drop_whitespace=False,
        )
        lines_out.extend(chunk or [''])
    return '\n'.join(lines_out)


def error_panel_text_wrap_width(console_width: int | None) -> int | None:
    """Character width for wrapped body lines inside a transcript error panel."""
    if console_width is None:
        return None
    area = max(20, console_width - TRANSCRIPT_LEFT_INSET - TRANSCRIPT_RIGHT_INSET)
    inner = area - 2 - 4
    return max(16, inner)


def error_panel_outer_width(console_width: int | None) -> int | None:
    """Width of the Panel box aligned with the framed transcript column."""
    if console_width is None:
        return None
    return max(20, console_width - TRANSCRIPT_LEFT_INSET - TRANSCRIPT_RIGHT_INSET)


def truncate_activity_detail(text: str, limit: int) -> str:
    """Collapse whitespace and cap verbose tool details for activity cards."""
    collapsed = ' '.join((text or '').split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(limit - 1, 0)].rstrip() + '…'
