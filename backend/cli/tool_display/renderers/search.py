"""Search code renderer with results tree display.

Shows search results grouped by file with match previews.
"""

from __future__ import annotations

import re
from typing import Any

from rich.markup import escape as markup_escape

from backend.cli.theme import (
    CLR_BRAND_HUE,
    CLR_SECONDARY,
)
from backend.cli.display.transcript import format_activity_primary

_LINE_NUM_RE = re.compile(r'^([^:]+):(\d+)(?::(.*))?$')


def _filter_raw_lines(output: str) -> list[str]:
    return [
        line
        for line in output.splitlines()
        if line.strip() and not line.startswith('Error running')
    ]


def _add_to_grouped(
    grouped: dict[str, list[tuple[int, str]]],
    line: str,
) -> None:
    m = _LINE_NUM_RE.match(line)
    if m:
        filepath = m.group(1)
        lineno = int(m.group(2))
        content = m.group(3) or ''
        if filepath not in grouped:
            grouped[filepath] = []
        grouped[filepath].append((lineno, content))
    else:
        grouped['output'] = grouped.get('output', [])  # type: ignore[unreachable]
        grouped['output'].append((0, line))


def _parse_search_lines(
    output: str,
) -> dict[str, list[tuple[int, str]]]:
    raw_lines = _filter_raw_lines(output)
    if not raw_lines:
        return {}
    grouped: dict[str, list[tuple[int, str]]] = {}
    for line in raw_lines:
        _add_to_grouped(grouped, line)
    return grouped


def _render_output_group(grouped: dict[str, list[tuple[int, str]]]) -> list[Any]:
    lines: list[Any] = []
    for _, content in grouped['output'][:5]:
        escaped = markup_escape(content)
        lines.append(f'  [dim]{escaped}[/dim]')
    return lines


def _render_file_matches(
    matches: list[tuple[int, str]],
    query: str,
    max_lines_per_file: int,
) -> list[Any]:
    lines: list[Any] = []
    for lineno, content in matches[:max_lines_per_file]:
        content = content.strip()
        if len(content) > 80:
            content = content[:77] + '…'
        if content:
            highlighted = _highlight_query(content, query)
            lines.append(
                f'    [{CLR_SECONDARY}]{lineno:>4}[/{CLR_SECONDARY}]  {highlighted}'
            )
    match_count = len(matches)
    if match_count > max_lines_per_file:
        lines.append(f'    [dim]... {match_count - max_lines_per_file} more[/dim]')
    return lines


def _render_file_groups(
    grouped: dict[str, list[tuple[int, str]]],
    query: str,
    max_files: int,
    max_lines_per_file: int,
) -> list[Any]:
    lines: list[Any] = []
    sorted_files = sorted(grouped.items(), key=lambda x: len(x[1]), reverse=True)
    for filepath, matches in sorted_files[:max_files]:
        match_count = len(matches)
        escaped_path = markup_escape(filepath)
        lines.append(
            f'  [{CLR_BRAND_HUE} bold]{escaped_path}[/{CLR_BRAND_HUE} bold]  [dim]{match_count} matches[/dim]'
        )
        lines.extend(_render_file_matches(matches, query, max_lines_per_file))
    if len(grouped) > max_files:
        remaining_files = len(grouped) - max_files
        remaining_matches = sum(len(m) for _, m in list(grouped.items())[max_files:])
        lines.append(
            f'  [dim]... {remaining_files} more files, {remaining_matches} matches[/dim]'
        )
    return lines


def render_search_results(
    output: str,
    query: str = '',
    max_files: int = 5,
    max_lines_per_file: int = 3,
) -> list[Any]:
    """Parse and render ripgrep-style search output as extra lines.

    Format: filepath:line:content
    Returns Rich markup lines (no badge/verb — just the file+match rows).
    """
    grouped = _parse_search_lines(output)
    if not grouped:
        return []
    if 'output' in grouped:
        return _render_output_group(grouped)
    return _render_file_groups(grouped, query, max_files, max_lines_per_file)


def _highlight_query(text: str, query: str) -> str:
    """Highlight query matches in text."""
    if not query or not text:
        return text

    escaped = re.escape(query)
    return re.sub(
        f'({escaped})', r'[bold #f6ff8f]\1[/bold #f6ff8f]', text, flags=re.IGNORECASE
    )


def render_search_summary(
    match_count: int,
    file_count: int,
    query: str = '',
    duration: str = '',
) -> list[Any]:
    """Render just the summary line for search results."""
    lines: list[Any] = []

    detail = f'{match_count} matches'
    if file_count > 0:
        detail += f' in {file_count} files'
    if query:
        # Escape query to prevent MarkupError
        escaped_query = markup_escape(query)
        detail += f'  [dim]·  "{escaped_query}"[/dim]'

    lines.append(format_activity_primary('Searched', detail))

    if duration:
        lines.append(f'  [dim]{duration}[/dim]')

    return lines


def extract_file_summary(
    output: str,
    max_files: int = 5,
) -> tuple[int, int, list[tuple[str, int]]]:
    """Extract file-level summary from ripgrep-style search output.

    Returns:
        Tuple of (total_matches, total_files, [(filepath, match_count), ...])
        File list is sorted by match count (descending), limited to max_files.
    """
    raw_lines = [
        line
        for line in output.splitlines()
        if line.strip() and not line.startswith('Error running')
    ]

    if not raw_lines:
        return 0, 0, []

    grouped: dict[str, int] = {}

    for line in raw_lines:
        m = _LINE_NUM_RE.match(line)
        if m:
            filepath = m.group(1)
            grouped[filepath] = grouped.get(filepath, 0) + 1

    if not grouped:
        return 0, 0, []

    total_matches = sum(grouped.values())
    total_files = len(grouped)
    sorted_files = sorted(grouped.items(), key=lambda x: x[1], reverse=True)
    top_files = sorted_files[:max_files]

    return total_matches, total_files, top_files


def render_file_list(
    files: list[tuple[str, int]],
    total_files: int,
    total_matches: int,
) -> list[Any]:
    """Render a compact file list for user display (Option C).

    Format:
      • src/auth.py (12 matches)
      • src/utils.py (8 matches)
      ... 3 more files, 15 matches
    """
    lines: list[Any] = []

    for filepath, count in files:
        escaped_path = markup_escape(filepath)
        lines.append(
            f'  • [{CLR_BRAND_HUE}]{escaped_path}[/{CLR_BRAND_HUE}] [dim]({count} matches)[/dim]'
        )

    if total_files > len(files):
        remaining_files = total_files - len(files)
        remaining_matches = total_matches - sum(c for _, c in files)
        lines.append(
            f'  [dim]... {remaining_files} more files, {remaining_matches} matches[/dim]'
        )

    return lines
