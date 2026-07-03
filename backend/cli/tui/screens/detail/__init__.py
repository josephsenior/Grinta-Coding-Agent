"""Detail screen base and concrete implementations for scan-line cards.

The seven concrete detail screens correspond to:
* ``AgentMessageCard`` → ``MessageDetailScreen``
* ``EditCard`` → ``EditDetailScreen``
* ``ShellCard`` → ``ShellDetailScreen``
* ``CompactionCard`` → ``PayloadDetailScreen``
* ``TerminalCard`` → ``TerminalDetailScreen``
* ``BrowserCard`` → ``BrowserDetailScreen``
* ``DebuggerCard`` → ``DebuggerDetailScreen``
* ``DelegateCard`` / ``MCPCard`` / ``PayloadCard`` → ``PayloadDetailScreen``
* ``AcceptanceCriteriaCard`` → ``AcceptanceCriteriaDetailScreen``
"""

from __future__ import annotations

from backend.cli.tui.screens.detail.acceptance_criteria import (
    AcceptanceCriteriaDetailScreen,
)
from backend.cli.tui.screens.detail.base import DetailScreen
from backend.cli.tui.screens.detail.browser import BrowserDetailScreen
from backend.cli.tui.screens.detail.debugger import DebuggerDetailScreen
from backend.cli.tui.screens.detail.edit import EditDetailScreen
from backend.cli.tui.screens.detail.message import MessageDetailScreen
from backend.cli.tui.screens.detail.payload import PayloadDetailScreen
from backend.cli.tui.screens.detail.shell import ShellDetailScreen
from backend.cli.tui.screens.detail.terminal import TerminalDetailScreen

__all__ = [
    'DetailScreen',
    'AcceptanceCriteriaDetailScreen',
    'MessageDetailScreen',
    'EditDetailScreen',
    'ShellDetailScreen',
    'TerminalDetailScreen',
    'BrowserDetailScreen',
    'DebuggerDetailScreen',
    'PayloadDetailScreen',
]
