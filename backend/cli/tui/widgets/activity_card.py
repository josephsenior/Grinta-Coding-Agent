"""Activity card widget for the Grinta TUI.

Renders tool calls, shell commands, file operations, and other agent activities
as compact, consistent cards — matching the CLI activity card system but
implemented as native Textual widgets for incremental updates.
"""

from __future__ import annotations

from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Static

from backend.cli._tool_display.renderers.badge import badge_for_tool_name
from backend.cli.theme import (
    NAVY_BG,
    NAVY_BRAND,
    NAVY_BORDER,
    NAVY_ERROR,
    NAVY_READY,
    NAVY_TEXT_DIM,
    NAVY_TEXT_MUTED,
    NAVY_WAITING,
    get_grinta_pygments_style,
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
        border: round #1b233a;
        background: #08101d;
        padding: 0;
    }
    ActivityCard:hover {
        background: #0a1323;
        border: round #26365b;
    }
    ActivityCard:focus {
        background: #0d162a;
        border: round #4a5f99;
    }
    ActivityCard.processing {
        border: round #32416a;
        background: #091320;
    }
    ActivityCard.category-shell.processing,
    ActivityCard.category-terminal.processing {
        border: round #3e557f;
    }
    ActivityCard .card-shell {
        width: 100%;
        height: auto;
        padding: 0 1;
    }
    ActivityCard .card-title {
        width: 100%;
        height: 1;
        color: #7f8aa3;
        text-style: bold;
        padding: 0 1;
        margin-top: 1;
    }
    ActivityCard .card-header {
        width: 100%;
        height: auto;
        padding: 0 1;
        margin-top: 1;
    }
    ActivityCard .card-secondary {
        width: 100%;
        height: auto;
        padding: 0 1;
    }
    ActivityCard .card-extra-wrap {
        width: 100%;
        height: auto;
        margin: 1 1 1 2;
        padding: 0 0;
        border: round #15233c;
        background: #050b16;
    }
    ActivityCard.category-shell .card-extra-wrap,
    ActivityCard.category-terminal .card-extra-wrap {
        border: round #24385c;
        background: #050913;
    }
    ActivityCard.category-files .card-extra-wrap {
        border: round #1f314f;
        background: #07101d;
    }
    ActivityCard .card-extra {
        width: 100%;
        height: auto;
        padding: 0 1;
    }
    ActivityCard .card-extra-wrap.-hidden {
        display: none;
    }
    """

    _KIND_COLORS = {
        'ok': NAVY_READY,
        'err': NAVY_ERROR,
        'warn': NAVY_WAITING,
        'neutral': NAVY_TEXT_MUTED,
    }

    BINDINGS = [
        ("enter", "toggle", "Toggle Expansion"),
        ("space", "toggle", "Toggle Expansion"),
    ]

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
        self.can_focus = bool(extra_content)
        self.processing = False
        self.add_class(f'category-{badge_category}')
        if extra_content:
            self.add_class('expandable')
        if title:
            self.add_class('has-title')

    def set_processing(self, processing: bool) -> None:
        """Set the card processing status (pulsing indicator)."""
        self.processing = processing
        if processing:
            self.add_class('processing')
        else:
            self.remove_class('processing')
        try:
            header = self.query_one('#header', Static)
            header.update(self._build_header_markup())
        except Exception:
            pass

    def _build_header_markup(self) -> str:
        badge = badge_for_tool_name(self._badge_category)
        badge_render = badge.render()
        verb_style = f'bold {NAVY_BRAND}'
        detail_text = self._detail

        caret = ""
        if self._extra_content:
            icon = '▾' if not self._collapsed else '▸'
            caret = f'[{NAVY_TEXT_DIM}]{icon}[/] '

        pulse = ""
        if self.processing:
            pulse = "[blink #5eead4]●[/] "

        return f'{caret}{pulse}{badge_render} [{verb_style}]{self._verb}[/] {detail_text}'

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
        return f'  {icon} [{color}]{self._secondary}[/]'

    def _get_formatted_extra_content(self) -> Any:
        from rich.syntax import Syntax
        content = self._extra_content or ""

        # Check if it looks like a unified diff (git diff style)
        diff_like = (
            content.startswith('--- ')
            or content.startswith('diff --git')
            or any(
                line.startswith(('+', '-', '@@'))
                for line in content.splitlines()
                if line and not line.startswith(('+++', '---'))
            )
        )
        if diff_like:
            return Syntax(
                content,
                "diff",
                theme=get_grinta_pygments_style(),
                background_color=NAVY_BG,
                line_numbers=True,
                padding=(0, 1),
                word_wrap=True,
            )

        # Check if it is JSON
        if (content.startswith('{') and content.endswith('}')) or (content.startswith('[') and content.endswith(']')):
            try:
                import json
                json.loads(content)
                return Syntax(
                    content,
                    "json",
                    theme=get_grinta_pygments_style(),
                    background_color=NAVY_BG,
                    padding=(0, 1),
                    word_wrap=True,
                )
            except Exception:
                pass

        # Check if it is Python code
        if "def " in content or "class " in content or "import " in content:
            return Syntax(
                content,
                "python",
                theme=get_grinta_pygments_style(),
                background_color=NAVY_BG,
                padding=(0, 1),
                word_wrap=True,
            )

        # Default: wrap in muted style for plain text
        lines = content.splitlines() or ['']
        styled_lines = [f'[{NAVY_TEXT_MUTED}]{line}[/]' for line in lines]
        return '\n'.join(styled_lines)

    def compose(self) -> ComposeResult:
        if self._title:
            yield Static(f'[{NAVY_TEXT_DIM}]{self._title}[/]', classes='card-title')

        with Vertical(classes='card-shell'):
            yield Static(self._build_header_markup(), classes='card-header', id='header')

            if self._secondary:
                yield Static(
                    self._build_secondary_markup(),
                    classes='card-secondary',
                    id='secondary',
                )

        if self._extra_content:
            wrap_classes = 'card-extra-wrap -hidden' if self._collapsed else 'card-extra-wrap'
            with Container(classes=wrap_classes, id='extra-wrap'):
                yield Static(
                    self._get_formatted_extra_content(),
                    classes='card-extra',
                    id='extra',
                )

    def update_secondary(self, text: str, kind: str = 'neutral') -> None:
        """Update the secondary/result line (e.g., after a command completes)."""
        self._secondary = text
        self._secondary_kind = kind
        if not self.is_mounted:
            return
        try:
            secondary = self.query_one('#secondary', Static)
            secondary.update(self._build_secondary_markup())
        except Exception:
            try:
                header = self.query_one('#header', Static)
                header.parent.mount(
                    Static(
                        self._build_secondary_markup(),
                        classes='card-secondary',
                        id='secondary',
                    )
                )
            except Exception:
                return

    def update_header(
        self,
        *,
        verb: str | None = None,
        detail: str | None = None,
        title: str | None = None,
    ) -> None:
        """Update the card header/title in place."""
        if verb is not None:
            self._verb = verb
        if detail is not None:
            self._detail = detail
        if title is not None:
            self._title = title
        if not self.is_mounted:
            return
        try:
            header = self.query_one('#header', Static)
            header.update(self._build_header_markup())
        except Exception:
            pass
        try:
            title_widget = self.query_one('.card-title', Static)
            if self._title:
                title_widget.update(f'[{NAVY_TEXT_DIM}]{self._title}[/]')
        except Exception:
            pass

    def append_extra(self, text: str) -> None:
        """Append content to the extra section."""
        was_empty = not self._extra_content
        if self._extra_content:
            self._extra_content += '\n' + text
        else:
            self._extra_content = text
        self.can_focus = True
        self.add_class('expandable')
        if not self.is_mounted:
            self._collapsed = False
            return
        if was_empty:
            self.mount(
                Container(
                    Static(
                        self._get_formatted_extra_content(),
                        classes='card-extra',
                        id='extra',
                    ),
                    classes='card-extra-wrap',
                    id='extra-wrap',
                )
            )
        else:
            try:
                extra = self.query_one('#extra', Static)
                extra.update(self._get_formatted_extra_content())
            except Exception:
                return
        try:
            self.query_one('#extra-wrap', Container).remove_class('-hidden')
        except Exception:
            return
        self._collapsed = False
        try:
            header = self.query_one('#header', Static)
            header.update(self._build_header_markup())
        except Exception:
            pass

    def set_collapsed(self, collapsed: bool) -> None:
        """Set the expanded/collapsed state without toggling blindly."""
        self._collapsed = collapsed
        if not self.is_mounted:
            return
        try:
            extra_wrap = self.query_one('#extra-wrap', Container)
        except Exception:
            extra_wrap = None
        if extra_wrap is not None:
            if collapsed:
                extra_wrap.add_class('-hidden')
            else:
                extra_wrap.remove_class('-hidden')
        try:
            header = self.query_one('#header', Static)
            header.update(self._build_header_markup())
        except Exception:
            pass

    def toggle_extra(self) -> None:
        """Toggle visibility of extra content."""
        extra_wrap = self.query_one('#extra-wrap', Container)
        if extra_wrap:
            extra_wrap.toggle_class('-hidden')
            self._collapsed = not self._collapsed
            try:
                header = self.query_one('#header', Static)
                header.update(self._build_header_markup())
            except Exception:
                pass

    def action_toggle(self) -> None:
        """Action handler for enter/space keypresses."""
        if self._extra_content:
            self.toggle_extra()

    def on_click(self, event: events.Click) -> None:
        """Handle click events on the header or widget itself."""
        if self._extra_content and event.widget and (event.widget.id == 'header' or event.widget == self):
            self.toggle_extra()
            event.prevent_default()
            event.stop()


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

    def __init__(self, text: str, *, id: str | None = None) -> None:
        super().__init__(text, id=id)


class AgentMessage(Static):
    """Agent response display in the transcript."""

    def __init__(self, text: str, *, id: str | None = None) -> None:
        super().__init__(text, id=id)

    def update_message(self, text: str) -> None:
        """Update message content dynamically."""
        self.update(text)


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
        self._update_display()

    def add_thought(self, thought: str) -> None:
        """Add a reasoning step."""
        self._thoughts.append(thought)
        self._step_count += 1
        self._update_display()

    def set_thoughts(self, text: str) -> None:
        """Set thoughts by parsing accumulated text."""
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        self._thoughts = lines
        self._step_count = len(lines)
        self._update_display()

    def update_action(self, action: str) -> None:
        """Update the current action description."""
        self._current_action = action
        self._update_display()

    def stop(self) -> None:
        """Stop the thinking indicator."""
        self.add_class('-hidden')

    def _update_display(self) -> None:
        import time

        elapsed = int(time.monotonic() - self._start_time) if self._start_time else 0

        lines: list[str] = []
        lines.append(f'[bold #5eead4]Thinking:[/] [dim]({elapsed}s)[/dim]')

        if self._thoughts:
            for thought in self._thoughts[-5:]:
                truncated = thought[:120] + ('...' if len(thought) > 120 else '')
                lines.append(f'  [lightgray opacity=70]┃ {truncated}[/]')

        if self._step_count >= 3:
            avg_step = elapsed / self._step_count if self._step_count > 0 else 0
            estimated_remaining = max(0, int((10 - self._step_count) * avg_step))
            if estimated_remaining > 0:
                eta = (
                    f'~{estimated_remaining}s'
                    if estimated_remaining < 60
                    else f'~{estimated_remaining // 60}m'
                )
                lines.append(
                    f'  [lightgray opacity=70]step {self._step_count} · {eta} remaining[/]'
                )

        self.update('\n'.join(lines))
