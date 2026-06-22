"""Tests for CollapsibleSection dynamic item refresh."""

from __future__ import annotations

import pytest
from rich.console import Console as RichConsole
from textual.widgets import Button

from backend.cli.display.hud import HUDBar
from backend.cli.display.reasoning_display import ReasoningDisplay
from backend.cli.tui.app import TUIRenderer
from backend.cli.tui.main import GrintaTUIApp
from backend.cli.tui.widgets.collapsible import (
    CollapsibleSection,
    McpServerRow,
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
        'status': 'info',
        'meta': None,
        'interactive': True,
        'toggleable': False,
        'disabled': False,
        'view_only': False,
    }
    assert isinstance(section._make_row(mcp_item), McpServerRow)
    assert isinstance(section._make_row(skill_item), SidebarRow)


@pytest.mark.asyncio
async def test_collapsible_manage_button_is_rendered(mock_config) -> None:
    console = RichConsole()
    loop = __import__('asyncio').get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        screen = _get_screen(app)
        mcp_section = screen.query_one('#sidebar-mcp', CollapsibleSection)
        skills_section = screen.query_one('#sidebar-skills', CollapsibleSection)
        mcp_manage = mcp_section.query_one('#action-btn', Button)
        skills_manage = skills_section.query_one('#action-btn', Button)
        assert str(mcp_manage.label) == 'Manage ›'
        assert str(skills_manage.label) == 'Manage ›'
        assert '-mcp' in mcp_manage.classes
        assert '-skill' in skills_manage.classes


@pytest.mark.asyncio
async def test_collapsible_set_items_mounts_visible_rows(mock_config) -> None:
    console = RichConsole()
    loop = __import__('asyncio').get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        screen = _get_screen(app)
        section = screen.query_one('#sidebar-tasks', CollapsibleSection)
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


@pytest.mark.asyncio
async def test_task_sidebar_retries_after_failed_first_update(
    mock_config, monkeypatch
) -> None:
    console = RichConsole()
    loop = __import__('asyncio').get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        screen = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=screen,
            loop=loop,
        )
        renderer._task_list = [
            {'id': '1', 'description': 'Ship sidebar refresh', 'status': 'todo'},
        ]

        original = renderer._update_sidebar_section
        calls = {'count': 0}

        def flaky_update(*args, **kwargs):
            calls['count'] += 1
            if calls['count'] == 1:
                return False
            return original(*args, **kwargs)

        monkeypatch.setattr(renderer, '_update_sidebar_section', flaky_update)

        renderer._refresh_tasks_sidebar()
        assert (
            not hasattr(renderer, '_last_task_sidebar_signature')
            or renderer._last_task_sidebar_signature is None
        )

        renderer._refresh_tasks_sidebar()
        section = screen.query_one('#sidebar-tasks', CollapsibleSection)
        assert section._section_title == 'Tasks (1)'
        assert len(list(section.query(SidebarRow).results())) == 1
