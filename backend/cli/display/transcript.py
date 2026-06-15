"""Structured transcript lines for CLI tool invocations.

Activity rows use a **primary** line (verb + short detail) and an optional **secondary**
line in dim styles (results, stats) to reduce clutter versus separate ``>`` / outcome rows.
"""

from __future__ import annotations

import re
from typing import Any

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

from backend.cli.layout_tokens import (
    ACTIVITY_CARD_TITLE_STYLE,
    CALLOUT_PANEL_PADDING,
)
from backend.cli.path_links import linkify_plain
from backend.cli.theme import (
    CLR_CARD_BORDER,
    CLR_DIFF_ADD,
    CLR_DIFF_REM,
    CLR_ERR_BODY,
    CLR_ERR_ICON,
    CLR_INFO_BODY,
    CLR_INFO_ICON,
    CLR_LIVE_PANEL_BORDER,
    CLR_OK_BODY,
    CLR_OK_ICON,
    CLR_ORIENT_GUTTER,
    CLR_REASONING_COMMITTED,
    CLR_SHELL_BORDER,
    CLR_SHELL_OUTPUT,
    CLR_STATUS_WARN,
    CLR_TURN_RULE,
    CLR_VERB,
    CLR_WARN_BODY,
    CLR_WARN_ICON,
    MARK_WARN,
    STYLE_DIM,
    STYLE_EMPTY,
    mark_err,
    mark_info,
    mark_ok,
)

# Stripped from user-visible transcripts (still present on stored observations for the LLM).
_APP_RESULT_VALIDATION_RE = re.compile(
    r'\s*<APP_RESULT_VALIDATION\b[^>]*>.*?(?:</APP_RESULT_VALIDATION>|\Z)',
    re.DOTALL | re.IGNORECASE,
)

# Indentation warnings are agent-facing guidance — hide from user transcript.
_INDENTATION_WARNINGS_RE = re.compile(
    r'\n\n\[INDENTATION WARNINGS\].*?(?=\n\n|\Z)',
    re.DOTALL,
)

_PSEUDO_XML_FUNCTION_RE = re.compile(
    r'\s*<function(?:=[^>\s]+|\s+name\s*=\s*["\']?[^>"\']+["\']?)[^>]*>'
    r'.*?(?:</function>|\Z)',
    re.DOTALL | re.IGNORECASE,
)

_FUNCTION_CALLS_RE = re.compile(
    r'\s*<function_calls\b[^>]*>.*?(?:</function_calls>|\Z)',
    re.DOTALL | re.IGNORECASE,
)


def strip_tool_result_validation_annotations(text: str) -> str:
    """Remove internal tool-validation tags; keeps scrollback readable."""
    return _APP_RESULT_VALIDATION_RE.sub('', text or '').strip()


def strip_pseudo_xml_function_calls(text: str) -> str:
    """Remove raw pseudo-XML function calls from user-visible streaming text."""
    stripped = _FUNCTION_CALLS_RE.sub('', text or '')
    return _PSEUDO_XML_FUNCTION_RE.sub('', stripped).strip()


def strip_indentation_warnings(text: str) -> str:
    """Remove agent-facing indentation warnings from user-visible output."""
    return _INDENTATION_WARNINGS_RE.sub('', text or '')


_GROUND_PREFIX = '    > '
# Primary row layout with tighter indent and better visual hierarchy.
_ACTIVITY_PRIMARY_INDENT = ' '
_ACTIVITY_GAP = '  '
_ACTIVITY_SECONDARY_INDENT = '    '
_ACTIVITY_RESULT_INDENT = '      '


def format_activity_primary(verb: str, detail: str | Text) -> Text:
    """Bold verb + detail on one line."""
    line = Text()
    line.append((verb or 'Did').strip(), style=CLR_VERB)
    if isinstance(detail, Text):
        if detail.plain.strip():
            line.append(_ACTIVITY_GAP, style=STYLE_EMPTY)
            line.append(detail)
        return line
    d = (detail or '').strip()
    if d:
        line.append(_ACTIVITY_GAP, style=STYLE_EMPTY)
        line.append_text(linkify_plain(d, link_files=True, link_urls=False))
    return line


def format_activity_secondary(message: str, *, kind: str = 'neutral') -> Text:
    """Continuation row for inline stats and previews inside activity cards."""
    styles = {
        'ok': CLR_OK_BODY,
        'err': CLR_ERR_BODY,
        'warn': CLR_WARN_BODY,
        'neutral': CLR_INFO_BODY,
    }
    body_style = styles.get(kind, styles['neutral'])
    line = Text(_ACTIVITY_SECONDARY_INDENT, style=STYLE_EMPTY)
    line.append_text(
        linkify_plain(
            (message or '').strip(),
            plain_style=body_style,
            link_files=True,
            link_urls=False,
        )
    )
    return line


def format_activity_result_secondary(message: str, *, kind: str = 'neutral') -> Text:
    """Continuation row for user-visible results within an activity card.

    Prefixed with a colored status icon: ``✓`` (ok), ``✗`` (err), ``•`` (neutral).
    """
    styles: dict[str, tuple[str, str, str]] = {
        'ok': (mark_ok(), CLR_OK_ICON, CLR_OK_BODY),
        'err': (mark_err(), CLR_ERR_ICON, CLR_ERR_BODY),
        'neutral': (mark_info(), CLR_INFO_ICON, CLR_INFO_BODY),
    }
    icon, icon_style, text_style = styles.get(kind, styles['neutral'])
    line = Text(_ACTIVITY_RESULT_INDENT, style=STYLE_EMPTY)
    line.append(f'{icon} ', style=icon_style)
    line.append_text(
        linkify_plain(
            (message or '').strip(),
            plain_style=text_style,
            link_files=True,
            link_urls=False,
        )
    )
    return line


def format_activity_delta_secondary(
    *,
    added: int | None = None,
    removed: int | None = None,
    added_label: str = 'lines',
    removed_label: str = 'lines',
) -> Text | None:
    """Compact colored +/- summary line for file and edit results."""
    if not added and not removed:
        return None

    line = Text(_ACTIVITY_RESULT_INDENT, style=STYLE_EMPTY)
    wrote = False
    if added:
        line.append(f'+{added:,} {added_label}', style=f'dim {CLR_DIFF_ADD}')
        wrote = True
    if removed:
        if wrote:
            line.append('  ', style=STYLE_DIM)
        line.append(f'-{removed:,} {removed_label}', style=f'dim {CLR_DIFF_REM}')
    return line


def format_activity_validation_callout(message: str) -> Panel:
    """Bordered callout for post-edit syntax / lint feedback (distinct from shell errors)."""
    body = Text()
    body.append(_ACTIVITY_RESULT_INDENT, style=STYLE_EMPTY)
    body.append(f'{MARK_WARN} ', style=CLR_WARN_ICON)
    body.append('Validation', style=f'bold {CLR_WARN_BODY}')
    body.append(' — ', style=STYLE_DIM)
    body.append_text(
        linkify_plain(
            (message or '').strip(),
            plain_style=CLR_WARN_BODY,
            link_files=True,
            link_urls=False,
        )
    )
    return Panel(
        body,
        border_style=CLR_STATUS_WARN,
        box=box.ROUNDED,
        padding=(0, 1),
    )


def format_shell_output_block(
    lines: list[str], *, kind: str = 'neutral'
) -> Panel | Group:
    """Shell command output wrapped in a subtle panel with left border.

    Uses a minimal box with a dim left border to distinguish shell output
    from other transcript content without being overwhelming.
    """
    if not lines:
        return Group()

    body_lines: list[Text] = []
    for line in lines:
        row = Text()
        row.append('│ ', style=CLR_SHELL_BORDER)
        row.append(line, style=CLR_SHELL_OUTPUT)
        body_lines.append(row)

    return Panel(
        Group(*body_lines),
        border_style=CLR_SHELL_BORDER,
        box=box.MINIMAL,
        padding=(0, 0),
    )


def format_activity_block(
    verb: str,
    detail: str | Text,
    *,
    secondary: str | None = None,
    secondary_kind: str = 'neutral',
    result_message: str | None = None,
    result_kind: str = 'neutral',
    extra_lines: list[Any] | None = None,
    title: str | None = None,
    badge_label: str | None = None,
) -> Any:
    """Primary row plus optional secondary rows, wrapped in a bordered card panel.

    When ``badge_label`` or ``title`` is provided the output is wrapped in a
    ``Panel`` whose border matches ``CLR_CARD_BORDER`` (matching ``shell.py``
    and the TUI ``ActivityCard`` widget).  Plain activity rows (no badge, no
    title) are returned as a bare ``Group`` with no border.
    """
    parts: list[Any] = [format_activity_primary(verb, detail)]
    if secondary:
        parts.append(format_activity_secondary(secondary, kind=secondary_kind))
    if result_message is not None:
        parts.append(format_activity_result_secondary(result_message, kind=result_kind))
    if extra_lines:
        parts.extend(extra_lines)
    content = Group(*parts)

    if badge_label:
        from backend.cli.tool_display.renderers.badge import badge_for_tool_name

        badge = badge_for_tool_name(badge_label)
        panel_title = Text(badge.label, style=f'bold {badge.label_color}')
        return Panel(
            content,
            title=panel_title,
            title_align='left',
            border_style=CLR_CARD_BORDER,
            padding=(0, 2),
        )

    if title:
        panel_title = Text(title.strip(), style=ACTIVITY_CARD_TITLE_STYLE)
        return Panel(
            content,
            title=panel_title,
            title_align='left',
            border_style=CLR_CARD_BORDER,
            padding=(0, 2),
        )

    return content


def format_activity_turn_header() -> RenderableType:
    """Section heading before the first tool/shell row each agent turn."""
    from rich.rule import Rule

    return Rule(style=f'dim {CLR_TURN_RULE}')


_REASONING_SENTENCE_ENDERS = ('.', '!', '?', ':', ';', '"', "'", ')', ']', '…')


def format_reasoning_snapshot(lines: list[str]) -> Group:
    """Transcript block for reasoning that finished (after the live panel closes)."""
    cleaned = [ln.strip() for ln in lines if (ln or '').strip()]
    if not cleaned:
        return Group()
    last = cleaned[-1]
    if last and not last.endswith(_REASONING_SENTENCE_ENDERS):
        cleaned[-1] = f'{last}…'
    return Group(
        *[
            Text(f'{_ACTIVITY_RESULT_INDENT}{line}', style=CLR_REASONING_COMMITTED)
            for line in cleaned
        ]
    )


def format_activity_shell_block(
    verb: str,
    detail: str | Text,
    *,
    secondary: str | None = None,
    secondary_kind: str = 'neutral',
    result_message: str | None = None,
    result_kind: str = 'ok',
    extra_lines: list[Any] | None = None,
    title: str | None = None,
    badge_label: str | None = None,
) -> Any:
    """Shell command activity block — same visual style as other tool cards.

    The badge label is forwarded to :func:`format_activity_block` which uses it
    as the ``Panel`` title (rather than embedding it as a text line).
    """
    if badge_label:
        title = title or badge_label
    return format_activity_block(
        verb,
        detail,
        secondary=secondary,
        secondary_kind=secondary_kind,
        result_message=result_message,
        result_kind=result_kind,
        extra_lines=extra_lines,
        title=title,
        badge_label=badge_label,
    )


def format_shell_result_secondary(message: str, *, kind: str = 'ok') -> Text:
    """Alias for format_activity_result_secondary — kept for backward compatibility."""
    return format_activity_result_secondary(message or 'done', kind=kind)


def format_callout_panel(
    title: str,
    body: Any,
    *,
    accent_style: str = 'dim',
    padding: tuple[int, int] | None = None,
) -> Panel:
    """Reusable compact panel for CLI callouts, questions, and live sections."""
    panel_title = Text((title or 'Notice').strip(), style=f'{accent_style} bold')
    return Panel(
        body,
        title=panel_title,
        title_align='left',
        border_style=accent_style,
        box=box.ROUNDED,
        padding=padding if padding is not None else CALLOUT_PANEL_PADDING,
    )


def format_live_panel(
    title: str,
    body: Any,
    *,
    accent_style: str,
    padding: tuple[int, int] | None = None,
) -> Panel:
    """Chrome for the Rich ``Live`` block: minimal frame, subdued border."""
    panel_title = Text((title or '').strip(), style=f'bold {accent_style}')
    return Panel(
        body,
        title=panel_title,
        title_align='left',
        border_style=CLR_LIVE_PANEL_BORDER,
        box=box.MINIMAL,
        padding=padding if padding is not None else (0, 1),
    )


def format_ground_truth_tool_line(label: str) -> Text:
    """One structured transcript row for a tool invocation (ASCII prefix, no emoji)."""
    line = Text()
    line.append(_GROUND_PREFIX, style=STYLE_DIM)
    line.append((label or '').strip(), style=STYLE_EMPTY)
    return line


# ── Orient tool flat-line rendering ──────────────────────────────────────────
# Line anatomy: │ [icon] [verb 9ch] [target — flex, ellipsis-left] · [result — right-aligned, dim]
# One gutter color for all orient tools (CLR_ORIENT_GUTTER), no border, no expansion.

_ORIENT_RESULT_WIDTH = 22  # fixed-width column for result metrics
_ORIENT_VERB_WIDTH = 10  # fixed-width for verb (9ch + space)


def format_orient_line(
    icon: str,
    verb: str,
    target: str,
    result: str,
    *,
    result_style: str = STYLE_DIM,
) -> Text:
    """Flat single-line render for orient tools.

    Layout: ``│ [icon] [verb 9ch] [target — flex, ellipsis-left] · [result — right-aligned, dim]``
    All orient tools share one gutter color (``CLR_ORIENT_GUTTER``).
    """
    line = Text()
    # Gutter pipe
    line.append('\u2502 ', style=CLR_ORIENT_GUTTER)
    # Icon + verb in orient gutter color
    verb_display = (verb or '').ljust(_ORIENT_VERB_WIDTH)[:_ORIENT_VERB_WIDTH]
    if icon:
        line.append(f'{icon} ', style=CLR_ORIENT_GUTTER)
    line.append(verb_display, style=CLR_ORIENT_GUTTER)
    # Target (flex, left-ellipsis)
    target_str = (target or '').strip()
    if target_str:
        line.append(target_str, style=STYLE_EMPTY)
    # Dot separator
    line.append(' \u00b7 ', style=STYLE_DIM)
    # Result (right-aligned, fixed-width, dim)
    result_display = (result or '').rjust(_ORIENT_RESULT_WIDTH)[:_ORIENT_RESULT_WIDTH]
    line.append(result_display, style=result_style)
    return line


def format_orient_line_raw(
    icon: str,
    verb: str,
    target: str,
    result: str,
) -> Text:
    """Orient line for zero/empty states — dim styling, no warning color."""
    return format_orient_line(icon, verb, target, result, result_style=STYLE_DIM)


def format_orient_burst_header(area: str, count: int) -> Text:
    """Header for a burst of ≥3 consecutive orient lines.

    Renders as: ``Exploring <area> · N lookups`` in dim orient gutter color.
    """
    line = Text()
    line.append('  ▾ ', style=CLR_ORIENT_GUTTER)
    line.append(f'Exploring {area}', style=f'dim {CLR_ORIENT_GUTTER}')
    line.append(f' · {count} lookups', style=STYLE_DIM)
    return line
