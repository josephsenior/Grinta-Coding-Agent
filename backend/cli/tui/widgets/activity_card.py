"""Activity card widget for the Grinta TUI.

Renders tool calls, shell commands, file operations, and other agent activities
as compact, consistent cards with collapsed/expanded states.

Collapsed cards show:
  [status icon] [action] [target] [compact outcome]

Expanded cards show:
  bordered box with content/diff/output/metadata
"""

from __future__ import annotations

import json
from typing import Any

from rich.syntax import Syntax
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Static

from backend.cli.theme import (
    NAVY_BG,
    NAVY_BRAND,
    NAVY_ERROR,
    NAVY_READY,
    NAVY_TEXT_DIM,
    NAVY_TEXT_MUTED,
    get_grinta_pygments_style,
)

DIFF_ADD_PREFIX = '\x1fgrinta-diff-add\x1f'
DIFF_REM_PREFIX = '\x1fgrinta-diff-rem\x1f'
DIFF_CTX_PREFIX = '\x1fgrinta-diff-ctx\x1f'
DIFF_SPLIT_PREFIX = '\x1fgrinta-diff-split\x1f'


class DiffLine(Static):
    """Full-width row for file preview and edit diff lines."""

    DEFAULT_CSS = """
    DiffLine {
        width: 100%;
        height: 1;
        padding: 0 1;
    }
    DiffLine.add {
        background: #0f2f22;
        color: #7de6a1;
    }
    DiffLine.rem {
        background: #351818;
        color: #ff9a9a;
    }
    DiffLine.ctx {
        background: transparent;
        color: #969aad;
    }
    """

    _STYLE_BY_KIND = {
        'add': '#7de6a1',
        'rem': '#ff9a9a',
        'ctx': NAVY_TEXT_MUTED,
    }

    def __init__(self, text: str, kind: str, *, id: str | None = None) -> None:
        super().__init__(
            Text(text, style=self._STYLE_BY_KIND.get(kind, NAVY_TEXT_MUTED)),
            id=id,
        )
        self.add_class(kind)


class SplitDiffLine(Container):
    """Two-pane row for before/after file edit hunks."""

    DEFAULT_CSS = """
    SplitDiffLine {
        width: 100%;
        height: 1;
        layout: horizontal;
    }
    SplitDiffLine .split-pane {
        width: 1fr;
        height: 1;
        padding: 0 1;
    }
    SplitDiffLine .split-pane.left {
        border-right: solid #26324f;
    }
    SplitDiffLine .split-pane.add {
        background: #0f2f22;
        color: #7de6a1;
    }
    SplitDiffLine .split-pane.rem {
        background: #351818;
        color: #ff9a9a;
    }
    SplitDiffLine .split-pane.ctx {
        background: transparent;
        color: #969aad;
    }
    """

    _STYLE_BY_KIND = DiffLine._STYLE_BY_KIND

    def __init__(
        self,
        left: str,
        right: str,
        left_kind: str,
        right_kind: str,
        *,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.left_text = left
        self.right_text = right
        self.left_kind = left_kind
        self.right_kind = right_kind

    def compose(self) -> ComposeResult:
        left_style = self._STYLE_BY_KIND.get(self.left_kind, NAVY_TEXT_MUTED)
        right_style = self._STYLE_BY_KIND.get(self.right_kind, NAVY_TEXT_MUTED)
        yield Static(
            Text(self.left_text or ' ', style=left_style),
            classes=f'split-pane left {self.left_kind}',
        )
        yield Static(
            Text(self.right_text or ' ', style=right_style),
            classes=f'split-pane right {self.right_kind}',
        )


def encode_diff_line(text: str, kind: str) -> str:
    prefix = {
        'add': DIFF_ADD_PREFIX,
        'rem': DIFF_REM_PREFIX,
        'ctx': DIFF_CTX_PREFIX,
    }.get(kind, DIFF_CTX_PREFIX)
    return f'{prefix}{text}'


def encode_split_diff_line(
    left: str,
    right: str,
    left_kind: str,
    right_kind: str,
) -> str:
    payload = {
        'left': left,
        'right': right,
        'left_kind': left_kind,
        'right_kind': right_kind,
    }
    return DIFF_SPLIT_PREFIX + json.dumps(payload, ensure_ascii=True)


def _decode_diff_line(line: str) -> tuple[str, str] | None:
    for prefix, kind in (
        (DIFF_ADD_PREFIX, 'add'),
        (DIFF_REM_PREFIX, 'rem'),
        (DIFF_CTX_PREFIX, 'ctx'),
    ):
        if line.startswith(prefix):
            return kind, line[len(prefix):]
    return None


def _decode_split_diff_line(line: str) -> tuple[str, str, str, str] | None:
    if not line.startswith(DIFF_SPLIT_PREFIX):
        return None
    try:
        payload = json.loads(line[len(DIFF_SPLIT_PREFIX):])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    left = str(payload.get('left') or '')
    right = str(payload.get('right') or '')
    left_kind = str(payload.get('left_kind') or 'ctx')
    right_kind = str(payload.get('right_kind') or 'ctx')
    return left, right, left_kind, right_kind


class ActivityCard(Container):
    """Compact activity card with collapsed/expanded states.

    Collapsed (default):
      ✓ Created  test_edit.txt                 +4
      ✓ Edited   test_edit.txt                 +1 -1
      ✓ Shell    Get-ChildItem -Name           exit 0
      ✓ Read     src/main.py

    Expanded:
      Bordered box with content/diff/output/metadata.
    """

    DEFAULT_CSS = """
    ActivityCard {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        border: round #1b233a;
        background: #08101d;
        padding: 0 0 0 1;
    }
    ActivityCard:focus {
        border: round #4a5f99;
        background: #0d162a;
    }
    ActivityCard:hover {
        background: #0a1323;
        border: round #26365b;
    }
    ActivityCard.-category-shell,
    ActivityCard.-category-terminal {
        border: round #24385c;
        background: #050913;
    }
    ActivityCard #collapsed-row-container {
        width: 100%;
        height: 1;
        layout: horizontal;
    }
    ActivityCard .card-collapsed-text {
        width: 1fr;
        height: 1;
    }
    ActivityCard .card-caret {
        width: 3;
        height: 1;
        content-align: right middle;
        color: #54597b;
        padding: 0 1 0 0;
    }
    ActivityCard .card-caret:hover {
        color: #91abec;
    }
    ActivityCard .card-expanded-body {
        width: 100%;
        height: auto;
        padding: 0 1;
        margin: 1 0;
    }
    ActivityCard .card-extra-content {
        width: 100%;
        height: auto;
    }
    ActivityCard .card-meta-row {
        width: 100%;
        height: auto;
        padding: 0 1;
        color: #54597b;
    }
    ActivityCard .card-meta-row.-hidden {
        display: none;
    }
    """

    _STATUS_COLORS = {
        'ok': '#54efae',
        'err': '#fd8383',
        'warn': '#f6ff8f',
        'info': '#91abec',
        'neutral': '#969aad',
        'running': '#5eead4',
    }

    _STATUS_ICONS = {
        'ok': '✓',
        'err': '✗',
        'warn': '!',
        'info': '?',
        'neutral': '•',
        'running': '…',
    }

    BINDINGS = [
        ('enter', 'toggle', 'Toggle Expansion'),
        ('space', 'toggle', 'Toggle Expansion'),
    ]

    def __init__(
        self,
        verb: str,
        detail: str,
        *,
        badge_category: str = 'tool',
        status: str = 'neutral',
        outcome: str | None = None,
        extra_content: str | None = None,
        collapsed: bool = True,
        diff_encoded: bool = False,
        show_meta: bool = False,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._verb = verb
        self._detail = detail
        self._badge_category = badge_category
        self._status = status
        self._outcome = outcome
        self._extra_content = extra_content
        self._collapsed = collapsed
        self._diff_encoded = diff_encoded
        self._show_meta = show_meta
        self.processing = False
        self.can_focus = bool(extra_content)
        self._meta_lines: list[str] = []

        self.add_class(f'category-{badge_category}')
        if collapsed:
            self.add_class('-collapsed')
        else:
            self.add_class('-expanded')

    def set_processing(self, processing: bool) -> None:
        """Set the card processing status."""
        self.processing = processing
        if processing and self._status == 'neutral':
            self._status = 'running'
        elif not processing and self._status == 'running':
            self._status = 'neutral'
        try:
            collapsed = self.query_one('#collapsed-row', Static)
            collapsed.update(self._build_collapsed_markup())
        except Exception:
            pass

    def set_status(self, status: str, outcome: str | None = None) -> None:
        """Update the card status icon and outcome text."""
        self._status = status
        if outcome is not None:
            self._outcome = outcome
        try:
            collapsed = self.query_one('#collapsed-row', Static)
            collapsed.update(self._build_collapsed_markup())
        except Exception:
            pass

    def set_verb(self, verb: str, detail: str | None = None) -> None:
        """Update the verb and/or detail text."""
        self._verb = verb
        if detail is not None:
            self._detail = detail
        try:
            collapsed = self.query_one('#collapsed-row', Static)
            collapsed.update(self._build_collapsed_markup())
        except Exception:
            pass

    def set_outcome(self, outcome: str) -> None:
        """Update the outcome text without changing status."""
        self._outcome = outcome
        try:
            collapsed = self.query_one('#collapsed-row', Static)
            collapsed.update(self._build_collapsed_markup())
        except Exception:
            pass

    def _build_collapsed_markup(self) -> str:
        status = self._status or 'neutral'
        icon = self._STATUS_ICONS.get(status, '•')
        color = self._STATUS_COLORS.get(status, NAVY_TEXT_MUTED)

        pulse = ''
        if self.processing:
            pulse = '[blink #5eead4]…[/] '
            icon = '…'
            color = '#5eead4'

        icon_part = f'[{color}]{icon}[/]'
        verb_part = f'[bold {NAVY_BRAND}]{self._verb}[/]'
        detail_part = self._detail
        outcome_part = ''
        if self._outcome:
            outcome_color = (
                NAVY_READY if status == 'ok'
                else NAVY_ERROR if status == 'err'
                else NAVY_TEXT_DIM
            )
            outcome_part = f'  [{outcome_color}]{self._outcome}[/]'

        return f'{pulse}{icon_part} {verb_part}  {detail_part}{outcome_part}'

    def _caret_char(self) -> str:
        return chr(9660) if not self._collapsed else chr(9654)

    def _get_formatted_extra_content(self) -> Any:
        content = self._extra_content or ''

        if '[on #' in content:
            return content

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
                'diff',
                theme=get_grinta_pygments_style(),
                background_color=NAVY_BG,
                line_numbers=True,
                padding=(0, 1),
                word_wrap=True,
            )

        if (content.startswith('{') and content.endswith('}')) or (content.startswith('[') and content.endswith(']')):
            try:
                json.loads(content)
                return Syntax(
                    content,
                    'json',
                    theme=get_grinta_pygments_style(),
                    background_color=NAVY_BG,
                    padding=(0, 1),
                    word_wrap=True,
                )
            except Exception:
                pass

        if 'def ' in content or 'class ' in content or 'import ' in content:
            return Syntax(
                content,
                'python',
                theme=get_grinta_pygments_style(),
                background_color=NAVY_BG,
                padding=(0, 1),
                word_wrap=True,
            )

        lines = content.splitlines() or ['']
        styled_lines = [f'[{NAVY_TEXT_MUTED}]{line}[/]' for line in lines]
        return '\n'.join(styled_lines)

    def _extra_renderables(self) -> list[Any]:
        content = self._extra_content or ''

        if self._diff_encoded:
            renderables: list[Any] = []
            for line in content.splitlines():
                split_decoded = _decode_split_diff_line(line)
                if split_decoded is not None:
                    left, right, left_kind, right_kind = split_decoded
                    renderables.append(
                        SplitDiffLine(left, right, left_kind, right_kind)
                    )
                    continue
                decoded = _decode_diff_line(line)
                if decoded is not None:
                    kind, body = decoded
                    renderables.append(DiffLine(body, kind))
                else:
                    renderables.append(DiffLine(line, 'ctx'))
            return renderables or [Static('', id='extra')]

        return [Static(self._get_formatted_extra_content(), id='extra')]

    def compose(self) -> ComposeResult:
        with Horizontal(id='collapsed-row-container'):
            yield Static(self._build_collapsed_markup(), id='collapsed-row', classes='card-collapsed-text')
            if self._extra_content:
                yield Static(self._caret_char(), id='caret', classes='card-caret')

        if self._extra_content:
            with Container(classes='card-expanded-body', id='expanded-body'):
                yield from self._extra_renderables()

            if self._show_meta or self._meta_lines:
                meta_text = '  '.join(self._meta_lines) if self._meta_lines else ''
                yield Static(meta_text, id='meta-row', classes='card-meta-row -hidden' if self._collapsed else 'card-meta-row')
        else:
            yield Container(id='expanded-body', classes='card-expanded-body -hidden')
            yield Static('', id='meta-row', classes='card-meta-row -hidden')

    def on_mount(self) -> None:
        self._sync_visibility()

    def _sync_visibility(self) -> None:
        try:
            body = self.query_one('#expanded-body', Container)
        except Exception:
            body = None
        try:
            meta = self.query_one('#meta-row', Static)
        except Exception:
            meta = None

        if self._collapsed:
            self.remove_class('-expanded')
            self.add_class('-collapsed')
            if body is not None:
                body.display = False
            if meta is not None:
                meta.display = False
        else:
            self.remove_class('-collapsed')
            self.add_class('-expanded')
            if body is not None:
                body.display = True
            if meta is not None:
                meta.display = True

        try:
            collapsed = self.query_one('#collapsed-row', Static)
            collapsed.update(self._build_collapsed_markup())
        except Exception:
            pass
        try:
            caret = self.query_one('#caret', Static)
            caret.update(self._caret_char())
        except Exception:
            pass

    def set_collapsed(self, collapsed: bool) -> None:
        """Set the expanded/collapsed state."""
        self._collapsed = collapsed
        if not self.is_mounted:
            return
        self._sync_visibility()

    def expand(self) -> None:
        """Expand the card to show details."""
        if self._collapsed:
            self.set_collapsed(False)

    def collapse(self) -> None:
        """Collapse the card back to compact view."""
        if not self._collapsed:
            self.set_collapsed(True)

    def toggle_extra(self) -> None:
        """Toggle visibility of expanded content."""
        self._collapsed = not self._collapsed
        self._sync_visibility()

    def action_toggle(self) -> None:
        """Action handler for enter/space keypresses."""
        if self._extra_content:
            self.toggle_extra()

    def on_click(self, event: events.Click) -> None:
        """Handle click events to toggle expansion."""
        if self._extra_content:
            clicked = event.widget
            if clicked and clicked.id in ('collapsed-row', 'caret', 'collapsed-row-container'):
                self.toggle_extra()
                event.prevent_default()
                event.stop()
            elif clicked == self:
                self.toggle_extra()
                event.prevent_default()
                event.stop()

    def update_content(self, extra_content: str) -> None:
        """Update or set the extra content."""
        self._extra_content = extra_content
        self.can_focus = True
        if not self.is_mounted:
            self._collapsed = False
            return

        try:
            body = self.query_one('#expanded-body', Container)
            body.remove_children()
            for renderable in self._extra_renderables():
                body.mount(renderable)
            body.display = True
        except Exception:
            pass

        if self._collapsed:
            self._collapsed = False
            self._sync_visibility()

    def append_content(self, text: str) -> None:
        """Append content to the extra section."""
        if self._extra_content:
            self._extra_content += '\n' + text
        else:
            self._extra_content = text
        self.can_focus = True

        if not self.is_mounted:
            self._collapsed = False
            return

        self.update_content(self._extra_content)

    def set_meta(self, *lines: str) -> None:
        """Set metadata lines shown in expanded view."""
        self._meta_lines = list(lines)
        self._show_meta = bool(self._meta_lines)
        if not self.is_mounted:
            return
        try:
            meta = self.query_one('#meta-row', Static)
            meta_text = '  '.join(self._meta_lines) if self._meta_lines else ''
            meta.update(meta_text)
            meta.display = not self._collapsed
        except Exception:
            pass


class TurnCompletion(Static):
    """Thin full-width completion marker between agent turns."""

    DEFAULT_CSS = """
    TurnCompletion {
        width: 100%;
        height: 1;
        margin: 0 0 1 0;
        padding: 0 1;
        background: #071b21;
        color: #8f9fc1;
    }
    """

    def __init__(
        self,
        duration: str,
        *,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.update(f'[bold #5eead4]Finished in:[/] [#c8d4e8]{duration}[/]')


class UserMessage(Static):
    """User message display in the transcript."""

    def __init__(self, text: str, *, id: str | None = None) -> None:
        super().__init__(text, id=id)


class AgentMessage(Static):
    """Agent response display in the transcript."""

    def __init__(self, text: str, *, id: str | None = None) -> None:
        from rich.markdown import Markdown
        from backend.cli.theme import get_grinta_pygments_style
        super().__init__(Markdown(text, code_theme=get_grinta_pygments_style()), id=id)

    def update_message(self, text: str) -> None:
        """Update message content dynamically."""
        from rich.markdown import Markdown
        from backend.cli.theme import get_grinta_pygments_style
        self.update(Markdown(text, code_theme=get_grinta_pygments_style()))


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
        self._thoughts = text.split('\n')
        self._step_count = len(self._thoughts)
        self._update_display()

    def stop(self) -> None:
        """Stop the thinking indicator."""
        self.add_class('-hidden')

    def _update_display(self) -> None:
        import time

        elapsed = int(time.monotonic() - self._start_time) if self._start_time else 0
        dots = '.' * ((elapsed % 4))

        thoughts_text = Text(
            '\n  '.join(self._thoughts), style='rgb(150,154,189)'
        )
        self.update(
            Text.assemble(
                ('Thinking:', 'bold #5eead4'),
                ' ',
                (f'({elapsed}s){dots}', 'dim'),
                '\n  ',
                thoughts_text,
            )
        )
