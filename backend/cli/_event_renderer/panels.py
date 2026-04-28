"""Task / delegate / system panel builders + system message tagging."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from backend.cli._event_renderer.constants import DELEGATE_WORKER_STATUS_STYLES
from backend.cli.layout_tokens import (
    ACTIVITY_PANEL_PADDING,
    LIVE_PANEL_ACCENT_STYLE,
)
from backend.cli.transcript import format_callout_panel
from backend.core.task_status import (
    TASK_STATUS_PANEL_STYLES,
    TASK_STATUS_TODO,
    normalize_task_status,
)


# ---------------------------------------------------------------------------
# Dataclasses (re-exported by the public event_renderer module)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ErrorGuidance:
    """Actionable recovery copy for a rendered error."""

    summary: str
    steps: tuple[str, ...]
    omit_summary_in_recovery: bool = False


@dataclass
class PendingActivityCard:
    """Buffered non-shell activity card, paired with a later observation."""

    title: str
    verb: str
    detail: str
    secondary: str | None = None
    kind: str = 'generic'
    payload: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Task & worker panel signatures + builders
# ---------------------------------------------------------------------------


def task_panel_signature(
    task_list: list[dict[str, Any]],
) -> tuple[tuple[str, str, str], ...]:
    """Build a stable signature for the visible task tracker state."""
    rows: list[tuple[str, str, str]] = []
    for item in task_list:
        try:
            status = normalize_task_status(item.get('status'), default=TASK_STATUS_TODO)
        except ValueError:
            status = TASK_STATUS_TODO
        desc = str(item.get('description') or '…')
        task_id = str(item.get('id') or '?')
        rows.append((task_id, status, desc))
    return tuple(rows)


def delegate_worker_panel_signature(
    workers: dict[str, dict[str, Any]],
) -> tuple[tuple[int, str, str, str, str], ...]:
    """Build a stable signature for the visible delegated-worker panel."""
    rows: list[tuple[int, str, str, str, str]] = []
    for worker_id, item in workers.items():
        order = item.get('order', 9999)
        if not isinstance(order, int):
            order = 9999
        rows.append(
            (
                order,
                str(item.get('label') or worker_id),
                str(item.get('status') or 'running'),
                str(item.get('task') or 'subtask'),
                str(item.get('detail') or ''),
            )
        )
    return tuple(sorted(rows, key=lambda row: (row[0], row[1], row[3], row[4])))


def build_task_panel(task_list: list[dict[str, Any]]) -> Any:
    """Render the current task list as a single reusable panel block."""
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column()
    table.add_column(ratio=1)

    for task_id, status, desc in task_panel_signature(task_list):
        badge = Text()
        badge.append('[', style='dim')
        badge.append(
            status.upper(),
            style=f'bold {TASK_STATUS_PANEL_STYLES.get(status, "dim")}',
        )
        badge.append(']', style='dim')

        body = Text()
        if task_id and task_id != '?':
            body.append(f'{task_id}  ', style='dim')
        body.append(desc, style='default')
        table.add_row(badge, body)

    empty_state: Any = (
        table
        if task_list
        else Text(
            'No tasks in the tracker yet — the agent may add some as it works.',
            style='dim',
        )
    )
    return format_callout_panel(
        f'Tasks ({len(task_list)})',
        empty_state,
        accent_style=LIVE_PANEL_ACCENT_STYLE,
        padding=ACTIVITY_PANEL_PADDING,
    )


def build_delegate_worker_panel(workers: dict[str, dict[str, Any]]) -> Any:
    """Render delegated worker progress as a compact reusable panel block."""
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column()
    table.add_column(ratio=1)

    for _order, label, status, task, detail in delegate_worker_panel_signature(workers):
        badge = Text()
        badge.append('[', style='dim')
        badge.append(
            status.upper(),
            style=f'bold {DELEGATE_WORKER_STATUS_STYLES.get(status, "dim")}',
        )
        badge.append(']', style='dim')

        body = Text()
        if label:
            body.append(f'{label}  ', style='dim')
        body.append(task or 'subtask', style='default')
        if detail and detail != task:
            body.append(f'\n{detail}', style='dim')
        table.add_row(badge, body)

    empty_state: Any = (
        table
        if workers
        else Text(
            'No parallel workers — subtasks appear here when the agent delegates.',
            style='dim',
        )
    )
    return format_callout_panel(
        f'Workers ({len(workers)})',
        empty_state,
        accent_style=LIVE_PANEL_ACCENT_STYLE,
        padding=ACTIVITY_PANEL_PADDING,
    )


# ---------------------------------------------------------------------------
# System notice / message helpers
# ---------------------------------------------------------------------------


_SYSTEM_TAG_MAP: dict[str, tuple[str, str]] = {
    'warning': ('[!]', 'yellow'),
    'autonomy': ('[auto]', 'magenta'),
    'status': ('[*]', 'blue'),
    'settings': ('[cfg]', 'cyan'),
    'system': ('[grinta]', 'cyan'),
    'grinta': ('[grinta]', 'cyan'),
}


def system_message_tag(title: str) -> tuple[str, str]:
    """ASCII bracket tag + color (no Unicode icons)."""
    normalized = title.strip().lower()
    if normalized in _SYSTEM_TAG_MAP:
        return _SYSTEM_TAG_MAP[normalized]
    if 'timeout' in normalized:
        return '[time]', 'yellow'
    label = (title.strip() or 'note').replace('\n', ' ')
    if len(label) > 24:
        label = label[:21] + '...'
    return f'[{label}]', 'cyan'


_CANONICAL_SYSTEM_TITLES: dict[str, str] = {
    'grinta': 'System',
    'system': 'System',
    'warning': 'Warning',
    'status': 'Status',
    'error': 'Error',
    'autonomy': 'Autonomy',
    'model': 'Model',
    'clipboard': 'Clipboard',
}


def normalize_system_title(title: str) -> str:
    """Normalise arbitrary titles to stable, user-facing label casing."""
    raw = (title or '').strip()
    if not raw:
        return 'Info'
    lowered = raw.lower()
    if lowered in _CANONICAL_SYSTEM_TITLES:
        return _CANONICAL_SYSTEM_TITLES[lowered]
    if 'timeout' in lowered:
        return 'Timeout'
    return raw[:1].upper() + raw[1:]


_SYSTEM_TONES: dict[str, tuple[str, str]] = {
    'warning': ('#f59e0b', 'yellow'),
    'success': ('#10b981', '#86efac'),
    'info': ('#38bdf8', '#93c5fd'),
}


def build_system_notice_panel(
    text: str,
    *,
    title: str,
    tone: str = 'info',
) -> Panel:
    """Unified panel chrome for non-error system messages."""
    normalized_title = normalize_system_title(title)
    border_style, body_style = _SYSTEM_TONES.get(tone, _SYSTEM_TONES['info'])
    panel_title = Text(normalized_title, style=f'bold {border_style}')
    body = Text((text or '').strip(), style=body_style)
    return Panel(
        body,
        title=panel_title,
        title_align='left',
        border_style=border_style,
        box=box.ROUNDED,
        padding=(0, 1),
    )


__all__ = [
    'ErrorGuidance',
    'PendingActivityCard',
    'build_delegate_worker_panel',
    'build_system_notice_panel',
    'build_task_panel',
    'delegate_worker_panel_signature',
    'normalize_system_title',
    'system_message_tag',
    'task_panel_signature',
]
