"""Session management — list, inspect, and resume past sessions."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.table import Table

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from backend.core.config.app_config import AppConfig


def _resolve_config(config: AppConfig | None) -> AppConfig:
    if config is not None:
        return config

    from backend.core.config import load_app_config

    return load_app_config(set_logging_levels=False)


def _find_sessions_root(config: AppConfig | None = None) -> Path | None:
    """Locate the canonical conversation storage directory."""
    from backend.core.constants import CONVERSATION_BASE_DIR
    from backend.persistence.locations import get_local_data_root

    resolved_config = _resolve_config(config)
    path = Path(get_local_data_root(resolved_config)) / CONVERSATION_BASE_DIR
    if path.is_dir():
        return path
    return None


def _load_metadata(session_dir: Path) -> dict[str, Any] | None:
    """Load metadata.json from a session directory."""
    import json

    meta_path = session_dir / 'metadata.json'
    if not meta_path.exists():
        return None
    try:
        with meta_path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        logger.debug('Could not load metadata from %s', meta_path, exc_info=True)
        return None


def _count_events(session_dir: Path) -> int:
    """Count persisted events in a session directory."""
    events_dir = session_dir / 'events'
    if events_dir.is_dir():
        return sum(1 for f in events_dir.iterdir() if f.suffix == '.json')
    return 0


def _list_session_entries(root: Path) -> list[tuple[str, dict[str, Any], int]]:
    """Load and sort persisted sessions by recency."""
    sessions: list[tuple[str, dict[str, Any], int]] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        meta = _load_metadata(entry)
        event_count = _count_events(entry)
        sessions.append((entry.name, meta or {}, event_count))

    def _sort_key(item: tuple[str, dict[str, Any], int]) -> str:
        metadata = item[1]
        return metadata.get('last_updated_at', metadata.get('created_at', '0'))

    sessions.sort(key=_sort_key, reverse=True)
    return sessions


def list_sessions(
    console: Console,
    *,
    limit: int = 20,
    config: AppConfig | None = None,
) -> None:
    """Display a table of past sessions."""
    root = _find_sessions_root(config)
    if root is None:
        console.print('[dim]No session storage found.[/dim]')
        return

    sessions = _list_session_entries(root)
    if not sessions:
        console.print('[dim]No past sessions found.[/dim]')
        return

    sessions = sessions[:limit]

    table = Table(title='Past Sessions', border_style='dim', show_lines=False)
    table.add_column('#', style='dim')
    table.add_column('Session ID', style='dim')
    table.add_column('Title')
    table.add_column('Model', style='dim')
    table.add_column('Events', justify='right', style='dim')
    table.add_column('Cost', justify='right', style='dim')
    table.add_column('Updated', style='dim')

    for i, (sid, meta, event_count) in enumerate(sessions, 1):
        title = meta.get('title', meta.get('name', '—'))
        model = meta.get('llm_model', '—')
        cost = meta.get('accumulated_cost', 0)
        cost_str = f'${cost:.4f}' if cost else '—'
        updated = meta.get('last_updated_at', meta.get('created_at', '—'))
        if isinstance(updated, str) and len(updated) > 19:
            updated = updated[:19]

        table.add_row(
            str(i),
            sid,
            str(title) if title else '—',
            str(model)[:20] if model else '—',
            str(event_count),
            cost_str,
            str(updated),
        )

    console.print(table)
    console.print(
        '[dim]Use /resume <N> or /resume <session_id> to resume a session.[/dim]'
    )


def get_session_id_by_index(index: int, config: AppConfig | None = None) -> str | None:
    """Get a session ID by its index from the list (1-based)."""
    root = _find_sessions_root(config)
    if root is None:
        return None

    sessions = _list_session_entries(root)

    if 1 <= index <= len(sessions):
        return sessions[index - 1][0]
    return None


def get_session_suggestions(
    config: AppConfig | None = None, limit: int = 8
) -> list[tuple[str, str]]:
    """Return recent session identifiers plus short labels for autocomplete."""
    root = _find_sessions_root(config)
    if root is None:
        return []

    suggestions: list[tuple[str, str]] = []
    for index, (sid, meta, _event_count) in enumerate(
        _list_session_entries(root)[:limit], 1
    ):
        title = str(
            meta.get('title', meta.get('name', 'Untitled session'))
            or 'Untitled session'
        )
        model = str(meta.get('llm_model', '') or '')
        updated = str(meta.get('last_updated_at', meta.get('created_at', '')) or '')
        if len(updated) > 19:
            updated = updated[:19]

        descriptor_parts = [title]
        if model:
            descriptor_parts.append(model)
        if updated:
            descriptor_parts.append(updated)
        descriptor = ' · '.join(descriptor_parts)

        suggestions.append((str(index), f'#{index} {descriptor}'))
        suggestions.append((sid, descriptor))

    return suggestions
