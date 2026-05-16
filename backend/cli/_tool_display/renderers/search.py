"""Search code renderer with results tree display.

Shows search results grouped by file with match previews.
"""

from __future__ import annotations

import re

from rich.markup import escape as markup_escape

from backend.cli._tool_display.renderers.badge import badge_for_tool_name
from backend.cli.theme import (
    CLR_BRAND_HUE,
    CLR_SECONDARY,
    CLR_STATUS_OK,
    CLR_DETAIL,
)
from backend.cli.transcript import format_activity_primary

_LINE_NUM_RE = re.compile(r'^([^:]+):(\d+)(?::(.*))?$')


def render_search_results(
    output: str,
    query: str = '',
    max_files: int = 5,
    max_lines_per_file: int = 3,
) -> list[str]:
    """Parse and render ripgrep-style search output as extra lines.

    Format: filepath:line:content
    Returns Rich markup lines (no badge/verb — just the file+match rows).
    """
    lines: list[str] = []

    raw_lines = [l for l in output.splitlines() if l.strip() and not l.startswith('Error running')]

    if not raw_lines:
        return []

    grouped: dict[str, list[tuple[int, str]]] = {}

    for line in raw_lines:
        m = _LINE_NUM_RE.match(line)
        if m:
            filepath = m.group(1)
            lineno = int(m.group(2))
            content = m.group(3) or ''
            if filepath not in grouped:
                grouped[filepath] = []
            grouped[filepath].append((lineno, content))
        else:
            grouped['output'] = grouped.get('output', [])
            grouped['output'].append((0, line))

    if 'output' in grouped:
        for _, content in grouped['output'][:5]:
            # Escape content to prevent MarkupError
            escaped = markup_escape(content)
            lines.append(f"  [dim]{escaped}[/dim]")
        return lines

    sorted_files = sorted(grouped.items(), key=lambda x: len(x[1]), reverse=True)

    for filepath, matches in sorted_files[:max_files]:
        match_count = len(matches)
        # Escape filepath to prevent MarkupError
        escaped_path = markup_escape(filepath)
        lines.append(f"  [{CLR_BRAND_HUE} bold]{escaped_path}[/{CLR_BRAND_HUE} bold]  [dim]{match_count} matches[/dim]")

        for lineno, content in matches[:max_lines_per_file]:
            content = content.strip()
            if len(content) > 80:
                content = content[:77] + '…'

            if content:
                highlighted = _highlight_query(content, query)
                lines.append(f"    [{CLR_SECONDARY}]{lineno:>4}[/{CLR_SECONDARY}]  {highlighted}")

        if match_count > max_lines_per_file:
            lines.append(f"    [dim]... {match_count - max_lines_per_file} more[/dim]")

    if len(grouped) > max_files:
        remaining_files = len(grouped) - max_files
        remaining_matches = sum(len(m) for _, m in list(grouped.items())[max_files:])
        lines.append(f"  [dim]... {remaining_files} more files, {remaining_matches} matches[/dim]")

    return lines


def _highlight_query(text: str, query: str) -> str:
    """Highlight query matches in text."""
    if not query or not text:
        return text

    escaped = re.escape(query)
    return re.sub(f'({escaped})', r'[/][bold #f6ff8f]\1[/][dim]', text, flags=re.IGNORECASE)


def render_search_summary(
    match_count: int,
    file_count: int,
    query: str = '',
    duration: str = '',
) -> list[str]:
    """Render just the summary line for search results."""
    lines: list[str] = []

    detail = f"{match_count} matches"
    if file_count > 0:
        detail += f" in {file_count} files"
    if query:
        # Escape query to prevent MarkupError
        escaped_query = markup_escape(query)
        detail += f"  [dim]·  \"{escaped_query}\"[/dim]"

    lines.append(format_activity_primary('Searched', detail))

    if duration:
        lines.append(f"  [dim]{duration}[/dim]")

    return lines