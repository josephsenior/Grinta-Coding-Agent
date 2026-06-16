"""ActivityCard widget — compact tool/shell/file activity rows."""

from __future__ import annotations

import json
from typing import Any

from rich.syntax import Syntax
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
from backend.cli.tui.helpers import infer_display_shell_kind
from backend.cli.tui.widgets.activity_card.diff_lines import (
    DiffLine,
    SplitDiffLine,
    _decode_diff_line,
    _decode_split_diff_line,
    _format_file_delta_outcome,
)
from backend.cli.tui.widgets.terminal_pane import TerminalPane


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
    ActivityCard.-category-terminal,
    ActivityCard.-category-debugger {
        border: round #24385c;
        background: #050913;
    }
    ActivityCard.-category-shell.-running,
    ActivityCard.-category-terminal.-running,
    ActivityCard.-category-debugger.-running {
        border-left: heavy #5eead4;
    }
    ActivityCard.-expanded.-category-shell,
    ActivityCard.-expanded.-category-terminal,
    ActivityCard.-expanded.-category-debugger {
        border: round #24385c;
        padding: 0;
    }
    ActivityCard.-collapsed.-category-shell .card-collapsed-text,
    ActivityCard.-collapsed.-category-terminal .card-collapsed-text,
    ActivityCard.-collapsed.-category-debugger .card-collapsed-text {
        color: #cbd5e1;
    }
    ActivityCard.-category-grep,
    ActivityCard.-category-glob,
    ActivityCard.-category-search,
    ActivityCard.-category-find_symbols,
    ActivityCard.-category-read_symbols,
    ActivityCard.-category-analyze {
        border: round #2d4a6a;
        background: #050c14;
    }
    ActivityCard.-category-web_search,
    ActivityCard.-category-web_fetch {
        border: round #3a4a6a;
        background: #060d18;
    }
    ActivityCard.-category-browser {
        border: round #3d5a4a;
        background: #060f0c;
    }
    ActivityCard.-category-mcp {
        border: round #3a3d5a;
        background: #080a14;
    }
    ActivityCard.-collapsed {
        border: none;
        border-left: solid #1b233a;
        padding: 0 1 0 1;
    }
    ActivityCard.-collapsed:focus {
        border-left: solid #4a5f99;
    }
    ActivityCard.-collapsed:hover {
        border-left: solid #26365b;
    }
    ActivityCard.-collapsed.-category-shell,
    ActivityCard.-collapsed.-category-terminal,
    ActivityCard.-collapsed.-category-debugger {
        border-left: solid #24385c;
    }
    ActivityCard.-collapsed.-category-grep,
    ActivityCard.-collapsed.-category-glob,
    ActivityCard.-collapsed.-category-search,
    ActivityCard.-collapsed.-category-find_symbols,
    ActivityCard.-collapsed.-category-read_symbols,
    ActivityCard.-collapsed.-category-analyze {
        border-left: solid #2d4a6a;
    }
    ActivityCard.-collapsed.-category-web_search,
    ActivityCard.-collapsed.-category-web_fetch {
        border-left: solid #3a4a6a;
    }
    ActivityCard.-collapsed.-category-browser {
        border-left: solid #3d5a4a;
    }
    ActivityCard.-collapsed.-category-mcp {
        border-left: solid #3a3d5a;
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
    ActivityCard.-pinned {
        border-left: heavy #f6ff8f;
    }
    ActivityCard.-collapsed.-pinned {
        border-left: heavy #f6ff8f;
    }
    ActivityCard .card-pin {
        width: 2;
        height: 1;
        content-align: center middle;
        color: #f6ff8f;
    }
    ActivityCard .card-pin.-hidden {
        display: none;
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
        ('p', 'toggle_pin', 'Pin card'),
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
        shell_kind: str | None = None,
        terminal_command: str | None = None,
        terminal_cwd: str | None = None,
        terminal_session_id: str | None = None,
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
        self._terminal_command = terminal_command or self._command_from_detail(detail)
        self._shell_kind = shell_kind or self._default_shell_kind()
        self._terminal_cwd = terminal_cwd
        self._terminal_session_id = terminal_session_id or ''
        self._terminal_exit_code: int | None = None
        self._terminal_pane: TerminalPane | None = None
        self._pinned = False
        self._output_tail = ''
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

    @staticmethod
    def _command_from_detail(detail: str) -> str:
        text = (detail or '').strip()
        if text.startswith('$ '):
            return text[2:].strip()
        return text

    def _default_shell_kind(self) -> str:
        if self._badge_category == 'terminal':
            return 'terminal'
        if self._badge_category == 'debugger':
            return 'debugger'
        if self._badge_category == 'shell':
            return infer_display_shell_kind(self._terminal_command)
        return 'bash'

    def _is_terminal_card(self) -> bool:
        return self._badge_category in {'shell', 'terminal', 'debugger'}

    def _sync_running_class(self) -> None:
        if not self._is_terminal_card():
            return
        if self.processing:
            self.add_class('-running')
        else:
            self.remove_class('-running')

    @property
    def is_pinned(self) -> bool:
        return self._pinned

    def should_auto_expand(self) -> bool:
        if not self._collapsible:
            return False
        if self._is_terminal_card():
            return True
        return bool(self._extra_content) or self.processing

    def _refresh_output_tail(self) -> None:
        if not self._is_terminal_card():
            return
        lines = [
            line for line in (self._extra_content or '').splitlines() if line.strip()
        ]
        self._output_tail = lines[-1][:100] if lines else ''

    def set_pinned(self, pinned: bool) -> None:
        self._pinned = pinned
        if pinned:
            self.add_class('-pinned')
            self.expand()
        else:
            self.remove_class('-pinned')
        self._sync_pin_indicator()
        try:
            collapsed = self.query_one('#collapsed-row', Static)
            collapsed.update(self._build_collapsed_markup())
        except Exception:
            pass

    def toggle_pin(self) -> None:
        self.set_pinned(not self._pinned)

    def action_toggle_pin(self) -> None:
        self.toggle_pin()

    def _sync_pin_indicator(self) -> None:
        try:
            pin = self.query_one('#pin-indicator', Static)
            pin.set_class('-hidden', not self._pinned)
        except Exception:
            pass

    def configure_terminal(
        self,
        *,
        command: str | None = None,
        cwd: str | None = None,
        session_id: str | None = None,
        shell_kind: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        """Update embedded terminal chrome metadata."""
        if command is not None:
            self._terminal_command = command.strip()
        if cwd is not None:
            self._terminal_cwd = cwd.strip() or None
        if session_id is not None:
            self._terminal_session_id = session_id.strip()
        if shell_kind is not None:
            self._shell_kind = shell_kind
        if exit_code is not None:
            self._terminal_exit_code = exit_code
        if self._terminal_pane is not None and self.is_mounted:
            self._apply_terminal_pane_state(self._terminal_pane)

    def _terminal_footer_text(self) -> str:
        parts: list[str] = []
        if self._terminal_cwd:
            parts.append(f'cwd: {self._terminal_cwd}')
        if self._terminal_exit_code is not None:
            parts.append(f'exit {self._terminal_exit_code}')
        elif self.processing:
            parts.append('running')
        if self._outcome and self._terminal_exit_code is None:
            parts.append(self._outcome)
        return ' · '.join(parts)

    def _ensure_terminal_pane(self, body: Container) -> TerminalPane:
        if self._terminal_pane is not None:
            return self._terminal_pane
        try:
            pane = body.query_one('#terminal-pane', TerminalPane)
            self._terminal_pane = pane
            self._apply_terminal_pane_state(pane)
            return pane
        except Exception:
            pass
        pane = TerminalPane(
            shell_kind=self._shell_kind,
            command=self._terminal_command,
            cwd=self._terminal_cwd,
            session_id=self._terminal_session_id,
            footer=self._terminal_footer_text(),
            running=self.processing,
            id='terminal-pane',
        )
        body.remove_children()
        body.mount(pane)
        self._terminal_pane = pane
        self._apply_terminal_pane_state(pane)
        return pane

    def _apply_terminal_pane_state(self, pane: TerminalPane) -> None:
        pane.set_shell_kind(self._shell_kind)
        pane.set_command(self._terminal_command)
        pane.set_cwd(self._terminal_cwd)
        pane.set_session_id(self._terminal_session_id)
        pane.set_footer(self._terminal_footer_text())
        pane.set_running(self.processing)
        if self._extra_content:
            pane.set_output(self._extra_content)

    def _mount_terminal_body(self, body: Container) -> None:
        pane = self._ensure_terminal_pane(body)
        pane.set_output(self._extra_content or '')
        body.display = not self._collapsed

    def set_processing(self, processing: bool) -> None:
        """Set the card processing status."""
        self.processing = processing
        if processing and self._status == 'neutral':
            self._status = 'running'
        elif not processing and self._status == 'running':
            self._status = 'neutral'
        self._sync_running_class()
        if self._terminal_pane is not None:
            self._terminal_pane.set_running(processing)
            self._terminal_pane.set_footer(self._terminal_footer_text())
        if processing and self.should_auto_expand():
            self.expand()
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
        if status in {'err', 'warn'} and self._collapsible:
            self.expand()
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

        if self._is_terminal_card() and self._badge_category != 'debugger':
            command = self._terminal_command or self._command_from_detail(self._detail)
            if self._shell_kind == 'pwsh':
                prompt = f'[#7dd3fc]PS>[/] [#e2e8f0]{command}[/]'
            else:
                prompt = f'[#54efae]$[/] [#e2e8f0]{command}[/]'
            detail_part = prompt
        else:
            verb_part = f'[{NAVY_BRAND}]{self._verb}[/]'
            detail_part = f'{verb_part}  {self._detail}'

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

        tail_part = ''
        if (
            self._is_terminal_card()
            and not self.processing
            and self._output_tail
            and self._collapsed
        ):
            tail = self._output_tail
            if len(tail) > 72:
                tail = tail[:69] + '...'
            tail_part = f'  [#54597b]{tail}[/]'

        pin_part = ' [#f6ff8f]📌[/]' if self._pinned else ''
        return f'{pulse}{icon_part} {detail_part}{outcome_part}{tail_part}{pin_part}'

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
            yield Static('📌', id='pin-indicator', classes='card-pin -hidden')
            if self._collapsible:
                yield Static(self._caret_char(), id='caret', classes='card-caret')

        if self._extra_content:
            with Container(classes='card-expanded-body', id='expanded-body'):
                if self._is_terminal_card():
                    yield TerminalPane(
                        shell_kind=self._shell_kind,
                        command=self._terminal_command,
                        cwd=self._terminal_cwd,
                        session_id=self._terminal_session_id,
                        footer=self._terminal_footer_text(),
                        running=self.processing,
                        id='terminal-pane',
                    )
                else:
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
        try:
            self._terminal_pane = self.query_one('#terminal-pane', TerminalPane)
        except Exception:
            self._terminal_pane = None
        if self._terminal_pane is not None and self._extra_content:
            self._terminal_pane.set_output(self._extra_content)
        self._refresh_output_tail()
        self._sync_running_class()
        self._sync_pin_indicator()
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
        if self._pinned:
            return
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
        from backend.cli.tui.constants import _TUI_TERMINAL_DISPLAY_LINE_CAP

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
        self._refresh_output_tail()
        self.can_focus = True
        self._ensure_collapsible_for_extra()
        if not self.is_mounted:
            return
        try:
            collapsed = self.query_one('#collapsed-row', Static)
            collapsed.update(self._build_collapsed_markup())
        except Exception:
            pass
        if self._is_terminal_card():
            try:
                body = self.query_one('#expanded-body', Container)
                pane = self._ensure_terminal_pane(body)
                pane.append_output(chunk)
                body.display = not self._collapsed
            except Exception:
                pass
            return
        try:
            body = self.query_one('#expanded-body', Container)
            self._mount_incremental_tail(body)
        except Exception:
            pass

    def update_content(self, extra_content: str) -> None:
        """Update or set the extra content."""
        self._extra_content = extra_content
        self._refresh_output_tail()
        self.can_focus = True
        if extra_content:
            self._ensure_collapsible_for_extra()
        if not self.is_mounted:
            return

        try:
            body = self.query_one('#expanded-body', Container)
            if self._is_terminal_card():
                pane = self._ensure_terminal_pane(body)
                pane.set_output(extra_content or '')
                pane.set_footer(self._terminal_footer_text())
                body.display = not self._collapsed
                return
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

    def set_diff_encoded(self, diff_encoded: bool) -> None:
        """Switch expanded body rendering to the unified diff widget."""
        if self._diff_encoded == diff_encoded:
            return
        self._diff_encoded = diff_encoded
        if diff_encoded:
            self._syntax_language = 'diff'
        if not self.is_mounted or not self._extra_content:
            return
        self._ensure_collapsible_for_extra()
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
