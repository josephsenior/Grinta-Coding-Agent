"""Activity card data structures."""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.cli.tool_display.renderers.badge import badge_for_tool_name
from backend.cli.theme import (
    NAVY_BRAND,
    NAVY_ERROR,
    NAVY_READY,
    NAVY_TEXT_MUTED,
    NAVY_WAITING,
)

@dataclass
class ActivityLine:
    """A single line in an activity card."""

    text: str
    style: str = ''
    indent: int = 0


@dataclass
class ActivityCard:
    """A structured activity card for rendering.

    This data structure can be rendered to both Rich (CLI) and Textual (TUI).
    """

    verb: str
    detail: str
    badge_category: str = 'tool'
    title: str | None = None
    secondary: str | None = None
    secondary_kind: str = 'neutral'
    extra_lines: list[ActivityLine] = field(default_factory=list)
    meta_lines: list[str] = field(default_factory=list)
    is_collapsible: bool = False
    start_collapsed: bool = False
    syntax_language: str | None = None

    _KIND_COLORS = {
        'ok': NAVY_READY,
        'err': NAVY_ERROR,
        'warn': NAVY_WAITING,
        'neutral': NAVY_TEXT_MUTED,
    }

    def to_rich_lines(self) -> list[str]:
        """Convert to Rich markup lines for CLI rendering."""
        lines: list[str] = []

        badge = badge_for_tool_name(self.badge_category)
        badge_render = badge.render()
        verb_style = f'bold {NAVY_BRAND}'
        header = f'{badge_render} [{verb_style}]{self.verb}[/] {self.detail}'

        if self.title:
            lines.append(f'[dim]{self.title}[/dim]')

        lines.append(header)

        if self.secondary:
            color = self._KIND_COLORS.get(self.secondary_kind, NAVY_TEXT_MUTED)
            icon = {
                'ok': '[bold #54efae]✓[/]',
                'err': '[bold #fd8383]✗[/]',
                'warn': '[bold #f6ff8f]⚠[/]',
                'neutral': '[dim #969aad]•[/]',
            }.get(self.secondary_kind, '•')
            lines.append(f'    {icon} [{color}]{self.secondary}[/]')

        for extra in self.extra_lines:
            indent = '  ' * extra.indent
            style = extra.style if extra.style else NAVY_TEXT_MUTED
            lines.append(f'{indent}[{style}]{extra.text}[/]')

        return lines

    def to_tui_markup(self) -> str:
        """Convert to Textual markup for TUI rendering."""
        return '\n'.join(self.to_rich_lines())

