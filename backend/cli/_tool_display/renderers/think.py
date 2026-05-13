"""Think/message renderers for agent reasoning and communication."""

from __future__ import annotations

from backend.cli._tool_display.renderers.badge import badge_for_tool_name
from backend.cli.theme import (
    CLR_SECONDARY,
)
from backend.cli.transcript import format_activity_primary


def render_think(thought: str, source_tool: str = '') -> list[str]:
    """Render internal agent reasoning as structured extra lines.

    Returns badge + primary line + continuation lines (no extra formatting).
    """
    lines: list[str] = []

    badge = badge_for_tool_name(source_tool or 'think')
    lines.append(badge.render())

    thought = thought.strip()
    paragraphs = thought.split('\n\n')

    first_para = paragraphs[0].replace('\n', ' ').strip()
    if len(first_para) > 100:
        first_para = first_para[:97] + '…'

    lines.append(format_activity_primary('Thought', first_para))

    if len(paragraphs) > 1:
        for para in paragraphs[1:4]:
            text = para.replace('\n', ' ').strip()
            if len(text) > 100:
                text = text[:97] + '…'
            if text:
                lines.append(f"  [dim]{text}[/dim]")

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
                lines.append(f"  [{CLR_SECONDARY}]{text}[/{CLR_SECONDARY}]")

    return lines