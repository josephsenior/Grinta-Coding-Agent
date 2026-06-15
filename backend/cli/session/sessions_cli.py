"""Session retention CLI — list / show / export / delete past sessions.

Backs the ``grinta sessions ...`` subcommand. Reuses ``cli.session_manager``
helpers so the slash-command UI and the CLI subcommand share one source of
truth for what counts as "a session".
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from backend.cli.theme import (
    CLR_CARD_BORDER,
    CLR_CARD_TITLE,
    CLR_META,
    CLR_STATUS_ERR,
    CLR_STATUS_OK,
    MARK_OK,
    STYLE_DIM,
)


@dataclass(frozen=True)
class _SessionResolveFailure:
    message: str


def _root() -> Path | None:
    from backend.cli.session.session_manager import _find_sessions_root

    return _find_sessions_root(None)


def _entries() -> list[tuple[str, dict[str, Any], int, Path]]:
    """[(session_id, metadata, event_count, path), ...] sorted newest first."""
    root = _root()
    if root is None:
        return []
    from backend.cli.session.session_manager import _list_session_entries

    base = _list_session_entries(root)
    out: list[tuple[str, dict[str, Any], int, Path]] = []
    for sid, meta, count in base:
        out.append((sid, meta, count, root / sid))
    return out


def cmd_list(console: Console, limit: int = 50, search: str | None = None) -> int:
    if limit < 1:
        console.print(f'[{CLR_STATUS_ERR}]--limit must be 1 or greater.[/]')
        return 2

    rows = _entries()[:limit]

    # Apply fuzzy search if search term provided
    if search:
        rows = _filter_sessions_fuzzy(rows, search)

    if not rows:
        if search:
            console.print(
                f'[{CLR_META}]No sessions matching "[bold]{search}[/bold]". '
                'Try a different search term.[/]'
            )
        else:
            console.print(
                f'[{CLR_META}]No sessions yet. Start a conversation with '
                '[bold]grinta[/bold], then use this view to resume or export it.[/]'
            )
        return 0
    table = _build_session_table(console)
    for i, (sid, meta, count, _path) in enumerate(rows, 1):
        table.add_row(*_format_session_row(i, sid, meta, count))
    console.print(table)
    search_hint = (
        ' | [bold]grinta sessions list --search <term>[/bold] to filter'
        if search
        else ''
    )
    console.print(
        f'[{CLR_META}]Shell: [bold]grinta sessions show <N|id>[/bold] for details, '
        '[bold]grinta sessions export <N|id> <path>[/bold] to save one.'
        f'{search_hint}[/]'
    )
    return 0


def _filter_sessions_fuzzy(
    rows: list[tuple[str, dict[str, Any], int, Path]],
    search_term: str,
) -> list[tuple[str, dict[str, Any], int, Path]]:
    """Filter sessions using fuzzy matching on title and model."""
    try:
        from rapidfuzz import fuzz  # noqa: F401
    except ImportError:
        return _filter_sessions_plain(rows, search_term)

    search_lower = search_term.lower()
    scored: list[tuple[int, tuple[str, dict[str, Any], int, Path]]] = []
    for row in rows:
        score = _fuzzy_session_score(search_lower, row[1])
        if score > 50:
            scored.append((int(100 - score), row))
    scored.sort()
    return [r for _, r in scored]


def _filter_sessions_plain(
    rows: list[tuple[str, dict[str, Any], int, Path]],
    search_term: str,
) -> list[tuple[str, dict[str, Any], int, Path]]:
    search_lower = search_term.lower()
    return [
        r
        for r in rows
        if search_lower in str(r[1].get('title', '') or '').lower()
        or search_lower in str(r[1].get('name', '') or '').lower()
        or search_lower in str(r[1].get('llm_model', '') or '').lower()
    ]


def _fuzzy_session_score(search_lower: str, meta: dict[str, Any]) -> int:
    from rapidfuzz import fuzz

    title = str(meta.get('title') or meta.get('name') or '').lower()
    model = str(meta.get('llm_model') or '').lower()
    return int(
        max(
            fuzz.partial_ratio(search_lower, title),
            fuzz.partial_ratio(search_lower, model),
        )
    )


def _build_session_table(console: Console) -> Table:
    tw = max(40, int(getattr(console, 'width', None) or 80))
    title_max = max(12, min(40, (tw * 32) // 100))
    id_max = max(8, min(14, tw // 8))
    table = Table(
        title='Sessions',
        title_style=CLR_CARD_TITLE,
        border_style=CLR_CARD_BORDER,
        show_lines=True,
        box=box.ROUNDED,
        padding=(1, 1),
        expand=False,
    )
    table.add_column('#', style=STYLE_DIM, no_wrap=True)
    table.add_column('ID', max_width=id_max, overflow='fold', no_wrap=False)
    table.add_column('Title', max_width=title_max, overflow='fold')
    table.add_column(
        'Model', style=STYLE_DIM, max_width=max(10, tw // 12), overflow='fold'
    )
    table.add_column('Events', justify='right', no_wrap=True)
    table.add_column('Cost', justify='right', no_wrap=True)
    table.add_column('Updated', style=STYLE_DIM, max_width=22, overflow='fold')
    return table


def _format_session_row(
    index: int,
    sid: str,
    meta: dict[str, Any],
    count: int,
) -> tuple[str, str, str, str, str, str, str]:
    title = str(meta.get('title') or meta.get('name') or '—')
    model = str(meta.get('llm_model') or '—')[:24]
    cost = meta.get('accumulated_cost') or 0
    cost_str = f'${cost:.4f}' if cost else '—'
    updated = str(meta.get('last_updated_at') or meta.get('created_at') or '—')[:19]
    return str(index), sid[:12], title, model, str(count), cost_str, updated


def _resolve(
    target: str,
) -> tuple[str, dict[str, Any], int, Path] | _SessionResolveFailure | None:
    rows = _entries()
    if not rows:
        return None
    cleaned = (target or '').strip()
    if cleaned.isdigit():
        return _resolve_by_index(rows, int(cleaned))

    exact = [row for row in rows if row[0] == cleaned]
    if exact:
        return exact[0]
    return _resolve_by_prefix(rows, cleaned)


def _resolve_by_index(
    rows: list[tuple[str, dict[str, Any], int, Path]],
    index: int,
) -> tuple[str, dict[str, Any], int, Path] | None:
    if 1 <= index <= len(rows):
        return rows[index - 1]
    return None


def _resolve_by_prefix(
    rows: list[tuple[str, dict[str, Any], int, Path]],
    cleaned: str,
) -> tuple[str, dict[str, Any], int, Path] | _SessionResolveFailure | None:
    matches = [row for row in rows if row[0].startswith(cleaned)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        preview = ', '.join(row[0][:12] for row in matches[:4])
        if len(matches) > 4:
            preview += ', ...'
        return _SessionResolveFailure(
            f"Session prefix '{cleaned}' is ambiguous ({len(matches)} matches: {preview}). Use a longer id."
        )
    return None


def _report_resolve_failure(console: Console, target: str) -> int:
    console.print(f'[{CLR_STATUS_ERR}]No session matches:[/] {target}')
    console.print(
        f'[{CLR_META}]Run [bold]grinta sessions list[/bold] to see recent sessions.[/]'
    )
    return 2


def _print_resolve_failure(console: Console, failure: _SessionResolveFailure) -> None:
    console.print(f'[{CLR_STATUS_ERR}]{failure.message}[/]')
    console.print(
        f'[{CLR_META}]Run [bold]grinta sessions list[/bold] to copy a longer id.[/]'
    )


def _session_summary_table(
    sid: str,
    meta: dict[str, Any],
    count: int,
    path: Path,
) -> Table:
    table = Table(
        show_header=False, box=box.ROUNDED, border_style=CLR_CARD_BORDER, padding=(1, 2)
    )
    table.add_column(style=CLR_CARD_TITLE, no_wrap=True)
    table.add_column(overflow='fold')

    table.add_row('ID', sid)
    table.add_row('Path', str(path))
    table.add_row('Events', str(count))
    for key in (
        'title',
        'name',
        'llm_model',
        'accumulated_cost',
        'created_at',
        'last_updated_at',
    ):
        value = meta.get(key)
        if value not in (None, ''):
            table.add_row(key.replace('_', ' ').title(), str(value))
    return table


def cmd_show(console: Console, target: str) -> int:
    row = _resolve(target)
    if isinstance(row, _SessionResolveFailure):
        _print_resolve_failure(console, row)
        return 2
    if row is None:
        return _report_resolve_failure(console, target)
    sid, meta, count, path = row
    console.print(
        Panel(
            _session_summary_table(sid, meta, count, path),
            title=Text('Session', style=CLR_CARD_TITLE),
            title_align='left',
            border_style=CLR_CARD_BORDER,
            padding=(1, 2),
        )
    )
    return 0


def cmd_export(console: Console, target: str, out_path: str) -> int:
    row = _resolve(target)
    if isinstance(row, _SessionResolveFailure):
        _print_resolve_failure(console, row)
        return 2
    if row is None:
        return _report_resolve_failure(console, target)
    _sid, _meta, _count, path = row
    out = Path(out_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() == '.zip':
        archive = shutil.make_archive(str(out.with_suffix('')), 'zip', root_dir=path)
        console.print(f'[{CLR_STATUS_OK}]{MARK_OK}[/] Wrote [bold]{archive}[/bold]')
    else:
        # Tree copy.
        shutil.copytree(path, out, dirs_exist_ok=True)
        console.print(f'[{CLR_STATUS_OK}]{MARK_OK}[/] Copied to [bold]{out}[/bold]')
    return 0


def cmd_delete(console: Console, target: str, *, yes: bool = False) -> int:
    row = _resolve(target)
    if isinstance(row, _SessionResolveFailure):
        _print_resolve_failure(console, row)
        return 2
    if row is None:
        return _report_resolve_failure(console, target)
    sid, _meta, _count, path = row
    if not yes:
        from rich.prompt import Confirm

        if not Confirm.ask(
            f'Delete session {sid}? This cannot be undone.', default=False
        ):
            console.print(f'[{CLR_META}]Cancelled. No changes were made.[/]')
            return 0
    shutil.rmtree(path, ignore_errors=True)
    console.print(f'[{CLR_STATUS_OK}]{MARK_OK}[/] Deleted [bold]{sid}[/bold]')
    return 0


def cmd_prune(console: Console, *, days: int = 30, yes: bool = False) -> int:
    """Delete sessions older than ``days``."""
    if days < 0:
        console.print(f'[{CLR_STATUS_ERR}]--days must be 0 or greater.[/]')
        return 2
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    to_delete = [
        (sid, path)
        for sid, meta, _count, path in _entries()
        if _session_older_than_cutoff(meta, path, cutoff)
    ]

    if not to_delete:
        console.print(f'[{CLR_META}]No sessions older than {days} days.[/]')
        return 0

    console.print(
        f'Will delete [bold]{len(to_delete)}[/bold] sessions older than {days} days.'
    )
    if not yes:
        from rich.prompt import Confirm

        if not Confirm.ask(
            'Delete these sessions? This action cannot be undone.', default=False
        ):
            console.print(f'[{CLR_META}]Cancelled. No changes were made.[/]')
            return 0
    for sid, path in to_delete:
        shutil.rmtree(path, ignore_errors=True)
        console.print(f'  [{CLR_STATUS_OK}]{MARK_OK}[/] Deleted {sid}')
    return 0


def _session_older_than_cutoff(
    meta: dict[str, Any],
    path: Path,
    cutoff: datetime,
) -> bool:
    ts = meta.get('last_updated_at') or meta.get('created_at')
    if not ts:
        # No timestamp → fall back to mtime.
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            return False
        return mtime < cutoff
    try:
        parsed = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
    except Exception:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed < cutoff


__all__ = ['cmd_list', 'cmd_show', 'cmd_export', 'cmd_delete', 'cmd_prune']
