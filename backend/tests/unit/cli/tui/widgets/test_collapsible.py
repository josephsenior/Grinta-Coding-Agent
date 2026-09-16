"""Tests for CollapsibleSection dynamic item refresh."""

from __future__ import annotations

import pytest
from rich.console import Console as RichConsole

from backend.cli.display.hud import HUDBar
from backend.cli.display.reasoning_display import ReasoningDisplay
from backend.cli.tui.app import TUIRenderer
from backend.cli.tui.main import GrintaTUIApp
from backend.cli.tui.widgets.collapsible import (
    CollapsibleSection,
    McpServerRow,
    SidebarManageButton,
    SidebarRow,
)
from backend.tests.unit.cli.tui._shared import _get_screen


def test_collapsible_make_row_routes_mcp_and_skill_rows() -> None:
    section = CollapsibleSection('Test', collapsed=False)
    mcp_item = {
        'label': 'github',
        'item_id': 'mcp:github',
        'deletable': True,
        'status': 'ok',
        'meta': None,
        'interactive': True,
        'toggleable': True,
        'disabled': False,
        'view_only': False,
    }
    skill_item = {
        'label': 'my-skill',
        'item_id': 'skill:my-skill',
        'deletable': True,
        'status': 'skill',
        'meta': None,
        'interactive': True,
        'toggleable': False,
        'disabled': False,
        'view_only': False,
    }
    assert isinstance(section._make_row(mcp_item), McpServerRow)
    assert isinstance(section._make_row(skill_item), SidebarRow)


@pytest.mark.asyncio
async def test_environment_dialog_manage_button_is_rendered(mock_config) -> None:
    """MCP/Skills 'Edit' buttons, now inside GrintaEnvironmentDialog."""
    console = RichConsole()
    loop = __import__('asyncio').get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        screen = _get_screen(app)
        from backend.cli.tui.dialogs import GrintaEnvironmentDialog

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=screen,
            loop=loop,
        )
        dialog = GrintaEnvironmentDialog(renderer)
        await app.push_screen(dialog)
        await pilot.pause()

        mcp_section = dialog.query_one('#env-mcp', CollapsibleSection)
        skills_section = dialog.query_one('#env-skills', CollapsibleSection)
        mcp_manage = mcp_section.query_one('#action-btn', SidebarManageButton)
        skills_manage = skills_section.query_one('#action-btn', SidebarManageButton)
        assert str(mcp_manage.content) == 'Edit'
        assert str(skills_manage.content) == 'Edit'
        assert '-mcp' in mcp_manage.classes
        assert '-skill' in skills_manage.classes


@pytest.mark.asyncio
async def test_collapsible_set_items_mounts_visible_rows(mock_config) -> None:
    """Generic CollapsibleSection.set_items behavior, exercised via the Tasks drawer."""
    console = RichConsole()
    loop = __import__('asyncio').get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        screen = _get_screen(app)
        from backend.cli.tui.dialogs import GrintaTasksDialog

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=screen,
            loop=loop,
        )
        dialog = GrintaTasksDialog(renderer)
        await app.push_screen(dialog)
        await pilot.pause()

        section = dialog.query_one('#tasks-list', CollapsibleSection)
        section.set_items(
            [
                ('First task', 'task:1', False, 'running', '1'),
                ('Second task', 'task:2', False, 'neutral', '2'),
            ]
        )
        await pilot.pause()

        rows = list(section.query(SidebarRow).results())
        assert len(rows) == 2
        body = section.query_one('#body')
        assert '-hidden' not in body.classes
