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
import re
from typing import Any

from rich.syntax import Syntax
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Static

from backend.cli.syntax_theme import get_grinta_rich_syntax_theme
from backend.cli.theme import (
    NAVY_BG,
    NAVY_BRAND,
    NAVY_ERROR,
    NAVY_READY,
    NAVY_TEXT_DIM,
    NAVY_TEXT_MUTED,
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
            return kind, line[len(prefix) :]
    return None


def _decode_split_diff_line(line: str) -> tuple[str, str, str, str] | None:
    if not line.startswith(DIFF_SPLIT_PREFIX):
        return None
    try:
        payload = json.loads(line[len(DIFF_SPLIT_PREFIX) :])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    left = str(payload.get('left') or '')
    right = str(payload.get('right') or '')
    left_kind = str(payload.get('left_kind') or 'ctx')
    right_kind = str(payload.get('right_kind') or 'ctx')
    return left, right, left_kind, right_kind


def _format_file_delta_outcome(outcome: str) -> str | None:
    """Return independently colored +N/-N file delta tokens."""
    tokens = outcome.replace(',', ' ').replace('·', ' ').split()
    if not tokens:
        return None

    parts: list[str] = []
    has_delta = False
    for token in tokens:
        if token.startswith('+') and token[1:].isdigit():
            parts.append(f'[{NAVY_READY}]{token}[/]')
            has_delta = True
        elif token.startswith('-') and token[1:].isdigit():
            parts.append(f'[{NAVY_ERROR}]{token}[/]')
            has_delta = True
        else:
            parts.append(f'[{NAVY_TEXT_DIM}]{token}[/]')

    return '  '.join(parts) if has_delta else None


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
    ActivityCard.-category-grep,
    ActivityCard.-category-glob,
    ActivityCard.-category-search {
        border: round #2d4a6a;
        background: #050c14;
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
        collapsible: bool = True,
        diff_encoded: bool = False,
        show_meta: bool = False,
        syntax_language: str | None = None,
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
        self._collapsible = collapsible
        self._diff_encoded = diff_encoded
        self._show_meta = show_meta
        self._syntax_language = syntax_language
        self.processing = False
        self.can_focus = bool(extra_content) or collapsible
        self._meta_lines: list[str] = []
        self._incremental_mode = False
        self._incremental_hidden_lines = 0

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
            file_delta = (
                _format_file_delta_outcome(self._outcome)
                if self._badge_category == 'files'
                else None
            )
            if file_delta:
                outcome_part = f'  {file_delta}'
            else:
                outcome_color = (
                    NAVY_READY
                    if status == 'ok'
                    else NAVY_ERROR
                    if status == 'err'
                    else NAVY_TEXT_DIM
                )
                outcome_part = f'  [{outcome_color}]{self._outcome}[/]'

        return f'{pulse}{icon_part} {verb_part}  {detail_part}{outcome_part}'

    def _caret_char(self) -> str:
        return chr(9660) if not self._collapsed else chr(9654)

    def _build_syntax_renderable(
        self,
        content: str,
        language: str,
        *,
        line_numbers: bool = False,
    ) -> Syntax:
        return Syntax(
            content,
            language,
            theme=get_grinta_rich_syntax_theme(),
            background_color=NAVY_BG,
            line_numbers=line_numbers,
            padding=(0, 1),
            word_wrap=True,
        )

    def _is_diff_like_content(self, content: str) -> bool:
        if content.startswith('--- ') or content.startswith('diff --git'):
            return True
        return any(
            line.startswith(('+', '-', '@@'))
            for line in content.splitlines()
            if line and not line.startswith(('+++', '---'))
        )

    def _try_json_syntax(self, content: str) -> Any | None:
        is_json_shape = (content.startswith('{') and content.endswith('}')) or (
            content.startswith('[') and content.endswith(']')
        )
        if not is_json_shape:
            return None
        try:
            json.loads(content)
        except Exception:
            return None
        return self._build_syntax_renderable(content, 'json')

    def _format_plain_content(self, content: str) -> str:
        lines = content.splitlines() or ['']
        styled_lines = [f'[{NAVY_TEXT_MUTED}]{line}[/]' for line in lines]
        return '\n'.join(styled_lines)

    def _auto_detect_format(self, content: str) -> Any:
        if self._is_diff_like_content(content):
            return self._build_syntax_renderable(content, 'diff', line_numbers=True)
        json_result = self._try_json_syntax(content)
        if json_result is not None:
            return json_result
        return self._format_plain_content(content)

    def _get_formatted_extra_content(self) -> Any:
        content = self._extra_content or ''

        if '[on #' in content:
            return content

        if self._syntax_language:
            return self._build_syntax_renderable(
                content,
                self._syntax_language,
                line_numbers=self._syntax_language == 'diff',
            )

        return self._auto_detect_format(content)

    def _extra_renderables(self) -> list[Any]:
        content = self._extra_content or ''

        if self._diff_encoded:
            from backend.cli.tui.widgets.unified_diff_view import diff_view_from_encoded

            diff_view = diff_view_from_encoded(content)
            if diff_view is not None:
                return [diff_view]

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
            yield Static(
                self._build_collapsed_markup(),
                id='collapsed-row',
                classes='card-collapsed-text',
            )
            if self._collapsible:
                yield Static(self._caret_char(), id='caret', classes='card-caret')

        if self._extra_content:
            with Container(classes='card-expanded-body', id='expanded-body'):
                yield from self._extra_renderables()

            if self._show_meta or self._meta_lines:
                meta_text = '  '.join(self._meta_lines) if self._meta_lines else ''
                yield Static(
                    meta_text,
                    id='meta-row',
                    classes='card-meta-row -hidden'
                    if self._collapsed
                    else 'card-meta-row',
                )
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
        if self._collapsible:
            self.toggle_extra()

    def _clicked_inside_expanded_body(self, widget: Any) -> bool:
        node = widget
        while node is not None and node is not self:
            if getattr(node, 'id', None) == 'expanded-body':
                return True
            classes = getattr(node, 'classes', ())
            if 'card-expanded-body' in classes:
                return True
            node = getattr(node, 'parent', None)
        return False

    def on_click(self, event: events.Click) -> None:
        """Handle click events to toggle expansion."""
        if self._collapsible:
            clicked = event.widget
            if not self._collapsed and self._clicked_inside_expanded_body(clicked):
                self.collapse()
                event.prevent_default()
                event.stop()
                return
            clicked_id = getattr(clicked, 'id', None)
            if clicked_id in (
                'collapsed-row',
                'caret',
                'collapsed-row-container',
            ):
                self.toggle_extra()
                event.prevent_default()
                event.stop()
            elif clicked == self:
                self.toggle_extra()
                event.prevent_default()
                event.stop()

    def enable_incremental_mode(self) -> None:
        """Use single-widget tail updates instead of full body remounts."""
        self._incremental_mode = True

    def _ensure_collapsible_for_extra(self) -> None:
        if self._collapsible:
            return
        self._collapsible = True
        if not self.is_mounted:
            return
        try:
            row = self.query_one('#collapsed-row-container', Horizontal)
            if not row.query('#caret'):
                row.mount(Static(self._caret_char(), id='caret', classes='card-caret'))
        except Exception:
            pass

    def _trim_incremental_lines(self, line_cap: int) -> None:
        lines = (self._extra_content or '').splitlines()
        if len(lines) <= line_cap:
            return
        hidden = len(lines) - line_cap
        self._incremental_hidden_lines += hidden
        self._extra_content = '\n'.join(lines[-line_cap:])

    def _incremental_tail_markup(self) -> str:
        from backend.cli.tui._app_constants import _TUI_TERMINAL_DISPLAY_LINE_CAP

        lines = (self._extra_content or '').splitlines()
        if len(lines) > _TUI_TERMINAL_DISPLAY_LINE_CAP:
            self._trim_incremental_lines(_TUI_TERMINAL_DISPLAY_LINE_CAP)
            lines = (self._extra_content or '').splitlines()
        parts: list[str] = []
        if self._incremental_hidden_lines:
            parts.append(
                f'[{NAVY_TEXT_DIM}]…{self._incremental_hidden_lines} earlier '
                f'line(s) hidden in card…[/]'
            )
        parts.extend(
            f'[{NAVY_TEXT_MUTED}]{line}[/]' for line in lines if line or lines == ['']
        )
        return '\n'.join(parts) if parts else ''

    def _mount_incremental_tail(self, body: Container) -> None:
        markup = self._incremental_tail_markup()
        try:
            tail = body.query_one('#incremental-tail', Static)
            tail.update(markup)
        except Exception:
            body.remove_children()
            body.mount(Static(markup, id='incremental-tail'))
        body.display = not self._collapsed

    def append_content_incremental(self, text: str) -> None:
        """Append terminal/shell output without remounting the expanded body."""
        chunk = (text or '').strip('\n')
        if not chunk:
            return
        if self._extra_content:
            self._extra_content += '\n' + chunk
        else:
            self._extra_content = chunk
        self.can_focus = True
        self._ensure_collapsible_for_extra()
        if not self.is_mounted:
            return
        try:
            body = self.query_one('#expanded-body', Container)
            self._mount_incremental_tail(body)
        except Exception:
            pass

    def update_content(self, extra_content: str) -> None:
        """Update or set the extra content."""
        self._extra_content = extra_content
        self.can_focus = True
        if not self.is_mounted:
            return

        try:
            body = self.query_one('#expanded-body', Container)
            if self._incremental_mode and not self._diff_encoded:
                self._mount_incremental_tail(body)
                return
            body.remove_children()
            for renderable in self._extra_renderables():
                body.mount(renderable)
            body.display = not self._collapsed
        except Exception:
            pass

    def append_content(self, text: str) -> None:
        """Append content to the extra section."""
        if self._incremental_mode and not self._diff_encoded:
            self.append_content_incremental(text)
            return
        if self._extra_content:
            self._extra_content += '\n' + text
        else:
            self._extra_content = text
        self.can_focus = True
        self._ensure_collapsible_for_extra()
        if not self.is_mounted:
            return
        self.update_content(self._extra_content)

    def set_syntax_language(self, language: str | None) -> None:
        """Override the language used when syntax-highlighting extra content."""
        if language == self._syntax_language:
            return
        self._syntax_language = language
        if not self.is_mounted or self._extra_content is None:
            return
        try:
            body = self.query_one('#expanded-body', Container)
            body.remove_children()
            for renderable in self._extra_renderables():
                body.mount(renderable)
            body.display = not self._collapsed
        except Exception:
            pass

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

    def __init__(
        self,
        text: str,
        *,
        renderable: Any | None = None,
        id: str | None = None,
    ) -> None:
        if renderable is None:
            from backend.cli.tui._render_prep import prep_markdown

            renderable = prep_markdown(text)
        super().__init__(renderable, id=id)

    def update_message(self, text: str, *, renderable: Any | None = None) -> None:
        """Update message content dynamically."""
        if renderable is None:
            from backend.cli.tui._render_prep import prep_markdown

            renderable = prep_markdown(text)
        self.update(renderable)


class LiveResponse(Static):
    """In-flight assistant response with lightweight streaming affordances."""

    DEFAULT_CSS = """
    LiveResponse {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        padding: 0 1 0 2;
        background: #070b14;
        border-left: solid #3d5a80;
        color: #b8c4d8;
    }
    LiveResponse.-streaming {
        color: #d5dee8;
        border-left: solid #5eead4;
    }
    """

    def set_streaming_renderable(self, renderable: Any) -> None:
        """Update visible streaming content."""
        if renderable is None or renderable == '':
            self.update('')
            self.remove_class('-streaming')
            return
        self.add_class('-streaming')
        self.update(renderable)

    def set_streaming_text(self, text: str) -> None:
        """Fallback plain-text update when highlighted prep is unavailable."""
        if not text:
            self.update('')
            self.remove_class('-streaming')
            return
        self.add_class('-streaming')
        self.update(Text(text, style='#d5dee8'))


class ThinkingIndicator(Container):
    """Thinking/reasoning indicator with inline prefix.

    Shows the thinking content directly with a "Thinking:" prefix
    inline on the first line. No collapse/expand, no duration display.
    Supports syntax highlighting for code blocks within thinking content.
    """

    DEFAULT_CSS = """
    ThinkingIndicator {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        border: transparent;
        background: #090d18;
        border-left: solid #3d5a80;
        padding: 0 1 0 2;
    }
    ThinkingIndicator.-hidden {
        display: none;
    }
    ThinkingIndicator.-streaming {
        background: #0a101c;
        border-left: solid #5eead4;
    }
    ThinkingIndicator > #thinking-content {
        width: 100%;
        height: auto;
    }
    ThinkingIndicator .code-block {
        margin: 1 0;
        padding: 0 1;
        background: #0d1525;
    }
    """

    # Pattern to match fenced code blocks: ```language\n...\n```
    _CODE_BLOCK_PATTERN = re.compile(r'```(\w*)\n(.*?)```', re.DOTALL)

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._thoughts: list[str] = []
        self._current_action: str = 'Thinking'
        self._code_block_container: Any = None
        self.add_class('-hidden')

    def compose(self) -> ComposeResult:
        yield Static('', id='thinking-content')

    def start(self, action: str = 'Thinking') -> None:
        """Start the thinking indicator."""
        self._current_action = action
        self._thoughts = []
        self.remove_class('-hidden')
        self._update_display()

    def add_thought(self, thought: str) -> None:
        """Add a reasoning step."""
        self._thoughts.append(thought)
        self._update_display()

    def set_thoughts(self, text: str, *, streaming: bool = False) -> None:
        if streaming and text == getattr(self, '_last_stream_text', ''):
            return
        if streaming:
            self._last_stream_text = text
        else:
            self._last_stream_text = ''
        self._thoughts = text.split('\n')
        self._update_display(streaming=streaming)

    def stop(self) -> None:
        """Stop the thinking indicator."""
        self.add_class('-hidden')

    def finalize(self) -> None:
        """No-op for API compatibility."""

    def _has_code_blocks(self, text: str) -> bool:
        """Check if text contains fenced code blocks."""
        return bool(self._CODE_BLOCK_PATTERN.search(text))

    def _parse_text_segments(self, text: str) -> list[tuple[str, Any]]:
        segments = []
        last_end = 0
        for match in self._CODE_BLOCK_PATTERN.finditer(text):
            if match.start() > last_end:
                plain_text = text[last_end : match.start()]
                if plain_text.strip():
                    segments.append(('plain', plain_text))
            language = match.group(1) or 'text'
            code_content = match.group(2)
            segments.append(('code', (language, code_content)))
            last_end = match.end()
        if last_end < len(text):
            remaining = text[last_end:]
            if remaining.strip():
                segments.append(('plain', remaining))
        return segments

    def _build_segment_widgets(self, segments: list[tuple[str, Any]]) -> list[Any]:
        from textual.widgets import Static as TextualStatic

        prefix = f'{self._current_action}: '
        prefix_color = '#42a394'
        text_color = '#8c8c94'
        children: list[Any] = []

        for seg_type, seg_content in segments:
            if seg_type == 'plain':
                if not children:
                    parts = [
                        (prefix, f'bold {prefix_color}'),
                        (seg_content, text_color),
                    ]
                    text_widget = TextualStatic(Text.assemble(*parts))
                else:
                    text_widget = TextualStatic(Text(seg_content, style=text_color))
                children.append(text_widget)
            else:
                language, code = seg_content
                syntax = Syntax(
                    code,
                    language,
                    theme=get_grinta_rich_syntax_theme(),
                    background_color='#0d1525',
                    padding=(0, 1),
                    word_wrap=True,
                )
                code_widget = TextualStatic(syntax)
                code_widget.add_class('code-block')
                children.append(code_widget)
        return children

    def _render_with_code_blocks(self, text: str) -> tuple[Any, list[Any]]:
        """Render text with syntax-highlighted code blocks.

        Returns a tuple of (container, children_widgets) to be mounted by caller.
        """
        prefix = f'{self._current_action}: '
        prefix_color = '#42a394'
        text_color = '#8c8c94'

        segments = self._parse_text_segments(text)

        if not segments:
            parts = [(prefix, f'bold {prefix_color}'), (text, text_color)]
            return Text.assemble(*parts), []

        from textual.containers import Vertical

        container = Vertical()
        children = self._build_segment_widgets(segments)
        return container, children

    def _build_thoughts_text_parts(self) -> list[tuple[str, str]]:
        prefix = f'{self._current_action}: '
        prefix_color = '#42a394'
        text_color = '#8c8c94'
        lines = self._thoughts
        parts: list[tuple[str, str]] = [
            (prefix, f'bold {prefix_color}'),
            (lines[0], text_color),
        ]
        for line in lines[1:]:
            parts.append(('\n  ', text_color))
            parts.append((line, text_color))
        return parts

    def _update_display_streaming(self, content: Static) -> None:
        from rich.console import Group

        from backend.cli.tui._render_prep import prep_streaming_renderable

        content.remove_class('-hidden')
        if self._code_block_container is not None:
            self._code_block_container.remove()
            self._code_block_container = None

        full_text = '\n'.join(self._thoughts)
        prefix_color = '#42a394'
        prefix = Text.assemble((f'{self._current_action}: ', f'bold {prefix_color}'))

        if '```' in full_text or '`' in full_text:
            body = prep_streaming_renderable(full_text)
            content.update(Group(prefix, body))
            return

        parts = self._build_thoughts_text_parts()
        content.update(Text.assemble(*parts))

    def _update_display_with_code_blocks(self, content: Static, full_text: str) -> None:
        from textual.containers import Vertical

        content.add_class('-hidden')
        if self._code_block_container is None:
            self._code_block_container = Vertical()
            self.mount(self._code_block_container)
        for child in list(self._code_block_container.children):
            child.remove()
        _, children = self._render_with_code_blocks(full_text)
        for child in children:
            self._code_block_container.mount(child)

    def _update_display_plain(self, content: Static) -> None:
        content.remove_class('-hidden')
        if self._code_block_container is not None:
            self._code_block_container.remove()
            self._code_block_container = None
        parts = self._build_thoughts_text_parts()
        content.update(Text.assemble(*parts))

    def _update_display(self, *, streaming: bool = False) -> None:
        if not self._thoughts:
            return

        full_text = '\n'.join(self._thoughts)

        try:
            content = self.query_one('#thinking-content', Static)
        except Exception:
            return

        if streaming:
            self.add_class('-streaming')
            self._update_display_streaming(content)
            return

        self.remove_class('-streaming')

        if self._has_code_blocks(full_text):
            self._update_display_with_code_blocks(content, full_text)
        else:
            self._update_display_plain(content)

    def on_mount(self) -> None:
        self._update_display()
