"""MCP server management dialog."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Label

from backend.cli.settings import (
    add_mcp_server,
    get_mcp_server,
    get_mcp_servers,
    mcp_server_endpoint,
    remove_mcp_server,
    update_mcp_server,
)
from backend.cli.tui.dialogs.add_mcp import GrintaAddMCPDialog
from backend.cli.tui.dialogs.confirm import GrintaConfirmDialog
from backend.cli.tui.widgets.dialogs import ModalDialog
from backend.core.config import AppConfig, load_app_config
from backend.integrations.mcp.native_backends import is_user_visible_mcp_server


class GrintaManageMCPDialog(ModalDialog[bool]):
    """List, add, edit, and remove MCP servers.

    The dialog persists mutations via :mod:`backend.cli.settings.mcp`
    which emits an :class:`MCPConfigChange` on the bus. The runtime
    subscribes to that bus and reconciles its live client pool, so
    the dialog only needs to:

    * call the mutator;
    * re-read ``AppConfig`` and refresh the table;
    * subscribe to the bus while mounted so the *Reload* / external-edit
      feedback lands in the status row.
    """

    DEFAULT_CSS = """
    GrintaManageMCPDialog #mcp-panel {
        height: auto;
        margin-top: 1;
        background: #08101d;
        border: round #1b233a;
        border-left: heavy #eacb8a;
        padding: 0;
    }
    GrintaManageMCPDialog #mcp-table {
        height: 12;
        margin: 0;
        border: none;
        background: transparent;
    }
    """

    BINDINGS = [
        *ModalDialog.BINDINGS,
        Binding('enter', 'edit_selected', 'Edit', show=False),
        Binding('delete', 'delete_selected', 'Delete', show=False),
    ]

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config
        self._changed = False
        self._servers: list[dict[str, Any]] = []
        self._bus_unsubscribe: Any = None

    def compose(self) -> ComposeResult:
        with Vertical(id='dialog-container'):
            yield Label('MCP Servers', id='dialog-title')
            with Vertical(id='mcp-panel'):
                yield DataTable(id='mcp-table', zebra_stripes=False)
            yield Label('', id='dialog-feedback')
            with Horizontal(id='dialog-buttons'):
                yield Button('Add', id='mcp-add', variant='primary')
                yield Button('Edit', id='mcp-edit')
                yield Button('Delete', id='mcp-delete', variant='error')
                yield Button('Reload', id='mcp-reload')
                yield Button('Close', id='mcp-close')

    def on_mount(self) -> None:
        table = self.query_one('#mcp-table', DataTable)
        table.cursor_type = 'row'
        table.add_columns('Name', 'Command or URL')
        self._refresh_table()
        self._subscribe_bus()

    def on_unmount(self) -> None:
        unsub = self._bus_unsubscribe
        if callable(unsub):
            try:
                unsub()
            except Exception:
                pass
        self._bus_unsubscribe = None

    def _subscribe_bus(self) -> None:
        from backend.integrations.mcp.config_bus import get_mcp_config_bus

        def _on_change(change: Any) -> None:
            summary = _format_change_summary(change)
            if not summary:
                return
            try:
                self._set_feedback(summary)
            except Exception:
                pass

        self._bus_unsubscribe = get_mcp_config_bus().subscribe(_on_change)

    def action_edit_selected(self) -> None:
        self.run_worker(self._edit_server(), exclusive=True)

    def action_delete_selected(self) -> None:
        self.run_worker(self._delete_server(), exclusive=True)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.query_one('#dialog-feedback', Label).update('')

    def on_data_table_row_double_clicked(
        self, event: DataTable.RowDoubleClicked
    ) -> None:
        self.run_worker(self._edit_server(), exclusive=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == 'mcp-close':
            self.dismiss(self._changed)
            return
        if bid == 'mcp-add':
            self.run_worker(self._add_server(), exclusive=True)
            return
        if bid == 'mcp-edit':
            self.run_worker(self._edit_server(), exclusive=True)
            return
        if bid == 'mcp-delete':
            self.run_worker(self._delete_server(), exclusive=True)
            return
        if bid == 'mcp-reload':
            self.run_worker(self._manual_reload(), exclusive=True)
            return

    def _set_feedback(self, message: str, *, error: bool = False) -> None:
        color = '#f05757' if error else '#5eead4'
        self.query_one('#dialog-feedback', Label).update(f'[{color}]{message}[/]')

    def _existing_names(self) -> set[str]:
        return {str(s.get('name') or '') for s in get_mcp_servers(self._config)}

    def _selected_name(self) -> str | None:
        if not self._servers:
            return None
        table = self.query_one('#mcp-table', DataTable)
        row_index = table.cursor_row
        if row_index is None or row_index < 0 or row_index >= len(self._servers):
            return None
        return str(self._servers[row_index].get('name') or '') or None

    def _reload_config(self) -> None:
        self._config = load_app_config()

    def _refresh_table(self) -> None:
        self._reload_config()
        self._servers = get_mcp_servers(self._config)
        table = self.query_one('#mcp-table', DataTable)
        table.clear()
        if not self._servers:
            table.add_row('(none configured)', '')
            return
        for server in self._servers:
            endpoint = server.get('url') or server.get('command') or ''
            table.add_row(server.get('name', '?'), str(endpoint))

    async def _manual_reload(self) -> None:
        """Force the runtime to re-read ``settings.json`` and reconcile.

        Useful after the user hand-edited the file in another window or
        when the file watcher missed a change (e.g. shared mount with
        coarse mtime resolution). Re-emits the current config on the
        bus with source ``"manual"`` so the runtime picks it up.
        """
        try:
            from backend.cli.settings.storage import _load_raw_settings
            from backend.core.config.mcp_config import MCPConfig, MCPServerConfig
            from backend.integrations.mcp.config_bus import get_mcp_config_bus

            data = _load_raw_settings()
            mcp_cfg = data.get('mcp_config') or {}
            if not isinstance(mcp_cfg, dict):
                mcp_cfg = {}
            raw_servers = mcp_cfg.get('servers', [])
            if isinstance(raw_servers, dict):
                raw_servers = [raw_servers]
            servers: list[MCPServerConfig] = []
            for row in raw_servers or []:
                if not isinstance(row, dict):
                    continue
                name = row.get('name')
                if not name or name == 'default':
                    continue
                servers.append(MCPServerConfig(**{**row, 'name': name}))
            new_config = MCPConfig(
                enabled=bool(mcp_cfg.get('enabled', True)),
                servers=servers,
                mcp_exposed_name_reserved=frozenset(
                    mcp_cfg.get('mcp_exposed_name_reserved', []) or []
                ),
            )
            get_mcp_config_bus().emit(new_config, source='manual')
            self._set_feedback('Reload requested.')
        except Exception as exc:
            self._set_feedback(f'Reload failed: {exc}', error=True)

    async def _add_server(self) -> None:
        result = await self.app.push_screen_wait(
            GrintaAddMCPDialog(existing_names=self._existing_names())
        )
        if not result:
            return
        try:
            add_mcp_server(result['name'], command=result['command'])
        except Exception as exc:
            self._set_feedback(str(exc), error=True)
            return
        self._changed = True
        self._refresh_table()
        self._set_feedback(f'Added {result["name"]}.')

    async def _edit_server(self) -> None:
        name = self._selected_name()
        if not name:
            self._set_feedback('Select a server first.', error=True)
            return
        server = get_mcp_server(self._config, name)
        if server is None:
            self._set_feedback(f'Server not found: {name}', error=True)
            return
        result = await self.app.push_screen_wait(
            GrintaAddMCPDialog(
                existing_names=self._existing_names(),
                edit_name=name,
                edit_command=mcp_server_endpoint(server),
            )
        )
        if not result:
            return
        try:
            update_mcp_server(name, command=result['command'], config=self._config)
        except Exception as exc:
            self._set_feedback(str(exc), error=True)
            return
        self._changed = True
        self._refresh_table()
        self._set_feedback(f'Updated {name}.')

    async def _delete_server(self) -> None:
        name = self._selected_name()
        if not name:
            self._set_feedback('Select a server first.', error=True)
            return
        if not is_user_visible_mcp_server(name):
            self._set_feedback(f"'{name}' cannot be removed.", error=True)
            return
        result = await self.app.push_screen_wait(
            GrintaConfirmDialog(
                title='Delete MCP Server',
                body=f"Remove '{name}'?",
                options=[('cancel', 'Cancel'), ('delete', 'Remove')],
            )
        )
        if result != 'delete':
            return
        try:
            remove_mcp_server(name)
        except Exception as exc:
            self._set_feedback(str(exc), error=True)
            return
        self._changed = True
        self._refresh_table()
        self._set_feedback(f'Removed {name}.')


def _format_change_summary(change: Any) -> str:
    """Render a one-line human summary of a bus change.

    Returns an empty string when there is nothing to report (e.g. the
    change touched only non-MCP settings). The format mirrors the
    Cline/Cursor diff notation so muscle memory carries over.
    """
    diff = getattr(change, 'diff', None)
    if diff is None or not diff.has_changes:
        return ''
    added = list(getattr(diff, 'added', []) or [])
    removed = list(getattr(diff, 'removed', []) or [])
    changed = dict(getattr(diff, 'changed', {}) or {})
    parts: list[str] = []
    if added:
        parts.append('+ ' + ', '.join(s.name for s in added))
    if removed:
        parts.append('- ' + ', '.join(s.name for s in removed))
    if changed:
        parts.append('~ ' + ', '.join(old.name for old, _ in changed.values()))
    if not parts:
        return ''
    return 'Reloaded: ' + ' | '.join(parts)
