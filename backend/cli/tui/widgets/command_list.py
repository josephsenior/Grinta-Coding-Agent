"""Shared command / shortcut list rows for autocomplete and help modals."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Static

# Human-readable descriptions for the help modal (syntax lives in GrintaScreen._SLASH_HINTS).
SLASH_COMMAND_DESCRIPTIONS: dict[str, str] = {
    '/help': 'Show help and keyboard shortcuts',
    '/clear': 'Clear the transcript',
    '/settings': 'Open runtime settings',
    '/mode': 'View or set interaction mode (chat/plan/agent)',
    '/health': 'Run a fast self-check (git, ripgrep, model)',
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


# Aliases so the help dialog shows what the user actually presses, even
# when Textual's binding key string uses symbols or canonical form.
_BINDING_KEY_ALIASES: dict[str, str] = {
    'ctrl+c': 'Ctrl+C',
    'ctrl+shift+c': 'Ctrl+Shift+C',
    'escape': 'Esc',
    'ctrl+l': 'Ctrl+L',
    'ctrl+space': 'Ctrl+Space',
    'ctrl+z': 'Ctrl+Z',
    'tab': 'Tab',
    'enter': 'Enter',
    'pageup': 'PageUp',
    'pagedown': 'PageDown',
    'home': 'Home',
    'end': 'End',
    'ctrl+b': 'Ctrl+B',
    'f1': 'F1',
    'ctrl+j': 'Ctrl+J',
    'ctrl+k': 'Ctrl+K',
    'ctrl+p': 'Ctrl+P',
    'ctrl+n': 'Ctrl+N',
}


def shortcuts_from_bindings(
    bindings: list[tuple[str, str]],
    *,
    also_document: tuple[str, ...] = ('Enter', 'Esc'),
) -> list[tuple[str, str]]:
    """Derive the help-dialog shortcuts list from a (key, action) binding table.

    ``also_document`` is an allowlist of canonical names that should
    always appear even if the binding is ``show=False`` and the action
    isn't user-discoverable from a footer. ``Enter`` and ``Esc`` are the
    most common.
    """
    seen: set[str] = set()
    rows: list[tuple[str, str]] = []
    for key, action in bindings:
        label = _BINDING_KEY_ALIASES.get(key.lower(), key)
        if label in seen:
            continue
        seen.add(label)
        rows.append((label, action))
    for label in also_document:
        if label not in seen:
            seen.add(label)
            rows.append((label, '(see BINDINGS)'))
    return rows


def build_help_shortcuts(
    screen_bindings: list | None = None,
) -> list[tuple[str, str]]:
    """Public entry point — pulls the live bindings from ``GrintaScreen``.

    Falls back to the static ``KEYBOARD_SHORTCUTS`` list if the import
    fails (e.g. when this module is used outside the TUI, like in tests
    that import ``command_list`` without the full app).
    """
    if screen_bindings is None:
        try:
            from backend.cli.tui.app import GrintaScreen

            screen_bindings = GrintaScreen.BINDINGS
        except Exception:
            return list(KEYBOARD_SHORTCUTS)

    bindings_as_tuples: list[tuple[str, str]] = []
    for b in screen_bindings:
        try:
            bindings_as_tuples.append((b.key, b.action))
        except AttributeError:
            bindings_as_tuples.append((b[0], b[1]))
    return shortcuts_from_bindings(
        bindings_as_tuples, also_document=('Enter', 'Esc', 'Tab')
    )


# Slash commands that need arguments before they can run.
_SLASH_COMMANDS_REQUIRING_ARGS = frozenset({'/resume'})


def slash_command_runs_immediately(name: str) -> bool:
    """Return True when a palette pick can execute without extra input."""
    return name not in _SLASH_COMMANDS_REQUIRING_ARGS


class CommandListSection(Static):
    """Section title inside a command list panel."""

    DEFAULT_CSS = """
    CommandListSection {
        width: 100%;
        height: 1;
        margin: 1 0 0 0;
        padding: 0 1;
        color: #5eead4;
    }
    CommandListSection:first-of-type {
        margin-top: 0;
    }
    """


class CommandListRow(Horizontal):
    """Two-column row: command name + usage or description."""

    class Activated(Message):
        """A clickable slash-command row was chosen."""

        def __init__(self, command: str) -> None:
            super().__init__()
            self.command = command

    DEFAULT_CSS = """
    CommandListRow {
        width: 100%;
        height: auto;
        min-height: 1;
        padding: 0 1;
        margin: 0;
    }
    CommandListRow.-activatable {
        height: 1;
    }
    CommandListRow.-activatable:hover {
        background: #0d162a;
    }
    CommandListRow .cmd-name {
        width: 18;
        min-width: 18;
        color: #c8d4e8;
    }
    CommandListRow .cmd-detail {
        width: 1fr;
        color: #8f9fc1;
    }
    CommandListRow.-highlighted .cmd-name {
        color: #e9e9e9;
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
        activatable: bool = False,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._name = name
        self._detail = detail
        self._activatable = activatable
        if highlighted:
            self.add_class('-highlighted')
        if activatable:
            self.add_class('-activatable')
            self.can_focus = True

    def compose(self) -> ComposeResult:
        yield Static(self._name, classes='cmd-name')
        yield Static(self._detail, classes='cmd-detail')

    def on_click(self, event: events.Click) -> None:
        if not self._activatable:
            return
        self.post_message(self.Activated(self._name))
        event.prevent_default()
        event.stop()

    def on_key(self, event: events.Key) -> None:
        if not self._activatable:
            return
        if event.key in ('enter', 'space'):
            self.post_message(self.Activated(self._name))
            event.prevent_default()
            event.stop()


class CommandListPanel(Vertical):
    """Bordered panel matching transcript card polish."""

    DEFAULT_CSS = """
    CommandListPanel {
        width: 100%;
        height: auto;
        background: #08101d;
        border: round #1b233a;
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
            yield CommandListRow(name, detail, activatable=True)


def slash_command_detail(name: str, syntax: str) -> str:
    """Human detail for a slash command without repeating the command label."""
    desc = SLASH_COMMAND_DESCRIPTIONS.get(name, '')
    if syntax == name:
        return desc or name
    if syntax.startswith(name):
        stripped = syntax[len(name) :].lstrip()
        if stripped:
            return stripped
    return desc or syntax


def build_slash_command_rows(hints: dict[str, str]) -> list[tuple[str, str]]:
    """Merge registry syntax hints with human descriptions."""
    rows: list[tuple[str, str]] = []
    for name in sorted(hints):
        rows.append((name, slash_command_detail(name, hints[name])))
    return rows
