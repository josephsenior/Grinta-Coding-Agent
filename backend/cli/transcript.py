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

from backend.cli.layout_tokens import (
    ACTIVITY_CARD_BORDER_STYLE,
    ACTIVITY_CARD_TITLE_STYLE,
    ACTIVITY_CARD_TITLE_TERMINAL,
    ACTIVITY_PANEL_PADDING,
    ACTIVITY_SECTION_TITLE,
    CALLOUT_PANEL_PADDING,
)
from backend.cli.path_links import linkify_plain
from backend.cli.theme import (
    CLR_DIFF_ADD,
    CLR_DIFF_REM,
    CLR_ERR_BODY,
    CLR_ERR_ICON,
    CLR_INFO_BODY,
    CLR_INFO_ICON,
    CLR_OK_BODY,
    CLR_OK_ICON,
    CLR_REASONING_COMMITTED,
    CLR_STATUS_WARN,
    CLR_TURN_RULE,
    CLR_WARN_BODY,
    CLR_WARN_ICON,
    MARK_ERR,
    MARK_INFO,
    MARK_OK,
    MARK_WARN,
    STYLE_DIM,
    STYLE_EMPTY,
)

# Stripped from user-visible transcripts (still present on stored observations for the LLM).
# Handles well-formed closers and streaming/unclosed fragments (``.*?`` then ``\Z``).
_APP_RESULT_VALIDATION_RE = re.compile(
    r'\s*<APP_RESULT_VALIDATION\b[^>]*>.*?(?:</APP_RESULT_VALIDATION>|\Z)',
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


def format_activity_primary(verb: str, detail: str | Text) -> Text:
    """Bold verb + detail on one line (no ``>`` prefix).

    Plain-string *detail* is linkified for ``file://`` and workspace paths so
    terminals can open them via OSC-8 hyperlinks.
    """
    from backend.cli.theme import CLR_VERB

    line = Text()
    line.append(_ACTIVITY_PRIMARY_INDENT, style=STYLE_EMPTY)
    line.append(
        f'{(verb or "Did").strip():<{_ACTIVITY_VERB_WIDTH}}',
        style=CLR_VERB,
    )
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
    line = Text(_ACTIVITY_SECONDARY_INDENT, style=STYLE_EMPTY)
    styles = {
        'ok': CLR_OK_BODY,
        'err': CLR_ERR_BODY,
        'warn': CLR_WARN_BODY,
        'neutral': CLR_INFO_BODY,
    }
    body_style = styles.get(kind, styles['neutral'])
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
    """Continuation row for user-visible results within an activity card."""
    styles: dict[str, tuple[str, str, str]] = {
        'ok': (MARK_OK, CLR_OK_ICON, CLR_OK_BODY),
        'err': (MARK_ERR, CLR_ERR_ICON, CLR_ERR_BODY),
        'neutral': (MARK_INFO, CLR_INFO_ICON, CLR_INFO_BODY),
    }
    icon, icon_style, text_style = styles.get(kind, styles['neutral'])
    line = Text(_ACTIVITY_SECONDARY_INDENT, style=STYLE_EMPTY)
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

    line = Text(_ACTIVITY_SECONDARY_INDENT, style=STYLE_EMPTY)
    wrote = False
    if added:
        line.append(f'+ {added:,} {added_label}', style=f'dim {CLR_DIFF_ADD}')
        wrote = True
    if removed:
        if wrote:
            line.append('  ', style=STYLE_DIM)
        line.append(f'- {removed:,} {removed_label}', style=f'dim {CLR_DIFF_REM}')
    return line


def format_activity_validation_callout(message: str) -> Panel:
    """Bordered callout for post-edit syntax / lint feedback (distinct from shell errors)."""
    body = Text()
    body.append(_ACTIVITY_SECONDARY_INDENT, style=STYLE_EMPTY)
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
) -> Any:
    """Primary row plus optional secondary rows, optionally prefixed with a title."""
    parts: list[Any] = [format_activity_primary(verb, detail)]
    if secondary:
        parts.append(format_activity_secondary(secondary, kind=secondary_kind))
    if result_message is not None:
        parts.append(format_activity_result_secondary(result_message, kind=result_kind))
    if extra_lines:
        parts.extend(extra_lines)
    content = Group(*parts)
    if title is not None:
        title_line = Text()
        title_line.append('  ', style=STYLE_EMPTY)
        title_line.append((title or '').strip(), style=ACTIVITY_CARD_TITLE_STYLE)
        return Group(title_line, content)
    return content


def format_activity_turn_header() -> Text:
    """Section heading before the first tool/shell row each agent turn."""
    line = Text()
    line.append('  ', style=STYLE_EMPTY)
    line.append(ACTIVITY_SECTION_TITLE, style=CLR_TURN_RULE)
    return line


_REASONING_SENTENCE_ENDERS = ('.', '!', '?', ':', ';', '"', "'", ')', ']', '…')


def format_reasoning_snapshot(lines: list[str]) -> Group:
    """Transcript block for reasoning that finished (after the live panel closes).

    Models frequently emit a few tokens of preamble ("Let me check the file…",
    "I'll build it as a single HTML page…") and then switch to a tool call
    mid-thought. The CLI flushes whatever reasoning has accumulated when the
    action fires, which can leave the last committed line dangling without
    terminal punctuation — reading like a truncation bug.

    To make the UX read as intentional rather than broken, we append a single
    ``…`` to the final line when it doesn't already end in a
    sentence-terminator. The ellipsis is visually consistent with the
    streaming-cursor indicator and signals "the model continued into an
    action" rather than "text was lost".
    """
    cleaned = [ln.strip() for ln in lines if (ln or '').strip()]
    if not cleaned:
        return Group()
    last = cleaned[-1]
    if last and not last.endswith(_REASONING_SENTENCE_ENDERS):
        cleaned[-1] = f'{last}…'
    # Stronger separation from assistant Markdown (default foreground): dimmer
    # blue-gray + italic so internal reasoning never reads as the main reply.
    return Group(*[Text(line, style=CLR_REASONING_COMMITTED) for line in cleaned])


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
) -> Any:
    """Rounded Terminal card — same visual style as other tool cards.

    The default ``title`` is ``Terminal`` so plain shell commands render as
    before. Internal tools (apply_patch, analyze_project_structure, …) carry
    a friendlier title derived from their ``tool_call_metadata.function_name``
    via :func:`backend.cli.tool_call_display.tool_headline`; the renderer
    forwards that title here so the user sees e.g. ``Apply patch`` instead
    of a generic ``Terminal`` header for tool-authored commands.
    """
    return format_activity_block(
        verb,
        detail,
        secondary=secondary,
        secondary_kind=secondary_kind,
        result_message=result_message,
        result_kind=result_kind,
        extra_lines=extra_lines,
        title=title or ACTIVITY_CARD_TITLE_TERMINAL,
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


def format_ground_truth_tool_line(label: str) -> Text:
    """One structured transcript row for a tool invocation (ASCII prefix, no emoji)."""
    line = Text()
    line.append(_GROUND_PREFIX, style=STYLE_DIM)
    line.append((label or '').strip(), style=STYLE_EMPTY)
    return line
