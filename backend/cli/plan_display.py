"""Shared rich rendering for structured Plan-mode finish output."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from rich import box
from rich.console import Group
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from backend.cli.theme import (
    NAVY_BRAND,
    NAVY_ERROR,
    NAVY_READY,
    NAVY_TEXT_DIM,
    NAVY_TEXT_MUTED,
    NAVY_TEXT_PRIMARY,
    NAVY_TEXT_SECONDARY,
    NAVY_WAITING,
    get_grinta_pygments_style,
)


def is_structured_plan_finish(action: Any) -> bool:
    """Return True when a finish action carries Plan-mode structured outputs."""
    outputs = getattr(action, 'outputs', None)
    return isinstance(outputs, Mapping) and isinstance(outputs.get('plan'), list)


def _as_mapping(action_or_outputs: Any) -> Mapping[str, Any]:
    if isinstance(action_or_outputs, Mapping):
        return action_or_outputs
    outputs = getattr(action_or_outputs, 'outputs', None)
    return outputs if isinstance(outputs, Mapping) else {}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if not isinstance(value, Sequence):
        return []
    items: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            items.append(text)
    return items


def _markdown(text: str) -> Markdown:
    return Markdown(text, code_theme=get_grinta_pygments_style())


def _section_heading(label: str) -> Text:
    return Text(label, style=f'bold {NAVY_TEXT_SECONDARY}')


def _numbered_section(title: str, items: list[str]) -> Any | None:
    if not items:
        return None
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(width=4, justify='right', no_wrap=True)
    table.add_column(ratio=1)
    for index, item in enumerate(items, 1):
        table.add_row(
            Text(f'{index}.', style=NAVY_TEXT_DIM),
            _markdown(item),
        )
    return Group(_section_heading(title), table)


def _bullet_section(title: str, items: list[str]) -> Any | None:
    if not items:
        return None
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(width=2, justify='right', no_wrap=True)
    table.add_column(ratio=1)
    for item in items:
        table.add_row(Text('-', style=NAVY_TEXT_DIM), _markdown(item))
    return Group(_section_heading(title), table)


def _status_title(status: str) -> tuple[str, str]:
    normalized = (status or 'completed').strip().lower()
    if normalized == 'blocked':
        return 'Plan Blocked', NAVY_WAITING
    if normalized == 'failed':
        return 'Plan Failed', NAVY_ERROR
    return 'Plan Ready', NAVY_READY


def render_plan_finish_panel(action_or_outputs: Any) -> Panel:
    """Render a structured Plan-mode finish payload as a rich plan card."""
    outputs = _as_mapping(action_or_outputs)
    status = str(outputs.get('status') or 'completed')
    title, border_style = _status_title(status)
    summary = str(
        outputs.get('summary') or getattr(action_or_outputs, 'final_thought', '') or ''
    ).strip()
    plan = _string_list(outputs.get('plan'))
    files_or_areas = _string_list(outputs.get('files_or_areas'))
    risks = _string_list(outputs.get('risks'))
    verification = _string_list(outputs.get('verification'))
    assumptions = _string_list(outputs.get('assumptions'))
    next_step = str(outputs.get('next_step') or '').strip()

    parts: list[Any] = []
    if summary:
        parts.append(_markdown(summary))

    sections = [
        _numbered_section('Execution Plan', plan),
        _bullet_section('Files / Areas', files_or_areas),
        _bullet_section('Verification', verification),
        _bullet_section('Risks', risks),
        _bullet_section('Assumptions', assumptions),
    ]
    parts.extend(section for section in sections if section is not None)

    if next_step:
        next_table = Table.grid(expand=True, padding=(0, 1))
        next_table.add_column(width=2, justify='right', no_wrap=True)
        next_table.add_column(ratio=1)
        next_table.add_row(Text('>', style=NAVY_BRAND), _markdown(next_step))
        parts.append(Group(_section_heading('Next Step'), next_table))

    if not parts:
        parts.append(Text('No plan details were provided.', style=NAVY_TEXT_MUTED))

    return Panel(
        Padding(Group(*parts), (0, 1)),
        title=Text(title, style=f'bold {border_style}'),
        title_align='left',
        border_style=border_style,
        box=box.ROUNDED,
        padding=(0, 0),
        style=NAVY_TEXT_PRIMARY,
    )


__all__ = ['is_structured_plan_finish', 'render_plan_finish_panel']
