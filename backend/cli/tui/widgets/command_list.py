"""Shared command / shortcut list rows for autocomplete and help modals."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

# Human-readable descriptions for the help modal (syntax lives in GrintaScreen._SLASH_HINTS).
SLASH_COMMAND_DESCRIPTIONS: dict[str, str] = {
    '/help': 'Show help and keyboard shortcuts',
    '/clear': 'Clear the transcript',
    '/settings': 'Open runtime settings',
    '/sessions': 'Browse and resume saved sessions',
    '/resume': 'Resume a session by number or id',
    '/quit': 'Exit Grinta',
}

KEYBOARD_SHORTCUTS: list[tuple[str, str]] = [
    ('F1', 'Open help'),
    ('Ctrl+C', 'Interrupt agent or copy selection'),
    ('Ctrl+B', 'Toggle sidebar'),
    ('Ctrl+L', 'Clear transcript'),
    ('Ctrl+Space', 'Autocomplete slash commands'),
    ('PageUp / PageDown', 'Scroll transcript'),
    ('Home / End', 'Jump transcript top / bottom'),
    ('Esc', 'Close modal or dismiss overlay'),
]


class CommandListSection(Static):
    """Section title inside a command list panel."""

    DEFAULT_CSS = """
    CommandListSection {
        width: 100%;
        height: 1;
        margin: 1 0 0 0;
        padding: 0 1;
        color: #91abec;
        text-style: bold;
    }
    CommandListSection:first-of-type {
        margin-top: 0;
    }
    """


class CommandListRow(Horizontal):
    """Two-column row: command name + usage or description."""

    DEFAULT_CSS = """
    CommandListRow {
        width: 100%;
        height: auto;
        min-height: 1;
        padding: 0 1;
        margin: 0;
    }
    CommandListRow .cmd-name {
        width: 18;
        min-width: 18;
        color: #eacb8a;
        text-style: bold;
    }
    CommandListRow .cmd-detail {
        width: 1fr;
        color: #8ea2c8;
    }
    CommandListRow.-highlighted .cmd-name {
        color: #5eead4;
    }
    CommandListRow.-highlighted .cmd-detail {
        color: #c8d4e8;
    }
    """

    def __init__(
        self,
        name: str,
        detail: str,
        *,
        highlighted: bool = False,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._name = name
        self._detail = detail
        if highlighted:
            self.add_class('-highlighted')

    def compose(self) -> ComposeResult:
        yield Static(self._name, classes='cmd-name')
        yield Static(self._detail, classes='cmd-detail')


class CommandListPanel(Vertical):
    """Bordered panel matching transcript card polish."""

    DEFAULT_CSS = """
    CommandListPanel {
        width: 100%;
        height: auto;
        background: #07101d;
        border: round #26324f;
        border-left: heavy #5eead4;
        padding: 1 0;
    }
    """

    def __init__(
        self,
        *,
        rows: list[tuple[str, str]],
        section_title: str | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._rows = rows
        self._section_title = section_title

    def compose(self) -> ComposeResult:
        if self._section_title:
            yield CommandListSection(self._section_title)
        for name, detail in self._rows:
            yield CommandListRow(name, detail)


def build_slash_command_rows(hints: dict[str, str]) -> list[tuple[str, str]]:
    """Merge registry syntax hints with human descriptions."""
    rows: list[tuple[str, str]] = []
    for name in sorted(hints):
        syntax = hints[name]
        desc = SLASH_COMMAND_DESCRIPTIONS.get(name, '')
        detail = syntax if syntax != name else desc
        if desc and syntax != name and desc not in detail:
            detail = f'{desc}  ·  {syntax}'
        rows.append((name, detail))
    return rows
