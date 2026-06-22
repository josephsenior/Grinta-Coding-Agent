"""Right sidebar builder for Tasks, MCP Servers, and Skills panels."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import backend
from backend.cli.display.layout_tokens import (
    SIDEBAR_VISIBLE_MIN_WIDTH,
    SIDEBAR_WIDTH_RATIO,
)
from backend.cli.event_rendering.panels import task_panel_signature
from backend.cli.theme import (
    STYLE_DEFAULT,
    STYLE_DIM,
)
from backend.core.tasks.task_status import TASK_STATUS_PANEL_STYLES


def _create_sidebar_panel(title: str, content: Any, count: int | None = None) -> Panel:
    title_text = Text(f'{title}', style='bold #91abec')
    if count is not None:
        title_text.append(f' ({count})', style='bold #54597b')

    return Panel(
        content,
        title=title_text,
        title_align='left',
        border_style='#1b233a',
        box=box.ROUNDED,
        padding=(0, 1),
    )


# Maximum rows to show in each scrollable panel
SIDEBAR_MAX_ROWS = 30


def should_show_sidebar(terminal_width: int) -> bool:
    """Check if sidebar should be shown based on terminal width."""
    return terminal_width > SIDEBAR_VISIBLE_MIN_WIDTH


def compute_sidebar_width(terminal_width: int) -> int:
    """Compute sidebar width in columns."""
    return max(30, int(terminal_width * SIDEBAR_WIDTH_RATIO))


def compute_main_width(terminal_width: int) -> int:
    """Compute main panel width in columns."""
    sidebar_width = compute_sidebar_width(terminal_width)
    return max(40, terminal_width - sidebar_width - 1)  # -1 for divider


def build_task_list_panel(
    task_list: list[Any],
    *,
    width: int | None = None,
) -> Panel:
    """Build scrollable task list panel."""
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(width=1)  # status icon
    table.add_column(ratio=1)  # task description

    signature = task_panel_signature(task_list)
    displayed_count = 0
    for task_id, status, desc in signature:
        if displayed_count >= SIDEBAR_MAX_ROWS:
            break

        status_style = TASK_STATUS_PANEL_STYLES.get(status, 'dim')
        status_icon = Text('●', style=f'bold {status_style}')

        body = Text()
        if task_id and task_id != '?':
            body.append(f'{task_id} ', style=STYLE_DIM)
        body.append(desc, style=STYLE_DEFAULT)

        table.add_row(status_icon, body)
        displayed_count += 1

    empty_state = Text(
        'No tasks yet',
        style=STYLE_DIM,
    )

    content = table if signature else empty_state
    return _create_sidebar_panel('Tasks', content, len(signature))


def build_mcp_servers_panel(
    mcp_servers: list[dict[str, Any]] | None = None,
    *,
    width: int | None = None,
) -> Panel:
    """Build scrollable MCP servers list panel."""
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(width=2)  # bullet
    table.add_column(ratio=1)  # server info

    if mcp_servers:
        displayed_count = 0
        for server in mcp_servers:
            if displayed_count >= SIDEBAR_MAX_ROWS:
                break
            name = server.get('name', 'unknown')

            bullet = Text('• ', style='bold #eacb8a')
            server_info = Text(name, style='#c8d4e8')

            table.add_row(bullet, server_info)
            displayed_count += 1
    else:
        empty_state = Text(
            'No MCP servers configured',
            style=STYLE_DIM,
        )
        return _create_sidebar_panel('MCP Servers', empty_state, 0)

    return _create_sidebar_panel('MCP Servers', table, len(mcp_servers))


def build_skills_panel(
    skills: list[str] | None = None,
    *,
    width: int | None = None,
) -> Panel:
    """Build scrollable skills/playbooks list panel."""
    if skills is None:
        skills = load_sidebar_skills()

    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(width=2)  # bullet
    table.add_column(ratio=1)  # skill name

    if skills:
        displayed_count = 0
        for skill in sorted(skills):
            if displayed_count >= SIDEBAR_MAX_ROWS:
                break
            bullet = Text('• ', style='bold #7a849c')
            skill_name = Text(skill, style='#a1acc2')
            table.add_row(bullet, skill_name)
            displayed_count += 1
    else:
        empty_state = Text(
            'No skills available',
            style=STYLE_DIM,
        )
        return _create_sidebar_panel('Skills', empty_state, 0)

    return _create_sidebar_panel('Skills', table, len(skills))


def _load_playbook_skills() -> list[str]:
    """Load playbook skill names from backend/playbooks/ directory."""
    try:
        root = Path(backend.__file__).resolve().parent / 'playbooks'
        if not root.is_dir():
            return []
        return [
            p.stem
            for p in root.iterdir()
            if p.is_file()
            and p.suffix.lower() == '.md'
            and p.name.lower() != 'readme.md'
        ]
    except OSError:
        return []


def _load_user_skills() -> list[str]:
    """Load user-created skill names from ~/.grinta/skills/."""
    try:
        root = Path.home() / '.grinta' / 'skills'
        if not root.is_dir():
            return []
        return [
            p.stem for p in root.iterdir() if p.is_file() and p.suffix.lower() == '.md'
        ]
    except OSError:
        return []


def load_sidebar_skills() -> list[str]:
    """Bundled playbooks plus user skills under ~/.grinta/skills."""
    return sorted({*_load_playbook_skills(), *_load_user_skills()})


def load_sidebar_skill_items() -> list[
    tuple[str, str, bool, str, str | None, bool, dict[str, Any]]
]:
    """Sidebar rows for bundled and custom skills."""
    playbook_names = set(_load_playbook_skills())
    user_names = set(_load_user_skills())
    items: list[tuple[str, str, bool, str, str | None, bool, dict[str, Any]]] = []
    for skill in sorted(playbook_names | user_names):
        if skill in user_names:
            items.append((skill, f'skill:{skill}', False, 'info', None, False, {}))
        else:
            items.append(
                (
                    skill,
                    f'skill:{skill}',
                    False,
                    'neutral',
                    None,
                    False,
                    {'view_only': True},
                )
            )
    return items


def is_user_skill(name: str) -> bool:
    """Return True when the skill lives under ~/.grinta/skills/."""
    stem = name.removesuffix('.md')
    return stem in set(_load_user_skills())


def build_sidebar(
    task_list: list[dict[str, Any]],
    mcp_servers: list[dict[str, Any]] | None = None,
    *,
    terminal_width: int = 120,
) -> Any | None:
    """Build the sidebar with Tasks, MCP Servers, and Skills panels."""
    if not should_show_sidebar(terminal_width):
        return None

    sidebar_width = compute_sidebar_width(terminal_width)

    sections: list[Any] = []

    # 1. Tasks Panel
    sections.append(build_task_list_panel(task_list, width=sidebar_width))

    # 2. MCP Servers Panel
    sections.append(build_mcp_servers_panel(mcp_servers, width=sidebar_width))

    # 3. Skills Panel (using total count if list not available)
    # For simplicity, we just show the count or a few skills
    sections.append(build_skills_panel(width=sidebar_width))

    from rich.console import Group

    return Group(*sections)


def load_playbook_skills() -> list[str]:
    """Load playbook skill names from backend/playbooks/ directory."""
    return _load_playbook_skills()


__all__ = [
    'build_sidebar',
    'build_mcp_servers_panel',
    'build_skills_panel',
    'build_task_list_panel',
    'compute_main_width',
    'compute_sidebar_width',
    'is_user_skill',
    'load_playbook_skills',
    'load_sidebar_skill_items',
    'load_sidebar_skills',
    'should_show_sidebar',
]
