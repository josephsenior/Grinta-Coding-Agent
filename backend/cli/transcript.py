"""Structured transcript lines for CLI tool invocations.

Activity rows use a **primary** line (verb + short detail) and an optional **secondary**
line in dim styles (results, stats) to reduce clutter versus separate ``>`` / outcome rows.

Legacy ``> label`` helpers remain for tests and any code that still prints a single row.
"""

from __future__ import annotations

import re
from typing import Any

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from backend.cli.layout_tokens import CALLOUT_PANEL_PADDING

# Stripped from user-visible transcripts (still present on stored observations for the LLM).
_APP_RESULT_VALIDATION_RE = re.compile(
    r'\s*<APP_RESULT_VALIDATION\b[^>]*>.*?</APP_RESULT_VALIDATION>',
    re.DOTALL | re.IGNORECASE,
)


def strip_tool_result_validation_annotations(text: str) -> str:
    """Remove internal tool-validation tags; keeps scrollback readable."""
    return _APP_RESULT_VALIDATION_RE.sub('', text or '').strip()

_GROUND_PREFIX = '    > '
# Activity rows use a fixed verb column so details line up across tools.
_ACTIVITY_PRIMARY_INDENT = '  '
_ACTIVITY_VERB_WIDTH = 12
_ACTIVITY_GAP = '  '
_ACTIVITY_SECONDARY_INDENT = (
    _ACTIVITY_PRIMARY_INDENT + (' ' * _ACTIVITY_VERB_WIDTH) + _ACTIVITY_GAP
)


def format_activity_primary(verb: str, detail: str) -> Text:
    """Bold verb + detail on one line (no ``>`` prefix)."""
    line = Text()
    line.append(_ACTIVITY_PRIMARY_INDENT, style='')
    line.append(
        f'{(verb or "Did").strip():<{_ACTIVITY_VERB_WIDTH}}',
        style='bold cyan',
    )
    d = (detail or '').strip()
    if d:
        line.append(_ACTIVITY_GAP, style='')
        line.append(d, style='default')
    return line


def format_activity_secondary(message: str, *, kind: str = 'neutral') -> Text:
    """Dim continuation row (exit status, stats, previews)."""
    line = Text(_ACTIVITY_SECONDARY_INDENT, style='')
    styles = {
        'ok': 'dim green',
        'err': 'dim red',
        'neutral': 'dim bright_black',
    }
    line.append(message, style=styles.get(kind, styles['neutral']))
    return line


def format_activity_result_secondary(message: str, *, kind: str = 'neutral') -> Text:
    """Brighter continuation row for user-visible results and stats."""
    styles = {
        'ok': ('✔', 'bright_green'),
        'err': ('✘', 'bright_red'),
        'neutral': ('•', 'bright_black'),
    }
    icon, color = styles.get(kind, styles['neutral'])
    line = Text(_ACTIVITY_SECONDARY_INDENT, style='')
    line.append(f'{icon} ', style=f'bold {color}')
    line.append((message or '').strip(), style='bold bright_white' if kind != 'neutral' else 'bright_white')
    return line


def format_activity_block(
    verb: str,
    detail: str,
    *,
    secondary: str | None = None,
    secondary_kind: str = 'neutral',
    title: str | None = None,
) -> Any:
    """Primary row plus optional secondary dim row, optionally wrapped in a titled card."""
    parts: list[Text] = [format_activity_primary(verb, detail)]
    if secondary:
        parts.append(format_activity_secondary(secondary, kind=secondary_kind))
    content = Group(*parts)
    if title is not None:
        return Panel(
            content,
            title=title,
            title_align='left',
            border_style='bright_black',
            box=box.ROUNDED,
            padding=(0, 1),
        )
    return content


def format_activity_turn_header() -> Text:
    """One-line marker before the first tool/shell row each agent turn."""
    line = Text()
    line.append('  ', style='')
    line.append('▸', style='bold cyan')
    line.append(' Agent activity', style='bold dim cyan')
    return line


def format_activity_shell_block(
    verb: str,
    detail: str,
    *,
    secondary: str | None = None,
    secondary_kind: str = 'neutral',
    result_message: str | None = None,
    result_kind: str = 'ok',
) -> Any:
    """Rounded Terminal card — delegates to format_activity_block with title='Terminal'."""
    parts: list[Text] = [format_activity_primary(verb, detail)]
    if secondary:
        parts.append(format_activity_secondary(secondary, kind=secondary_kind))
    if result_message is not None:
        parts.append(format_shell_result_secondary(result_message, kind=result_kind))
    return Panel(
        Group(*parts),
        title='Terminal',
        title_align='left',
        border_style='bright_black',
        box=box.ROUNDED,
        padding=(0, 1),
    )


def format_shell_result_secondary(message: str, *, kind: str = 'ok') -> Text:
    """Bright success / failure row inside the Terminal card."""
    styles = {
        'ok': ('✓', 'bold bright_green', 'bold bright_green'),
        'err': ('✗', 'bold bright_red', 'bold bright_red'),
        'neutral': ('•', 'bold bright_black', 'dim'),
    }
    icon, icon_style, text_style = styles.get(kind, styles['neutral'])
    line = Text(_ACTIVITY_SECONDARY_INDENT, style='')
    line.append(f'{icon} ', style=icon_style)
    line.append((message or '').strip() or 'done', style=text_style)
    return line


def format_callout_panel(
    title: str,
    body: Any,
    *,
    accent_style: str = 'bright_black',
) -> Panel:
    """Reusable compact panel for CLI callouts, questions, and live sections."""
    panel_title = Text((title or 'Notice').strip(), style=f'{accent_style} bold')
    return Panel(
        body,
        title=panel_title,
        title_align='left',
        border_style=accent_style,
        box=box.ROUNDED,
        padding=CALLOUT_PANEL_PADDING,
    )


def format_ground_truth_tool_line(label: str) -> Text:
    """One structured transcript row for a tool invocation (ASCII prefix, no emoji)."""
    line = Text()
    line.append(_GROUND_PREFIX, style='bright_black')
    line.append((label or '').strip(), style='')
    return line
