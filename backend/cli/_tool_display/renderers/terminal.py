"""Terminal tool renderers.

Terminal-style panels for terminal_read, terminal_input, and terminal output.
"""

from __future__ import annotations

from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from backend.cli.theme import (
    CLR_CARD_BORDER,
    CLR_STATUS_OK,
    NAVY_TEXT_DIM,
    NAVY_TEXT_MUTED,
    NAVY_TEXT_PRIMARY,
)


def render_terminal_read(session_id: str = '') -> Panel:
    """Render a terminal read action as a compact panel."""
    content_parts = [Text('Reading terminal output', style=NAVY_TEXT_PRIMARY)]
    if session_id:
        content_parts.append(Text(f'Session: {session_id}', style=NAVY_TEXT_DIM))

    panel_title = Text('Terminal Read', style='bold #f6ff8f')
    return Panel(
        Group(*content_parts),
        title=panel_title,
        title_align='left',
        border_style=CLR_CARD_BORDER,
        padding=(0, 2),
    )


def _build_terminal_content(content: str) -> list[Text]:
    lines: list[Text] = []
    all_lines = content.splitlines()
    preview = all_lines[:15]
    for line in preview:
        if len(line) > 120:
            line = line[:117] + '\u2026'
        lines.append(Text(line, style=NAVY_TEXT_MUTED))
    if len(all_lines) > 15:
        lines.append(
            Text(f'... {len(all_lines) - 15} more lines', style=NAVY_TEXT_DIM)
        )
    return lines


def _build_terminal_meta(exit_code: int | None) -> Text | None:
    if exit_code is None:
        return None
    style = CLR_STATUS_OK if exit_code == 0 else '#fd8383'
    meta_line = Text()
    meta_line.append(f'exit {exit_code}', style=style)
    return meta_line


def render_terminal_output(
    content: str, session_id: str = '', exit_code: int | None = None
) -> Panel:
    """Render terminal output with session info."""
    content_parts = []

    if session_id:
        content_parts.append(Text(f'Session: {session_id}', style=NAVY_TEXT_DIM))

    if content:
        content_parts.extend(_build_terminal_content(content))

    meta = _build_terminal_meta(exit_code)
    if meta:
        content_parts.append(Text(''))
        content_parts.append(meta)

    panel_title = Text('Terminal', style='bold #f6ff8f')
    return Panel(
        Group(*content_parts)
        if content_parts
        else Text('(no output)', style=NAVY_TEXT_DIM),
        title=panel_title,
        title_align='left',
        border_style=CLR_CARD_BORDER,
        padding=(0, 2),
    )


def render_browser_screenshot(url: str = '') -> Panel:
    """Render a browser screenshot capture as a panel."""
    content_parts = [Text('Screenshot captured', style=NAVY_TEXT_PRIMARY)]
    if url:
        content_parts.append(Text(f'URL: {url}', style=NAVY_TEXT_DIM))

    panel_title = Text('Browser', style='bold #00e5ff')
    return Panel(
        Group(*content_parts),
        title=panel_title,
        title_align='left',
        border_style=CLR_CARD_BORDER,
        padding=(0, 2),
    )


def render_lsp_result(content: str, symbol: str = '') -> Panel:
    """Render LSP query results."""
    content_parts = []

    if symbol:
        content_parts.append(Text(f'Symbol: {symbol}', style=NAVY_TEXT_PRIMARY))

    if content:
        lines = content.splitlines()[:10]
        for line in lines:
            if len(line) > 120:
                line = line[:117] + '…'
            content_parts.append(Text(line, style=NAVY_TEXT_MUTED))

        if len(content.splitlines()) > 10:
            content_parts.append(
                Text(
                    f'... {len(content.splitlines()) - 10} more lines',
                    style=NAVY_TEXT_DIM,
                )
            )

    panel_title = Text('LSP', style='bold #60a5fa')
    return Panel(
        Group(*content_parts)
        if content_parts
        else Text('(no results)', style=NAVY_TEXT_DIM),
        title=panel_title,
        title_align='left',
        border_style=CLR_CARD_BORDER,
        padding=(0, 2),
    )


def render_delegation_action(task: str, worker: str = '') -> Panel:
    """Render a delegation action."""
    content_parts = [Text(task[:200], style=NAVY_TEXT_PRIMARY)]
    if worker:
        content_parts.append(Text(f'Worker: {worker}', style=NAVY_TEXT_DIM))

    panel_title = Text('Delegating', style='bold #4ade80')
    return Panel(
        Group(*content_parts),
        title=panel_title,
        title_align='left',
        border_style=CLR_CARD_BORDER,
        padding=(0, 2),
    )


def render_delegation_result(content: str) -> Panel:
    """Render delegation result."""
    content_parts = []

    if content:
        lines = content.splitlines()[:8]
        for line in lines:
            if len(line) > 120:
                line = line[:117] + '…'
            content_parts.append(Text(line, style=NAVY_TEXT_MUTED))

        if len(content.splitlines()) > 8:
            content_parts.append(
                Text(
                    f'... {len(content.splitlines()) - 8} more lines',
                    style=NAVY_TEXT_DIM,
                )
            )

    panel_title = Text('Delegation Result', style='bold #4ade80')
    return Panel(
        Group(*content_parts)
        if content_parts
        else Text('(no output)', style=NAVY_TEXT_DIM),
        title=panel_title,
        title_align='left',
        border_style=CLR_CARD_BORDER,
        padding=(0, 2),
    )


def render_condensation_action() -> Panel:
    """Render context condensation action."""
    content_parts = [
        Text('Compressing conversation history...', style=NAVY_TEXT_PRIMARY)
    ]

    panel_title = Text('Condensing', style='bold #91abec')
    return Panel(
        Group(*content_parts),
        title=panel_title,
        title_align='left',
        border_style=CLR_CARD_BORDER,
        padding=(0, 2),
    )


def render_condensation_complete() -> Panel:
    """Render context condensation complete."""
    content_parts = [Text('Context compressed successfully', style=NAVY_TEXT_PRIMARY)]

    panel_title = Text('Condensed', style='bold #54efae')
    return Panel(
        Group(*content_parts),
        title=panel_title,
        title_align='left',
        border_style=CLR_CARD_BORDER,
        padding=(0, 2),
    )


def render_user_reject() -> Panel:
    """Render user rejection."""
    content_parts = [Text('Action rejected by user', style='#fd8383')]

    panel_title = Text('Rejected', style='bold #fd8383')
    return Panel(
        Group(*content_parts),
        title=panel_title,
        title_align='left',
        border_style='#fd8383',
        padding=(0, 2),
    )


def render_server_ready() -> Panel:
    """Render server ready status."""
    content_parts = [
        Text('Server is ready and accepting connections', style=NAVY_TEXT_PRIMARY)
    ]

    panel_title = Text('Server Ready', style='bold #54efae')
    return Panel(
        Group(*content_parts),
        title=panel_title,
        title_align='left',
        border_style=CLR_CARD_BORDER,
        padding=(0, 2),
    )


def render_file_download(url: str) -> Panel:
    """Render file download action."""
    content_parts = [Text(f'URL: {url}', style=NAVY_TEXT_PRIMARY)]

    panel_title = Text('Download', style='bold #91abec')
    return Panel(
        Group(*content_parts),
        title=panel_title,
        title_align='left',
        border_style=CLR_CARD_BORDER,
        padding=(0, 2),
    )
