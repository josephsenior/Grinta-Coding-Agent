"""Textual widgets for the Grinta TUI.

Proper widget implementations replacing the empty shell classes.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Label, Static, TextArea


class TranscriptWidget(VerticalScroll):
    """Scrollable conversation transcript container.

    Uses incremental widget updates instead of rebuilding the entire display.
    Each message, tool call, and reasoning block is a separate widget.
    """

    DEFAULT_CSS = """
    TranscriptWidget {
        width: 100%;
        height: 100%;
        background: #060a14;
        scrollbar-color: #33405d #161e31;
        scrollbar-color-hover: #404f71 #161e31;
        scrollbar-color-active: #4f608a #161e31;
        scrollbar-size: 1 0;
        padding: 1 2;
        overflow-x: hidden;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(id='transcript-content')

    def append_widget(self, widget: Static | Container) -> None:
        """Add a widget to the transcript and scroll to bottom."""
        content = self.query_one('#transcript-content', Static)
        content.mount(widget)
        self.scroll_end(animate=True)

    def clear(self) -> None:
        """Clear all transcript content."""
        content = self.query_one('#transcript-content', Static)
        content.remove_children()


class InfoSidebarWidget(VerticalScroll):
    """Sidebar for Mission Control info (Tasks, MCPs, Skills).

    Displays task list, MCP server status, and available skills.
    """

    DEFAULT_CSS = """
    InfoSidebarWidget {
        width: 100%;
        height: 100%;
        background: #080c18;
        padding: 1 1;
        scrollbar-size: 0 0;
        overflow-y: auto;
        overflow-x: hidden;
    }
    InfoSidebarWidget .sidebar-section {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
    }
    InfoSidebarWidget .sidebar-section-title {
        color: #91abec;
        text-style: bold;
    }
    InfoSidebarWidget .sidebar-section-body {
        color: #969aad;
        margin-left: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._tasks: list[dict[str, str]] = []
        self._mcp_servers: list[dict[str, str]] = []
        self._skill_count: int = 0

    def compose(self) -> ComposeResult:
        yield Static(id='sidebar-content')

    def update_tasks(self, tasks: list[dict[str, str]]) -> None:
        """Update the task list display."""
        self._tasks = tasks
        self._render()

    def update_mcp_servers(self, servers: list[dict[str, str]]) -> None:
        """Update the MCP server display."""
        self._mcp_servers = servers
        self._render()

    def update_skills(self, count: int) -> None:
        """Update the skill count display."""
        self._skill_count = count
        self._render()

    def _render(self) -> None:
        content = self.query_one('#sidebar-content', Static)
        parts: list[str] = []

        # Tasks section
        parts.append('[bold #91abec]Tasks[/]')
        if self._tasks:
            for task in self._tasks:
                status = task.get('status', 'pending')
                status_icon = {
                    'done': '[bold #54efae]✓[/]',
                    'failed': '[bold #fd8383]✗[/]',
                    'running': '[bold #91abec]⟳[/]',
                    'pending': '[dim #969aad]○[/]',
                }.get(status, '○')
                title = task.get('title', task.get('description', 'Untitled'))
                parts.append(f'  {status_icon} {title}')
        else:
            parts.append('  [dim #969aad]No tasks[/]')

        parts.append('')

        # MCP Servers section
        parts.append('[bold #91abec]MCP Servers[/]')
        if self._mcp_servers:
            for server in self._mcp_servers:
                name = server.get('name', 'Unknown')
                server_type = server.get('type', 'active')
                status_icon = '[bold #54efae]●[/]' if server_type == 'active' else '[dim #969aad]○[/]'
                parts.append(f'  {status_icon} {name}')
        else:
            parts.append('  [dim #969aad]None configured[/]')

        parts.append('')

        # Skills section
        parts.append('[bold #91abec]Skills[/]')
        parts.append(f'  [dim #969aad]{self._skill_count} available[/]')

        content.update('\n'.join(parts))


class InputBarWidget(Horizontal):
    """Bottom input row with spinner and TextArea.

    Handles user input with proper focus management and submission.
    """

    DEFAULT_CSS = """
    InputBarWidget {
        width: 100%;
        height: 4;
        background: #0d1a2d;
        border-top: solid #1b233a;
        padding: 0 2;
        layout: horizontal;
    }
    InputBarWidget.processing {
        border-top: solid #91abec;
    }
    InputBarWidget TextArea {
        background: #16263d;
        color: #c8d4e8;
        border: none;
        padding: 0 1;
        width: 1fr;
        height: 3;
    }
    InputBarWidget #spinner {
        width: 3;
        height: 3;
        content-align: center middle;
        color: #91abec;
        margin-right: 1;
    }
    InputBarWidget #spinner.-hidden {
        display: none;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(id='spinner', classes='-hidden')
        yield TextArea(id='input', show_line_numbers=False)

    def set_processing(self, processing: bool) -> None:
        """Show/hide processing state."""
        spinner = self.query_one('#spinner', Static)
        if processing:
            spinner.remove_class('-hidden')
            spinner.update('⟳')
            self.add_class('processing')
        else:
            spinner.add_class('-hidden')
            self.remove_class('processing')

    def get_input(self) -> str:
        """Get the current input text."""
        ta = self.query_one('#input', TextArea)
        return ta.text.strip()

    def clear_input(self) -> None:
        """Clear the input field."""
        ta = self.query_one('#input', TextArea)
        ta.clear()

    def focus_input(self) -> None:
        """Focus the input field."""
        ta = self.query_one('#input', TextArea)
        ta.focus()


class HUDBarWidget(Container):
    """Multi-line status bar widget.

    Replaces the old HUD class with a proper Textual widget.
    """

    DEFAULT_CSS = """
    HUDBarWidget {
        width: 100%;
        height: auto;
        background: #0a1525;
        color: #969aad;
        padding: 1 2 0 2;
    }
    HUDBarWidget #hud-line-1 {
        width: 100%;
        height: 1;
        text-style: bold;
    }
    HUDBarWidget #hud-line-2 {
        width: 100%;
        height: 1;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label(id='hud-line-1')
        yield Label(id='hud-line-2')

    def update_line1(self, text: str) -> None:
        """Update the first HUD line."""
        self.query_one('#hud-line-1', Label).update(text)

    def update_line2(self, text: str) -> None:
        """Update the second HUD line."""
        self.query_one('#hud-line-2', Label).update(text)
