"""Think/message renderers for agent reasoning and communication."""

from __future__ import annotations

from typing import Any

from rich.markup import escape as markup_escape
from rich.text import Text

from backend.cli._tool_display.renderers._syntax import highlight_code_blocks
from backend.cli._tool_display.renderers.badge import badge_for_tool_name
from backend.cli.theme import CLR_SECONDARY, CLR_THOUGHT_BODY
from backend.cli.transcript import format_activity_primary


def render_think(thought: str, source_tool: str = '') -> list[Any]:
    """Render internal agent reasoning as structured extra lines.

    Returns badge + primary line with 'Thinking:' prefix + continuation lines.
    """
    lines: list[Any] = []

    badge = badge_for_tool_name(source_tool or 'think')
    lines.append(badge.render())

    thought = thought.strip()
    paragraphs = thought.split('\n\n')

    first_para = paragraphs[0].replace('\n', ' ').strip()
    if len(first_para) > 100:
        first_para = first_para[:97] + '…'

    # Use 'Thinking:' prefix instead of 'Thought' for consistency with TUI
    lines.append(format_activity_primary('Thinking:', first_para))

    if len(paragraphs) > 1:
        for para in paragraphs[1:4]:
            if not para.strip():
                continue
            # Build continuation lines preserving internal line breaks
            para_lines = [ln.strip() for ln in para.split('\n') if ln.strip()]
            for pl in para_lines[:6]:
                if len(pl) > 100:
                    pl = pl[:97] + '…'
                escaped = markup_escape(pl)
                # Aligned with _ACTIVITY_SECONDARY_INDENT (4 spaces)
                lines.append(f'    [{CLR_THOUGHT_BODY}]{escaped}[/{CLR_THOUGHT_BODY}]')
            if len(para_lines) > 6:
                lines.append(
                    f'    [{CLR_THOUGHT_BODY}]… ({len(para_lines) - 6} more lines)[/{CLR_THOUGHT_BODY}]'
                )

    return lines


def render_message(content: str) -> list[Any]:
    """Render an assistant message as structured extra lines.

    Returns badge + primary line + continuation lines.
    Code blocks (````` `````) are syntax-highlighted when present.
    """
    lines: list[Any] = []

    badge = badge_for_tool_name('message')
    lines.append(badge.render())

    content = content.strip()
    if not content:
        return lines

    if '```' in content:
        highlighted = highlight_code_blocks(content)
        first = highlighted[0]
        if isinstance(first, Text):
            first_text = first.plain.replace('\n', ' ').strip()
            if len(first_text) > 100:
                first_text = first_text[:97] + '\u2026'
            lines.append(format_activity_primary('Said', first_text))
        else:
            lines.append(format_activity_primary('Said', 'Result:'))
            lines.append(first)
        lines.extend(highlighted[1:])
        return lines

    paragraphs = content.split('\n\n')
    first_para = paragraphs[0].replace('\n', ' ').strip()
    if len(first_para) > 100:
        first_para = first_para[:97] + '\u2026'

    lines.append(format_activity_primary('Said', first_para))

    if len(paragraphs) > 1:
        for para in paragraphs[1:4]:
            text = para.replace('\n', ' ').strip()
            if len(text) > 100:
                text = text[:97] + '\u2026'
            if text:
                # Escape text to prevent MarkupError from unescaped brackets
                escaped_text = markup_escape(text)
                lines.append(f'  [{CLR_SECONDARY}]{escaped_text}[/{CLR_SECONDARY}]')

    return lines
