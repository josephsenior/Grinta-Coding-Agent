"""Activity card widget for the Grinta TUI.

Renders tool calls, shell commands, file operations, and other agent activities
as compact, consistent cards — matching the CLI activity card system but
implemented as native Textual widgets for incremental updates.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from backend.cli._tool_display.renderers.badge import badge_for_tool_name
from backend.cli.theme import (
    NAVY_BRAND,
    NAVY_ERROR,
    NAVY_READY,
    NAVY_TEXT_MUTED,
    NAVY_WAITING,
)


class ActivityCard(Container):
    """A compact activity card showing a tool call or agent action.

    Layout::

        ┌─ Shell ──────────────────────────────┐
        │ ├─Shell─ git status                  │  <- badge + verb + detail
        │     exit 0                           │  <- secondary/result line
        │     On branch main                   │  <- extra content
        └──────────────────────────────────────┘

    Args:
        verb: Action verb (e.g., "Ran", "Read", "Edited", "Created")
        detail: Primary detail (e.g., command, file path)
        badge_category: Tool category for badge lookup (e.g., "shell", "files")
        title: Optional section title shown above the card
        secondary: Optional secondary line (e.g., stats, exit code)
        secondary_kind: Semantic kind for secondary line ("ok", "err", "warn", "neutral")
        extra_content: Additional content lines below the card
        collapsed: Whether to start collapsed (for verbose content)
    """

    DEFAULT_CSS = """
    ActivityCard {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
    }
    ActivityCard .card-title {
        width: 100%;
        height: 1;
        color: $text-muted;
        text-style: bold;
    }
    ActivityCard .card-header {
        width: 100%;
        height: auto;
    }
    ActivityCard .card-secondary {
        width: 100%;
        height: auto;
        margin-left: 2;
    }
    ActivityCard .card-extra {
        width: 100%;
        height: auto;
        margin-left: 2;
    }
    ActivityCard .card-extra.-hidden {
        display: none;
    }
    """

    _KIND_COLORS = {
        'ok': NAVY_READY,
        'err': NAVY_ERROR,
        'warn': NAVY_WAITING,
        'neutral': NAVY_TEXT_MUTED,
    }

    def __init__(
        self,
        verb: str,
        detail: str,
        *,
        badge_category: str = 'tool',
        title: str | None = None,
        secondary: str | None = None,
        secondary_kind: str = 'neutral',
        extra_content: str | None = None,
        collapsed: bool = False,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._verb = verb
        self._detail = detail
        self._badge_category = badge_category
        self._title = title
        self._secondary = secondary
        self._secondary_kind = secondary_kind
        self._extra_content = extra_content
        self._collapsed = collapsed

    def _build_header_markup(self) -> str:
        badge = badge_for_tool_name(self._badge_category)
        badge_render = badge.render()
        verb_style = f'bold {NAVY_BRAND}'
        detail_text = self._detail
        return f'{badge_render} [{verb_style}]{self._verb}[/] {detail_text}'

    def _build_secondary_markup(self) -> str:
        if not self._secondary:
            return ''
        color = self._KIND_COLORS.get(self._secondary_kind, NAVY_TEXT_MUTED)
        icon = {
            'ok': '[bold #54efae]✓[/]',
            'err': '[bold #fd8383]✗[/]',
            'warn': '[bold #f6ff8f]⚠[/]',
            'neutral': '[dim #969aad]•[/]',
        }.get(self._secondary_kind, '•')
        return f'    {icon} [{color}]{self._secondary}[/]'

    def compose(self) -> ComposeResult:
        parts: list[str] = []

        if self._title:
            parts.append(f'[dim]{self._title}[/dim]')

        parts.append(self._build_header_markup())

        if self._secondary:
            parts.append(self._build_secondary_markup())

        header_text = '\n'.join(parts)
        yield Static(header_text, classes='card-header', id='header')

        if self._extra_content:
            extra_classes = 'card-extra -hidden' if self._collapsed else 'card-extra'
            yield Static(self._extra_content, classes=extra_classes, id='extra')

    def update_secondary(self, text: str, kind: str = 'neutral') -> None:
        """Update the secondary/result line (e.g., after a command completes)."""
        self._secondary = text
        self._secondary_kind = kind
        header = self.query_one('#header', Static)
        header.update(self._build_header_markup() + '\n' + self._build_secondary_markup())

    def append_extra(self, text: str) -> None:
        """Append content to the extra section."""
        if self._extra_content:
            self._extra_content += '\n' + text
        else:
            self._extra_content = text
        extra = self.query_one('#extra', Static)
        extra.update(self._extra_content)
        extra.remove_class('-hidden')
        self._collapsed = False

    def toggle_extra(self) -> None:
        """Toggle visibility of extra content."""
        extra = self.query_one('#extra', Static)
        if extra:
            extra.toggle_class('-hidden')
            self._collapsed = not self._collapsed


class TurnDivider(Static):
    """A visual divider between agent turns."""

    DEFAULT_CSS = """
    TurnDivider {
        width: 100%;
        height: 1;
        color: $text-muted;
    }
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.update('[dim #32416a]────────────────────────────────────────[/dim]')


class UserMessage(Static):
    """User message display in the transcript."""

    DEFAULT_CSS = """
    UserMessage {
        width: 100%;
        height: auto;
        margin: 1 0 1 0;
    }
    UserMessage .user-header {
        color: #91abec;
        text-style: bold;
    }
    UserMessage .user-body {
        color: $text-primary;
        margin-left: 1;
    }
    """

    def __init__(self, text: str, *, id: str | None = None) -> None:
        markup = f'[bold #91abec]YOU[/]\n  {text}'
        super().__init__(markup, id=id)


class AgentMessage(Static):
    """Agent response display in the transcript."""

    DEFAULT_CSS = """
    AgentMessage {
        width: 100%;
        height: auto;
        margin: 1 0 1 0;
    }
    """

    def __init__(self, text: str, *, id: str | None = None) -> None:
        markup = f'[bold #54efae]GRINTA[/]\n  {text}'
        super().__init__(markup, id=id)


class ThinkingIndicator(Static):
    """Live thinking/reasoning indicator with step tracking."""

    DEFAULT_CSS = """
    ThinkingIndicator {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
    }
    ThinkingIndicator.-hidden {
        display: none;
    }
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._thoughts: list[str] = []
        self._current_action: str = ''
        self._step_count: int = 0
        self._start_time: float = 0
        self.add_class('-hidden')

    def start(self, action: str = 'Thinking') -> None:
        """Start the thinking indicator."""
        import time
        self._start_time = time.monotonic()
        self._current_action = action
        self._thoughts = []
        self._step_count = 0
        self.remove_class('-hidden')
        self._render()

    def add_thought(self, thought: str) -> None:
        """Add a reasoning step."""
        self._thoughts.append(thought)
        self._step_count += 1
        self._render()

    def update_action(self, action: str) -> None:
        """Update the current action description."""
        self._current_action = action
        self._render()

    def stop(self) -> None:
        """Stop the thinking indicator."""
        self.add_class('-hidden')

    def _render(self) -> None:
        import time
        elapsed = int(time.monotonic() - self._start_time) if self._start_time else 0

        lines: list[str] = []
        lines.append(f'[bold #5eead4]Thinking:[/] [dim]({elapsed}s)[/dim]')

        if self._thoughts:
            for thought in self._thoughts[-5:]:
                truncated = thought[:120] + ('...' if len(thought) > 120 else '')
                lines.append(f'  [dim #6b7280]┃ {truncated}[/]')

        if self._step_count >= 3:
            avg_step = elapsed / self._step_count if self._step_count > 0 else 0
            estimated_remaining = max(0, int((10 - self._step_count) * avg_step))
            if estimated_remaining > 0:
                eta = f'~{estimated_remaining}s' if estimated_remaining < 60 else f'~{estimated_remaining // 60}m'
                lines.append(f'  [dim #969aad]step {self._step_count} · {eta} remaining[/]')

        self.update('\n'.join(lines))
