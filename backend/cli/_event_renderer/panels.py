"""Task / delegate / system panel builders + system message tagging."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rich import box
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from backend.cli.layout_tokens import (
    LIVE_PANEL_ACCENT_STYLE,
    WORKER_LABEL_WIDTH,
    WORKER_PANEL_ACCENT_STYLE,
    WORKER_TIMER_WIDTH,
)
from backend.cli.theme import (
    CLR_INFO_BODY,
    CLR_INFO_ICON,
    CLR_OK_BODY,
    CLR_OK_ICON,
    CLR_WARN_BODY,
    CLR_WARN_ICON,
    CLR_WORKER_ACTION,
    CLR_WORKER_LABEL,
    CLR_WORKER_LABEL_DONE,
    CLR_WORKER_LABEL_FAILED,
    CLR_WORKER_SPINNER,
    CLR_WORKER_TIMER,
    STYLE_DEFAULT,
    STYLE_DIM,
    STYLE_SYSTEM_TAG_AUTONOMY,
    STYLE_SYSTEM_TAG_NOTE,
    STYLE_SYSTEM_TAG_SETTINGS,
    STYLE_SYSTEM_TAG_STATUS,
    STYLE_SYSTEM_TAG_SYSTEM,
    STYLE_SYSTEM_TAG_TIMEOUT,
    STYLE_SYSTEM_TAG_WARNING,
)
from backend.cli.transcript import format_live_panel
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
    error_code: str = ''
    omit_summary_in_recovery: bool = False


@dataclass(frozen=True)
class _GuidanceRule:
    """A single rule in the guidance dispatch table."""

    matches: Callable[[str], bool]
    guidance: ErrorGuidance


@dataclass
class PendingActivityCard:
    """Buffered non-shell activity card, paired with a later observation."""

    title: str
    verb: str
    detail: str
    secondary: str | None = None
    kind: str = 'generic'
    payload: dict[str, Any] | None = None
    badge_label: str | None = None


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
        badge.append('• ', style=f'bold {TASK_STATUS_PANEL_STYLES.get(status, "dim")}')
        badge.append(
            status.upper(),
            style=f'bold {TASK_STATUS_PANEL_STYLES.get(status, "dim")}',
        )

        from rich.markdown import Markdown
        
        if task_id and task_id != '?':
            desc = f'**{task_id}**  {desc}'
            
        body = Markdown(desc)
        table.add_row(badge, body)

    empty_state: Any = (
        table
        if task_list
        else Text(
            'No tasks in the tracker yet — the agent may add some as it works.',
            style=STYLE_DIM,
        )
    )
    return format_live_panel(
        f'Tasks ({len(task_list)})',
        empty_state,
        accent_style=LIVE_PANEL_ACCENT_STYLE,
        padding=(0, 1),
    )


def _worker_status_icon(status: str) -> Any:
    """Return a renderable for the worker status column."""
    if status == 'running':
        return Spinner('dots', style=CLR_WORKER_SPINNER, speed=1.0)
    if status == 'done':
        return Text('✓', style='bold green')
    if status == 'failed':
        return Text('✗', style='bold red')
    if status == 'starting':
        return Spinner('line', style=CLR_WORKER_SPINNER, speed=0.5)
    return Text('•', style=STYLE_DIM)


def _worker_label_style(status: str, label: str) -> Text:
    """Return styled worker label text."""
    if status == 'done':
        return Text(label, style=CLR_WORKER_LABEL_DONE, no_wrap=True)
    if status == 'failed':
        return Text(label, style=CLR_WORKER_LABEL_FAILED, no_wrap=True)
    return Text(label, style=CLR_WORKER_LABEL, no_wrap=True)


def _worker_elapsed(worker: dict[str, Any]) -> Text:
    """Format worker elapsed time as ``⏱ 12s``."""
    started_at = worker.get('started_at')
    if started_at is None:
        return Text('', style=CLR_WORKER_TIMER)
    elapsed = max(0, int(time.monotonic() - started_at))
    status = worker.get('status', 'running')
    if status in ('done', 'failed'):
        finished_at = worker.get('finished_at')
        if finished_at is not None:
            elapsed = max(
                0, int(finished_at - (worker.get('started_at') or finished_at))
            )
    if elapsed < 60:
        label = f'{elapsed}s'
    elif elapsed < 3600:
        label = f'{elapsed // 60}m{elapsed % 60:02d}s'
    else:
        label = f'{elapsed // 3600}h{(elapsed % 3600) // 60:02d}m'
    return Text(label, style=CLR_WORKER_TIMER, no_wrap=True)


def _worker_action_text(worker: dict[str, Any]) -> Text:
    """Return the last action or detail text for a worker."""
    last_action = worker.get('last_action', '') or ''
    detail = worker.get('detail', '') or ''
    text = last_action or detail
    if not text:
        text = worker.get('task', 'working…')
    if len(text) > 60:
        text = text[:57] + '…'
    return Text(text, style=CLR_WORKER_ACTION, no_wrap=True)


def build_delegate_worker_panel(workers: dict[str, dict[str, Any]]) -> Any:
    """Render delegated worker progress as a dynamic per-worker panel block.

    Each worker row shows:
      ◌ Worker label  ⏱ 12s  Last action description…
    Uses Rich Spinner for running workers, static marks for done/failed.
    """
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(width=3)  # spinner / status icon
    table.add_column(width=WORKER_LABEL_WIDTH)  # worker label
    table.add_column(width=WORKER_TIMER_WIDTH)  # elapsed timer
    table.add_column(ratio=1)  # action / detail text

    if not workers:
        return format_live_panel(
            'Workers (0)',
            Text('Waiting for workers…', style=STYLE_DIM),
            accent_style=WORKER_PANEL_ACCENT_STYLE,
            padding=(0, 1),
        )

    sorted_workers = sorted(
        workers.items(),
        key=lambda item: (item[1].get('order', 9999), item[1].get('label', '')),
    )

    for worker_id, info in sorted_workers:
        status = info.get('status', 'running')
        label = info.get('label', worker_id)

        icon = _worker_status_icon(status)
        label_t = _worker_label_style(status, label)
        timer = _worker_elapsed(info)
        action = _worker_action_text(info)

        table.add_row(icon, label_t, timer, action)

    return format_live_panel(
        f'Workers ({len(workers)})',
        table,
        accent_style=WORKER_PANEL_ACCENT_STYLE,
        padding=(0, 1),
    )


# ---------------------------------------------------------------------------
# System notice / message helpers
# ---------------------------------------------------------------------------


_SYSTEM_TAG_MAP: dict[str, tuple[str, str]] = {
    'warning': ('[!]', STYLE_SYSTEM_TAG_WARNING),
    'autonomy': ('[auto]', STYLE_SYSTEM_TAG_AUTONOMY),
    'status': ('[*]', STYLE_SYSTEM_TAG_STATUS),
    'settings': ('[cfg]', STYLE_SYSTEM_TAG_SETTINGS),
    'system': ('[grinta]', STYLE_SYSTEM_TAG_SYSTEM),
    'grinta': ('[grinta]', STYLE_SYSTEM_TAG_SYSTEM),
}


def system_message_tag(title: str) -> tuple[str, str]:
    """ASCII bracket tag + color (no Unicode icons)."""
    normalized = title.strip().lower()
    if normalized in _SYSTEM_TAG_MAP:
        return _SYSTEM_TAG_MAP[normalized]
    if 'timeout' in normalized:
        return '[time]', STYLE_SYSTEM_TAG_TIMEOUT
    label = (title.strip() or 'note').replace('\n', ' ')
    if len(label) > 24:
        label = label[:21] + '...'
    return f'[{label}]', STYLE_SYSTEM_TAG_NOTE


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
    'warning': (CLR_WARN_ICON, CLR_WARN_BODY),
    'success': (CLR_OK_ICON, CLR_OK_BODY),
    'info': (CLR_INFO_ICON, CLR_INFO_BODY),
}


def build_system_notice_panel(
    text: str,
    *,
    title: str,
    tone: str = 'info',
) -> Panel:
    """Unified panel chrome for non-error system messages."""
    from rich.markdown import Markdown

    normalized_title = normalize_system_title(title)
    accent_style, body_style = _SYSTEM_TONES.get(tone, _SYSTEM_TONES['info'])
    # ``accent_style`` is a "bold #hex" pair: use the colour-only suffix for
    # the border (Rich draws border characters; bold has no visible effect)
    # and keep the bolded version for the title text.
    border_color = (
        accent_style.split(' ', 1)[1] if ' ' in accent_style else accent_style
    )
    panel_title = Text(normalized_title, style=accent_style)
    
    # Use Markdown for syntax highlighting if there is any code in the system message
    body = Markdown((text or '').strip())
    
    return Panel(
        body,
        title=panel_title,
        title_align='left',
        border_style=border_color,
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
