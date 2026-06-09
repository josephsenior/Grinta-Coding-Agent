"""Session management — list, inspect, search, sort, and resume past sessions."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from backend.cli.theme import CLR_CARD_BORDER, CLR_CARD_TITLE, STYLE_DIM

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


def _list_session_entries(
    root: Path,
    sort_by: str = 'updated',
) -> list[tuple[str, dict[str, Any], int]]:
    """Load and sort persisted sessions.

    Supports sorting by: ``updated`` (default), ``created``, ``events``,
    ``cost``, ``model``.
    """
    sessions: list[tuple[str, dict[str, Any], int]] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        meta = _load_metadata(entry)
        event_count = _count_events(entry)
        sessions.append((entry.name, meta or {}, event_count))

    def _sort_key(item: tuple[str, dict[str, Any], int]) -> Any:
        sid, meta, count = item
        if sort_by == 'created':
            return meta.get('created_at', '0')
        if sort_by == 'events':
            return count
        if sort_by == 'cost':
            return float(meta.get('accumulated_cost') or 0)
        if sort_by == 'model':
            return meta.get('llm_model', '') or ''
        return meta.get('last_updated_at', meta.get('created_at', '0'))

    reverse = sort_by not in ('model',)
    sessions.sort(key=_sort_key, reverse=reverse)
    return sessions


def _filter_sessions_fuzzy(
    sessions: list[tuple[str, dict[str, Any], int]],
    search_term: str,
) -> list[tuple[str, dict[str, Any], int]]:
    """Filter sessions using fuzzy matching on id, title, and model."""
    try:
        from rapidfuzz import fuzz
    except ImportError:
        search_lower = search_term.lower()
        return [
            s
            for s in sessions
            if search_lower in s[0].lower()
            or search_lower in str(s[1].get('title', '') or '').lower()
            or search_lower in str(s[1].get('name', '') or '').lower()
            or search_lower in str(s[1].get('llm_model', '') or '').lower()
        ]

    search_lower = search_term.lower()
    scored: list[tuple[int, tuple[str, dict[str, Any], int]]] = []

    for session in sessions:
        sid, meta, count = session
        sid_lower = sid.lower()
        title = str(meta.get('title') or meta.get('name') or '').lower()
        model = str(meta.get('llm_model') or '').lower()

        sid_score = fuzz.partial_ratio(search_lower, sid_lower)
        title_score = fuzz.partial_ratio(search_lower, title)
        model_score = fuzz.partial_ratio(search_lower, model)
        max_score = max(sid_score, title_score, model_score)

        if max_score > 50:
            scored.append((int(100 - max_score), session))

    scored.sort()
    return [s for _, s in scored]


def show_session(
    console: Console,
    *,
    config: AppConfig | None = None,
    target: str | int | None = None,
    sid: str | None = None,
) -> bool:
    """Display a detailed preview of a single session.

    Accepts ``target`` (index or id prefix) or a raw ``sid``.
    Returns True if the session was found and displayed.
    """
    root = _find_sessions_root(config)
    if root is None:
        console.print(f'[{STYLE_DIM}]No session storage found.[/{STYLE_DIM}]')
        return False

    sessions = _list_session_entries(root)
    if not sessions:
        console.print(f'[{STYLE_DIM}]No past sessions found.[/{STYLE_DIM}]')
        return False

    if sid:
        resolved = _resolve_by_id(sessions, sid)
    elif target is not None:
        resolved = _resolve_target(sessions, target)
    else:
        return False

    if resolved is None:
        return False

    sid, meta, event_count = resolved

    detail = Table(
        show_header=False,
        box=box.ROUNDED,
        border_style=CLR_CARD_BORDER,
        padding=(1, 2),
    )
    detail.add_column(style=CLR_CARD_TITLE, no_wrap=True)
    detail.add_column(overflow='fold')

    detail.add_row('ID', sid)
    detail.add_row('Title', str(meta.get('title') or meta.get('name') or '—'))
    detail.add_row('Model', str(meta.get('llm_model') or '—'))
    detail.add_row('Events', str(event_count))
    cost = meta.get('accumulated_cost') or 0
    detail.add_row('Cost', f'${float(cost):.4f}' if cost else '—')
    detail.add_row('Created', str(meta.get('created_at', '—'))[:19])
    detail.add_row('Updated', str(meta.get('last_updated_at', '—'))[:19])

    console.print()
    console.print(
        Panel(
            detail,
            title=Text('Session Preview', style=CLR_CARD_TITLE),
            title_align='left',
            border_style=CLR_CARD_BORDER,
            padding=(1, 2),
        )
    )
    console.print(
        f'[{STYLE_DIM}]Use /resume {sid[:12]} to resume this session.[/{STYLE_DIM}]'
    )
    return True


def _resolve_target(
    sessions: list[tuple[str, dict[str, Any], int]],
    target: str | int,
) -> tuple[str, dict[str, Any], int] | None:
    """Resolve an index (int) or id prefix (str) to a session."""
    if isinstance(target, int) or (isinstance(target, str) and target.isdigit()):
        index = int(target)
        if 1 <= index <= len(sessions):
            return sessions[index - 1]
        return None

    cleaned = str(target).strip()
    exact = [s for s in sessions if s[0] == cleaned]
    if exact:
        return exact[0]

    matches = [s for s in sessions if s[0].startswith(cleaned)]
    if len(matches) == 1:
        return matches[0]
    return None


def _resolve_by_id(
    sessions: list[tuple[str, dict[str, Any], int]],
    sid: str,
) -> tuple[str, dict[str, Any], int] | None:
    """Resolve by exact session id."""
    for s in sessions:
        if s[0] == sid:
            return s
    return None


def _format_session_row(
    index: int,
    sid: str,
    meta: dict[str, Any],
    count: int,
    max_width: int = 80,
) -> tuple[str, str, str, str, str, str, str]:
    title = str(meta.get('title') or meta.get('name') or '—')
    model = str(meta.get('llm_model') or '—')[:24]
    cost = meta.get('accumulated_cost') or 0
    cost_str = f'${float(cost):.4f}' if cost else '—'
    updated = str(meta.get('last_updated_at') or meta.get('created_at') or '—')[:19]
    return str(index), sid[:12], title, model, str(count), cost_str, updated


_SORT_OPTIONS = {'updated', 'created', 'events', 'cost', 'model'}


def list_sessions(
    console: Console,
    *,
    limit: int = 20,
    config: AppConfig | None = None,
    sort_by: str = 'updated',
    search: str | None = None,
) -> None:
    """Display a table of past sessions with optional sorting and search.

    Parameters
    ----------
    console:
        Rich console to print to.
    limit:
        Maximum number of sessions to show.
    config:
        App config (optional, loaded automatically if omitted).
    sort_by:
        Sort field: ``updated``, ``created``, ``events``, ``cost``, ``model``.
    search:
        Optional fuzzy search term for filtering by title or model.
    """
    root = _find_sessions_root(config)
    if root is None:
        console.print(f'[{STYLE_DIM}]No session storage found.[/{STYLE_DIM}]')
        return

    sort_field = sort_by if sort_by in _SORT_OPTIONS else 'updated'
    sessions = _list_session_entries(root, sort_by=sort_field)

    if not sessions:
        console.print(f'[{STYLE_DIM}]No past sessions found.[/{STYLE_DIM}]')
        return

    if search:
        sessions = _filter_sessions_fuzzy(sessions, search)
        if not sessions:
            console.print(
                f'[{STYLE_DIM}]No sessions matching "[bold]{search}[/bold]". '
                'Try a different search term.[/{STYLE_DIM}]'
            )
            return

    sessions = sessions[:limit]

    table = Table(
        title='Past Sessions',
        title_style=CLR_CARD_TITLE,
        border_style=CLR_CARD_BORDER,
        show_lines=False,
    )
    table.add_column('#', style=STYLE_DIM)
    table.add_column('Session ID', style=STYLE_DIM)
    table.add_column('Title')
    table.add_column('Model', style=STYLE_DIM)
    table.add_column('Events', justify='right', style=STYLE_DIM)
    table.add_column('Cost', justify='right', style=STYLE_DIM)
    table.add_column('Updated', style=STYLE_DIM)

    for i, (sid, meta, event_count) in enumerate(sessions, 1):
        title = meta.get('title', meta.get('name', '—'))
        model = meta.get('llm_model', '—')
        cost = meta.get('accumulated_cost', 0)
        cost_str = f'${float(cost):.4f}' if cost else '—'
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
    sort_hint = f' (sorted by {sort_field})' if sort_field != 'updated' else ''
    search_hint = f' matching "{search}"' if search else ''
    console.print(
        f'[{STYLE_DIM}]{len(sessions)} session(s){search_hint}{sort_hint}. '
        f'Use /resume <N> to resume a session. '
        f'Use /sessions --sort <field> to sort, /sessions --search <term> to filter.[/{STYLE_DIM}]'
    )


def _resolve_delete_target(
    sessions: list[tuple[str, dict[str, Any], int]],
    target: str,
) -> tuple[tuple[str, dict[str, Any], int] | None, str | None]:
    """Resolve a delete target to a session or error message."""
    if target.isdigit():
        idx = int(target)
        if 1 <= idx <= len(sessions):
            return sessions[idx - 1], None
        return None, f"No session at index '{target}'"

    match = [s for s in sessions if s[0] == target]
    if match:
        return match[0], None

    prefix_matches = [s for s in sessions if s[0].startswith(target)]
    if len(prefix_matches) == 1:
        return prefix_matches[0], None
    if len(prefix_matches) > 1:
        return None, f"Prefix '{target}' is ambiguous ({len(prefix_matches)} matches)"
    return None, f"No session matches '{target}'"


def delete_sessions(
    console: Console,
    targets: list[str],
    *,
    config: AppConfig | None = None,
    yes: bool = False,
) -> int:
    """Delete one or more sessions by index or id prefix.

    Returns 0 on success, 1 if any deletions failed, 2 on usage error.
    """
    root = _find_sessions_root(config)
    if root is None:
        console.print(f'[{STYLE_DIM}]No session storage found.[/{STYLE_DIM}]')
        return 2

    sessions = _list_session_entries(root)
    if not sessions:
        console.print(f'[{STYLE_DIM}]No past sessions found.[/{STYLE_DIM}]')
        return 2

    to_delete: list[tuple[str, dict[str, Any], int]] = []
    errors: list[str] = []

    for target in targets:
        resolved, error = _resolve_delete_target(sessions, target)
        if resolved is not None:
            to_delete.append(resolved)
        else:
            errors.append(error)

    if not to_delete:
        for e in errors:
            console.print(f'[red]{e}[/]')
        return 2

    if not yes:
        from rich.prompt import Confirm

        console.print(f'Will delete {len(to_delete)} session(s):')
        for sid, meta, _count in to_delete:
            title = str(meta.get('title') or meta.get('name') or sid)
            console.print(f'  {sid[:12]}  {title[:40]}')
        if not Confirm.ask('Proceed?', default=False):
            console.print('Cancelled.')
            return 0

    deleted = 0
    for sid, _meta, _count in to_delete:
        path = root / sid
        try:
            shutil.rmtree(path, ignore_errors=True)
            console.print(f'  [green]Deleted[/] {sid[:12]}')
            deleted += 1
        except Exception as e:
            console.print(f'  [red]Failed[/] {sid[:12]}: {e}')

    for err in errors:
        console.print(f'[yellow]{err}[/]')

    return 0 if deleted == len(to_delete) else 1


def get_session_id_by_index(index: int, config: AppConfig | None = None) -> str | None:
    """Get a session ID by its index from the list (1-based)."""
    root = _find_sessions_root(config)
    if root is None:
        return None

    sessions = _list_session_entries(root)

    if 1 <= index <= len(sessions):
        return sessions[index - 1][0]
    return None


def resolve_session_id(
    target: str,
    config: AppConfig | None = None,
) -> tuple[str | None, str | None]:
    """Resolve a 1-based index, exact session id, or unique id prefix.

    Returns ``(session_id, None)`` on success or ``(None, user_message)`` on
    failure. The message is ready for CLI display.
    """
    cleaned = (target or '').strip()
    if not cleaned:
        return None, 'Usage: /resume <N> or /resume <session_id>.'

    root = _find_sessions_root(config)
    if root is None:
        return None, 'No session storage found for this project.'

    sessions = _list_session_entries(root)
    if not sessions:
        return None, 'No past sessions found for this project.'

    if cleaned.isdigit():
        return _resolve_session_index(sessions, cleaned)
    return _resolve_session_by_id_or_prefix(sessions, cleaned)


def _resolve_session_index(
    sessions: list[tuple[str, dict[str, Any], int]],
    cleaned: str,
) -> tuple[str | None, str | None]:
    index = int(cleaned)
    if 1 <= index <= len(sessions):
        return sessions[index - 1][0], None
    return None, f'No session at index {cleaned}.'


def _resolve_session_by_id_or_prefix(
    sessions: list[tuple[str, dict[str, Any], int]],
    cleaned: str,
) -> tuple[str | None, str | None]:
    exact = [sid for sid, _meta, _event_count in sessions if sid == cleaned]
    if exact:
        return exact[0], None

    matches = [sid for sid, _meta, _event_count in sessions if sid.startswith(cleaned)]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        preview = ', '.join(sid[:12] for sid in matches[:4])
        if len(matches) > 4:
            preview += ', ...'
        return (
            None,
            f"Session prefix '{cleaned}' is ambiguous ({len(matches)} matches: {preview}). Use a longer id.",
        )
    return None, f'No session matches: {cleaned}'


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
