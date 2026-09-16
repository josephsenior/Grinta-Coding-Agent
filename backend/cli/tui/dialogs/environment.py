"""Environment modal — MCP servers, LSP servers, debug adapters, and skills.

These four panels used to be permanent sidebar columns, showing "Disabled" for
the whole session when a feature wasn't in use. They're per-session capability
info you check occasionally, not live state you need glanceable — so they live
here now, opened on demand, and the transcript gets the full terminal width by
default. Tasks stayed out of this dialog on purpose: unlike these four, task
progress changes while the agent works and belongs in the HUD line instead
(see backend/cli/tui/dialogs/tasks.py).

The section widgets and their edit/toggle wiring are the same
``CollapsibleSection`` machinery the old sidebar used — this dialog is a new
home for them, not a new implementation. Data and mutation logic (toggling
MCP/LSP/debugger, opening the MCP/skills manage dialogs) is delegated back to
the owning ``TUIRenderer`` and ``GrintaScreen`` so there's exactly one
implementation of "how do you toggle LSP" in the app.
"""

from __future__ import annotations

from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label

from backend.cli.theme import (
    NAVY_DOMAIN_MCP,
    NAVY_DOMAIN_SKILLS,
    NAVY_FOCUS_ACCENT,
    NAVY_RUNNING,
)
from backend.cli.tui.widgets.collapsible import CollapsibleSection, SidebarRow
from backend.cli.tui.widgets.dialogs import ModalDialog
from backend.cli.tui.widgets.small import InfoSidebar


class GrintaEnvironmentDialog(ModalDialog[None]):
    """MCP / LSP / Debug Adapters / Skills — capability info, checked on demand."""

    DEFAULT_CSS = """
    GrintaEnvironmentDialog > #dialog-container {
        width: 66;
        max-width: 92%;
        height: auto;
        max-height: 90%;
    }
    GrintaEnvironmentDialog #env-body {
        height: auto;
        max-height: 40;
        overflow-y: auto;
        scrollbar-size-vertical: 1;
        scrollbar-color: #64748b #0f172a;
    }
    """

    def __init__(self, renderer: Any) -> None:
        super().__init__()
        self._renderer = renderer
        self._screen = renderer._tui

    def compose(self) -> ComposeResult:
        with Vertical(id='dialog-container'):
            yield Label('Environment', id='dialog-title')
            with InfoSidebar(id='env-body'):
                yield CollapsibleSection(
                    title='MCP Servers',
                    content='Loading MCP servers...',
                    collapsed=False,
                    accent_color=NAVY_DOMAIN_MCP,
                    section_icon='⬡',
                    action_label='Edit',
                    action_button_class='-mcp',
                    id='env-mcp',
                )
                yield CollapsibleSection(
                    title='LSP Servers',
                    content='Scanning local PATH...',
                    collapsed=False,
                    accent_color=NAVY_FOCUS_ACCENT,
                    section_icon='◈',
                    id='env-lsp',
                )
                yield CollapsibleSection(
                    title='Debug Adapters',
                    content='Scanning local PATH...',
                    collapsed=False,
                    accent_color=NAVY_RUNNING,
                    section_icon='◆',
                    id='env-dap',
                )
                yield CollapsibleSection(
                    title='Skills',
                    content='Loading skills...',
                    collapsed=False,
                    accent_color=NAVY_DOMAIN_SKILLS,
                    section_icon='✦',
                    action_label='Edit',
                    action_button_class='-skill',
                    id='env-skills',
                )

    def on_mount(self) -> None:
        self.refresh_sections()

    def refresh_sections(self) -> None:
        """Rebuild every section from current config/cache state.

        Called on open and after any toggle or manage-dialog change. These
        panels are read fresh each time rather than kept live while the
        modal is closed — cheap, since they're config snapshots, not
        something that needs a background refresh loop.
        """
        renderer = self._renderer

        mcp_section = self.query_one('#env-mcp', CollapsibleSection)
        if renderer._sidebar_mcp_enabled():
            mcp_count = renderer._hud.state.mcp_servers
            mcp_servers = renderer._resolve_mcp_server_list(mcp_count) or []
            mcp_section.set_title(f'MCP Servers ({len(mcp_servers)})')
            mcp_section._content = 'No servers configured'
            mcp_section.set_items(renderer._build_mcp_sidebar_items(mcp_servers))
            mcp_section.set_feature_enabled(True)
        else:
            mcp_section.set_title('MCP Servers')
            mcp_section.set_content('Disabled')
            mcp_section.set_feature_enabled(False)

        lsp_section = self.query_one('#env-lsp', CollapsibleSection)
        if renderer._sidebar_lsp_enabled():
            cache = getattr(renderer, '_lsp_servers_cache', None)
            if cache is None:
                lsp_section.set_title('LSP Servers')
                lsp_section.set_content('Scanning local PATH...')
            else:
                items = renderer._build_lsp_sidebar_items(cache)
                lsp_section.set_title(f'LSP Servers ({len(items)})')
                lsp_section._content = 'No language servers detected on PATH'
                lsp_section.set_items(items)
            lsp_section.set_feature_enabled(True)
        else:
            lsp_section.set_title('LSP Servers')
            lsp_section.set_content('Disabled')
            lsp_section.set_feature_enabled(False)

        dap_section = self.query_one('#env-dap', CollapsibleSection)
        if renderer._sidebar_debugger_enabled():
            cache = getattr(renderer, '_dap_adapters_cache', None)
            if cache is None:
                dap_section.set_title('Debug Adapters')
                dap_section.set_content('Scanning local PATH...')
            else:
                items = renderer._build_dap_sidebar_items(cache)
                dap_section.set_title(f'Debug Adapters ({len(items)})')
                dap_section._content = 'No debug adapters detected on PATH'
                dap_section.set_items(items)
            dap_section.set_feature_enabled(True)
        else:
            dap_section.set_title('Debug Adapters')
            dap_section.set_content('Disabled')
            dap_section.set_feature_enabled(False)

        skill_items = renderer._build_skills_sidebar_items()
        skills_section = self.query_one('#env-skills', CollapsibleSection)
        skills_section.set_title(f'Skills ({len(skill_items)})')
        skills_section._content = 'No custom skills'
        skills_section.set_items(skill_items)

    def on_collapsible_section_feature_toggle_changed(
        self, event: CollapsibleSection.FeatureToggleChanged
    ) -> None:
        section_id = getattr(event.control, 'id', None)
        if section_id in ('env-mcp', 'env-lsp', 'env-dap'):
            self._apply_feature_toggle(section_id, bool(event.enabled))

    @work
    async def _apply_feature_toggle(self, section_id: str, enabled: bool) -> None:
        screen = self._screen
        if section_id == 'env-mcp':
            await screen._toggle_mcp_master(enabled)
        elif section_id == 'env-lsp':
            await screen._toggle_lsp_query(enabled)
        elif section_id == 'env-dap':
            await screen._toggle_debugger(enabled)
        self.refresh_sections()

    def on_sidebar_row_toggle_requested(self, event: Any) -> None:
        if not isinstance(event, SidebarRow.ToggleRequested) or not event.item_id:
            return
        if event.item_id.startswith('mcp:'):
            self._apply_mcp_server_toggle(event.item_id.split(':', 1)[1])

    @work
    async def _apply_mcp_server_toggle(self, mcp_name: str) -> None:
        await self._screen._toggle_mcp_server(mcp_name)
        self.refresh_sections()

    @work
    async def on_collapsible_section_action_clicked(
        self, event: CollapsibleSection.ActionClicked
    ) -> None:
        """Open the MCP/skills manage dialogs from this modal's section headers."""
        if not event.control:
            return

        from backend.core.config import load_app_config

        screen = self._screen
        if event.control.id == 'env-skills':
            from backend.cli.tui.dialogs.manage_skills import GrintaManageSkillsDialog

            changed = await self.app.push_screen_wait(GrintaManageSkillsDialog())
            if changed:
                screen.notify('Skills updated', severity='information', timeout=2.0)
                self.refresh_sections()
        elif event.control.id == 'env-mcp':
            from backend.cli.tui.dialogs.manage_mcp import GrintaManageMCPDialog

            screen._config = load_app_config()
            changed = await self.app.push_screen_wait(
                GrintaManageMCPDialog(screen._config)
            )
            if changed:
                screen._reload_mcp_config_and_refresh_sidebar()
                screen.notify(
                    'MCP servers updated', severity='information', timeout=2.0
                )
                self.refresh_sections()
