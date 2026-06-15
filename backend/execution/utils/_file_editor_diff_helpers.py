"""Pure diff and context-window helpers for FileEditor.

No instance state — these helpers take raw content strings and return
formatted diff context. Extracted from
``backend.execution.utils.file_editor_ops_mixin`` to keep that module
focused on the ops mixin class.
"""

from __future__ import annotations

import difflib


def _find_changed_ranges(
    old_lines: list[str],
    new_lines: list[str],
) -> list[tuple[int, int]]:
    """Find ranges of changed lines in the new content.

    Returns list of (start, end) tuples for changed regions.
    """
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    changed: list[tuple[int, int]] = []

    for tag, _, _, j1, j2 in matcher.get_opcodes():
        if tag != 'equal' and j2 > j1:
            changed.append((j1, j2))

    return changed


def _merge_ranges_with_context(
    changed_ranges: list[tuple[int, int]],
    total_lines: int,
    context_lines: int,
) -> list[tuple[int, int]]:
    """Merge overlapping changed ranges and add context padding."""
    merged: list[tuple[int, int]] = []

    for start, end in changed_ranges:
        ctx_start = max(0, start - context_lines)
        ctx_end = min(total_lines, end + context_lines)

        if merged and ctx_start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], ctx_end))
        else:
            merged.append((ctx_start, ctx_end))

    return merged


def _format_range_lines(
    new_lines: list[str],
    changed_ranges: list[tuple[int, int]],
    ctx_start: int,
    ctx_end: int,
    total_lines: int,
) -> list[str]:
    """Format lines for a single context range with line numbers and markers."""
    output: list[str] = []

    header = (
        f'Updated file view (lines {ctx_start + 1}-{ctx_end} of {total_lines}):'
        if ctx_start > 0 or ctx_end < total_lines
        else f'Updated file view ({total_lines} lines):'
    )
    output.append(header)

    for i in range(ctx_start, ctx_end):
        line_num = i + 1
        is_changed = any(start <= i < end for start, end in changed_ranges)
        marker = '>>> ' if is_changed else '    '
        line_content = new_lines[i] if i < len(new_lines) else ''
        output.append(f'{marker}{line_num}\t{line_content}')

    return output


def _format_context_window(
    old_content: str,
    new_content: str,
    context_lines: int = 5,
) -> str:
    """Generate a context window showing the edited region with line numbers.

    Uses difflib to find changed lines, then shows a window of context_lines
    before and after each change region. Edited lines are marked with '>>> '.

    Args:
        old_content: Original file content.
        new_content: Updated file content.
        context_lines: Number of context lines before/after changes.

    Returns:
        Formatted string with line numbers and context window.
    """
    old_lines = old_content.splitlines() if old_content else []
    new_lines = new_content.splitlines() if new_content else []

    changed_ranges = _find_changed_ranges(old_lines, new_lines)
    if not changed_ranges:
        return ''

    merged_ranges = _merge_ranges_with_context(
        changed_ranges, len(new_lines), context_lines
    )

    output_parts: list[str] = []
    total_lines = len(new_lines)

    for idx, (ctx_start, ctx_end) in enumerate(merged_ranges):
        if idx > 0:
            output_parts.append('...')
        output_parts.extend(
            _format_range_lines(
                new_lines, changed_ranges, ctx_start, ctx_end, total_lines
            )
        )

    return '\n'.join(output_parts)


def _to_changed_line_spans(
    old_content: str | None, new_content: str | None
) -> list[dict[str, int]]:
    """Return compact 1-based inclusive line spans for changed regions."""
    if old_content is None or new_content is None:
        return []
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()
    spans: list[dict[str, int]] = []
    for start, end in _find_changed_ranges(old_lines, new_lines):
        if end <= start:
            continue
        spans.append({'start_line': start + 1, 'end_line': end})
    return spans
