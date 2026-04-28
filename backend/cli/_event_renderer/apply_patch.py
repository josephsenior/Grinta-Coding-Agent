"""Apply-patch activity helpers for the event renderer."""

from __future__ import annotations

import re

from rich.text import Text

from backend.cli._event_renderer.constants import (
    APPLY_PATCH_STATS_RE,
    APPLY_PATCH_TITLE,
    CMD_SUMMARY_NOISE_PATTERNS,
    CMD_SUMMARY_PRIORITY_PATTERNS,
)
from backend.cli._event_renderer.text_utils import truncate_activity_detail
from backend.cli.transcript import format_activity_secondary


def summarize_cmd_failure(content: str) -> str:
    """Pick the most actionable single-line failure summary."""
    lines = [line.strip() for line in (content or '').splitlines() if line.strip()]
    if not lines:
        return ''

    filtered = [
        line
        for line in lines
        if not any(noise in line.lower() for noise in CMD_SUMMARY_NOISE_PATTERNS)
    ]
    candidates = filtered or lines
    matched = _first_priority_match(candidates)
    if matched is not None:
        return matched
    return candidates[-1][:160]


def _first_priority_match(candidates: list[str]) -> str | None:
    for pattern in CMD_SUMMARY_PRIORITY_PATTERNS:
        for line in reversed(candidates):
            if pattern.search(line):
                return line[:160]
    return None


def is_apply_patch_activity(title: str | None, label: str | None) -> bool:
    """Return True when the internal shell card corresponds to apply_patch."""
    title_text = (title or '').strip().lower()
    label_text = (label or '').strip().lower()
    return (
        title_text == APPLY_PATCH_TITLE
        or 'applying patch' in label_text
        or 'validating patch' in label_text
    )


_PATCH_HEADER_PREFIXES: tuple[str, ...] = (
    'diff --git ',
    'index ',
    '+++ ',
    '--- ',
    '@@ ',
    'Binary files ',
    '\\ No newline at end of file',
)


def _is_patch_header_line(line: str) -> bool:
    return any(line.startswith(prefix) for prefix in _PATCH_HEADER_PREFIXES)


def extract_apply_patch_delta(content: str) -> tuple[int | None, int | None]:
    """Extract patch +/- line counts from stats marker or raw unified diff text."""
    match = APPLY_PATCH_STATS_RE.search(content or '')
    if match:
        return int(match.group(1)), int(match.group(2))

    added = 0
    removed = 0
    saw_patch_lines = False
    for line in (content or '').splitlines():
        if _is_patch_header_line(line):
            continue
        if line.startswith('+'):
            added += 1
            saw_patch_lines = True
        elif line.startswith('-'):
            removed += 1
            saw_patch_lines = True

    if not saw_patch_lines:
        return None, None
    return added, removed


def _apply_patch_success_line(added: int | None, removed: int | None) -> Text:
    line = format_activity_secondary('succeeded', kind='ok')
    if added is not None and removed is not None:
        line.append('  ', style='dim')
        line.append(f'+{added}', style='dim green')
        line.append('  ', style='dim')
        line.append(f'-{removed}', style='dim red')
    return line


_APPLY_PATCH_GUIDANCE_MARKER = '[APPLY_PATCH_GUIDANCE]'


def compact_apply_patch_result(
    *,
    exit_code: int | None,
    label: str,
    content: str,
) -> tuple[str | None, str, list[Text] | None]:
    """Compact result text for apply_patch to reduce transcript clutter."""
    del label  # currently unused; kept for parity with original signature.
    added, removed = extract_apply_patch_delta(content)

    if exit_code == 0:
        return None, 'ok', [_apply_patch_success_line(added, removed)]

    if exit_code is None:
        return 'failed', 'err', None

    if _APPLY_PATCH_GUIDANCE_MARKER in content:
        detail = content.split(_APPLY_PATCH_GUIDANCE_MARKER, 1)[1].strip().splitlines()
        first = detail[0].strip() if detail else ''
        if first:
            return f'failed · {truncate_activity_detail(first, 140)}', 'err', None

    if summary := summarize_cmd_failure(content):
        return f'failed · {summary}', 'err', None

    return f'failed · exit {exit_code}', 'err', None


__all__ = [
    'compact_apply_patch_result',
    'extract_apply_patch_delta',
    'is_apply_patch_activity',
    'summarize_cmd_failure',
]
