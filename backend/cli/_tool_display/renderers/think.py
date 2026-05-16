"""Think/message renderers for agent reasoning and communication."""

from __future__ import annotations

from rich.markup import escape as markup_escape

from backend.cli._tool_display.renderers.badge import badge_for_tool_name
from backend.cli.theme import (
    CLR_SECONDARY,
    CLR_THOUGHT_BODY,
)
from backend.cli.transcript import format_activity_primary


def render_think(thought: str, source_tool: str = '') -> list[str]:
    """Render internal agent reasoning as structured extra lines.

    Returns badge + primary line with 'Thinking:' prefix + continuation lines.
    """
    lines: list[str] = []

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
            text = para.replace('\n', ' ').strip()
            if len(text) > 100:
                text = text[:97] + '…'
            if text:
                # Escape text to prevent MarkupError from unescaped brackets
                escaped_text = markup_escape(text)
                lines.append(f"  [{CLR_THOUGHT_BODY}]{escaped_text}[/{CLR_THOUGHT_BODY}]")

    return lines


def render_message(content: str) -> list[str]:
    """Render an assistant message as structured extra lines.

    Returns badge + primary line + continuation lines.
    """
    lines: list[str] = []

    badge = badge_for_tool_name('message')
    lines.append(badge.render())

    content = content.strip()

    paragraphs = content.split('\n\n')
    first_para = paragraphs[0].replace('\n', ' ').strip()
    if len(first_para) > 100:
        first_para = first_para[:97] + '…'

    lines.append(format_activity_primary('Said', first_para))

    if len(paragraphs) > 1:
        for para in paragraphs[1:4]:
            text = para.replace('\n', ' ').strip()
            if len(text) > 100:
                text = text[:97] + '…'
            if text:
                # Escape text to prevent MarkupError from unescaped brackets
                escaped_text = markup_escape(text)
                lines.append(f"  [{CLR_SECONDARY}]{escaped_text}[/{CLR_SECONDARY}]")

    return lines