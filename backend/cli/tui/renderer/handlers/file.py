"""File read / edit / write event handlers for the TUI renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.cli.event_rendering.unified_renderer import ActivityRenderer
from backend.cli.orient_tools import (
    OrientLineModel,
    file_read_action_model,
    file_read_observation_model,
)
from backend.cli.tui.helpers import (
    _count_text_lines,
    _count_unified_diff_changes,
    _encode_unified_diff_text,
    _format_diff_summary,
    _split_combined_diff,
)
from backend.cli.tui.renderer.helpers.file import (
    clean_file_edit_content,
    create_file_line_count,
    encode_create_file_diff,
    file_write_observation_diff,
    resolve_edit_mode_range,
    resolve_no_cmd_line_range,
)
from backend.ledger.action import FileEditAction, FileReadAction, FileWriteAction
from backend.ledger.observation import (
    FileEditObservation,
    FileReadObservation,
    FileWriteObservation,
)
from backend.ledger.observation.files import file_edit_observation_is_new_file

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )


def _discard_pending_file_card_widget(widget: Any) -> None:
    """Drop a stale pending file card when the observation type does not match."""
    try:
        widget.remove()
    except Exception:
        pass


def _write_create_file_diff_card(
    orch: 'RendererEventProcessorMixin',
    path: str,
    new_content: str,
    *,
    added: int | None = None,
) -> None:
    line_count = create_file_line_count(new_content, added)
    encoded = encode_create_file_diff(path, new_content)
    orch._write_tui_file_card(
        'Created',
        orch._compact_file_card_path(path),
        secondary=f'+{line_count}' if line_count else None,
        secondary_kind='ok' if line_count else 'neutral',
        extra_content=encoded,
        collapsed=True,
    )


def _finalize_pending_create_file_card(
    orch: 'RendererEventProcessorMixin',
    widget: Any,
    path: str,
    new_content: str,
    *,
    added: int | None = None,
) -> None:
    line_count = create_file_line_count(new_content, added)
    encoded = encode_create_file_diff(path, new_content)
    orch._update_activity_card_outcome(
        widget,
        status='ok',
        outcome=f'+{line_count}' if line_count else None,
        extra_content=encoded,
        diff_encoded=bool(encoded),
        collapse=False,
        operation_label=f'Created {orch._compact_file_card_path(path)}'.strip(),
    )


def _handle_file_read_action(
    orch: 'RendererEventProcessorMixin', event: FileReadAction
) -> None:
    path = getattr(event, 'path', '')
    model = file_read_action_model(event)
    orch._remember_pending_file_card(
        '_pending_file_read_cards_by_path',
        path,
        model,
    )
    orch._tui.set_current_operation(
        f'{model.verb} {model.target}'.strip(),
        meta='Reading',
        active=True,
    )


def _resolve_verb_from_registry(
    orch: 'RendererEventProcessorMixin',
    cmd: str,
    insert_line: int | None,
) -> tuple[str, str] | None:
    verb_entry = orch._FILE_EDIT_VERBS.get(cmd)
    if verb_entry is None:
        return None
    verb, include_stats = verb_entry
    if include_stats and insert_line is not None:
        return verb, f'line {insert_line}'
    return verb, ''


def _resolve_file_edit_verb_and_range(
    orch: 'RendererEventProcessorMixin',
    event: FileEditAction,
    cmd: str,
    insert_line: int | None,
    start: int,
    end: int,
    start_line: int | None,
    end_line: int | None,
) -> tuple[str, str]:
    result = _resolve_verb_from_registry(orch, cmd, insert_line)
    if result is not None:
        return result
    if not cmd:
        return resolve_no_cmd_line_range(start, end)
    if cmd == 'edit':
        result = resolve_edit_mode_range(event, start_line, end_line)
        if result is not None:
            return result
    return 'Edited', ''


def _handle_file_edit_create(
    orch: 'RendererEventProcessorMixin',
    event: FileEditAction,
    path: str,
) -> None:
    file_text = getattr(event, 'file_text', '') or ''
    if orch._has_pending_file_card(
        '_pending_file_create_cards_by_path',
        path,
    ):
        return
    card = ActivityRenderer.file_create(
        orch._compact_file_card_path(path),
        line_count=_count_text_lines(file_text),
    )
    widget = orch._write_card(card)
    orch._remember_pending_file_card(
        '_pending_file_create_cards_by_path',
        path,
        widget,
    )


def _handle_file_edit_action(
    orch: 'RendererEventProcessorMixin', event: FileEditAction
) -> None:
    cmd = getattr(event, 'command', '')
    path = event.path
    insert_line = getattr(event, 'insert_line', None)
    start = getattr(event, 'start', 1)
    end = getattr(event, 'end', -1)
    start_line = getattr(event, 'start_line', None)
    end_line = getattr(event, 'end_line', None)

    verb, line_range = _resolve_file_edit_verb_and_range(
        orch,
        event,
        cmd,
        insert_line,
        start,
        end,
        start_line,
        end_line,
    )

    if cmd == 'create_file':
        _handle_file_edit_create(orch, event, path)
    else:
        op_detail = f'{path} · {line_range}' if line_range else path
        orch._tui.set_current_operation(
            f'{verb} {op_detail}'.strip(),
            meta='Running',
            active=True,
        )


def _handle_file_write_action(
    orch: 'RendererEventProcessorMixin', event: FileWriteAction
) -> None:
    path = event.path
    if orch._has_pending_file_card('_pending_file_create_cards_by_path', path):
        return
    content = getattr(event, 'content', '') or ''
    card = ActivityRenderer.file_create(
        orch._compact_file_card_path(path),
        line_count=_count_text_lines(content),
    )
    widget = orch._write_card(card)
    orch._remember_pending_file_card(
        '_pending_file_create_cards_by_path',
        path,
        widget,
    )


def _handle_file_read_observation(
    orch: 'RendererEventProcessorMixin', event: FileReadObservation
) -> None:
    path = getattr(event, 'path', '') or ''
    pending = orch._take_pending_file_card(
        '_pending_file_read_cards_by_path',
        path,
    )
    if isinstance(pending, OrientLineModel):
        orch._write_orient_line(pending)
        return
    orch._write_orient_line(file_read_observation_model(event))


def _resolve_file_edit_pending_create(
    orch: 'RendererEventProcessorMixin',
    event: FileEditObservation,
    path: str,
    added: int,
) -> bool:
    pending_create = orch._take_pending_file_card(
        '_pending_file_create_cards_by_path',
        path,
    )
    if pending_create is None:
        return False
    if not file_edit_observation_is_new_file(event):
        _discard_pending_file_card_widget(pending_create)
        return False
    new_content = getattr(event, 'new_content', '') or ''
    _finalize_pending_create_file_card(
        orch,
        pending_create,
        path,
        new_content,
        added=added,
    )
    return True


def _handle_file_edit_new_file(
    orch: 'RendererEventProcessorMixin',
    event: FileEditObservation,
    path: str,
    added: int,
) -> None:
    new_content = getattr(event, 'new_content', '') or ''
    _write_create_file_diff_card(
        orch,
        path or event.path,
        new_content,
        added=added,
    )


def _write_multi_file_edit_card(
    orch: 'RendererEventProcessorMixin',
    fp: str,
    file_diff: str,
) -> None:
    f_added, f_removed = _count_unified_diff_changes(file_diff)
    encoded = _encode_unified_diff_text(file_diff, path=fp)
    if encoded:
        orch._write_tui_file_card(
            'Edited',
            fp,
            secondary=_format_diff_summary(f_added, f_removed),
            secondary_kind='ok' if f_added or f_removed else 'neutral',
            extra_content=encoded,
        )


def _write_multi_file_edit_cards(
    orch: 'RendererEventProcessorMixin',
    per_file: list,
) -> None:
    for fp, file_diff in per_file:
        _write_multi_file_edit_card(orch, fp, file_diff)


def _handle_file_edit_multi_file(
    orch: 'RendererEventProcessorMixin',
    event: FileEditObservation,
    path: str,
) -> None:
    diff_text = orch._extract_file_edit_diff(event)
    if diff_text:
        per_file = _split_combined_diff(diff_text)
        if per_file:
            _write_multi_file_edit_cards(orch, per_file)
        else:
            orch._write_card(ActivityRenderer.file_edit('Edited', path or '?'))
    else:
        orch._write_card(ActivityRenderer.file_edit('Edited', path or '?'))


def _resolve_existing_file_edit_diff(
    orch: 'RendererEventProcessorMixin',
    event: FileEditObservation,
    added: int,
    removed: int,
) -> tuple[str | None, int, int]:
    event_id = getattr(event, 'id', -1)
    if event_id >= 0:
        cached = getattr(orch, '_render_prep_cache', {}).get(event_id)
        if cached:
            return cached, added, removed
    encoded_diff = orch._extract_file_edit_group_rows(event)
    if encoded_diff:
        return encoded_diff, added, removed
    diff_text = orch._extract_file_edit_diff(event)
    if not (added or removed):
        added, removed = _count_unified_diff_changes(diff_text)
    encoded_diff = (
        _encode_unified_diff_text(
            diff_text,
            path=str(getattr(event, 'path', '') or ''),
        )
        if diff_text
        else None
    )
    return encoded_diff, added, removed


def _write_file_edit_existing_card(
    orch: 'RendererEventProcessorMixin',
    path: str,
    encoded_diff: str | None,
    added: int,
    removed: int,
) -> None:
    if encoded_diff:
        orch._write_tui_file_card(
            'Edited',
            path,
            secondary=_format_diff_summary(added, removed),
            secondary_kind='ok' if added or removed else 'neutral',
            extra_content=encoded_diff,
        )
    else:
        card = ActivityRenderer.file_edit(
            'Edited',
            path,
            added=added,
            removed=removed,
        )
        orch._write_card(card)


def _handle_file_edit_existing(
    orch: 'RendererEventProcessorMixin',
    event: FileEditObservation,
    path: str,
    added: int,
    removed: int,
) -> None:
    encoded_diff, added, removed = _resolve_existing_file_edit_diff(
        orch,
        event,
        added,
        removed,
    )
    _write_file_edit_existing_card(orch, path, encoded_diff, added, removed)


def _route_file_edit_observation(
    orch: 'RendererEventProcessorMixin',
    event: FileEditObservation,
    path: str,
    added: int,
    removed: int,
) -> None:
    if file_edit_observation_is_new_file(event):
        _handle_file_edit_new_file(orch, event, path, added)
    elif not path or path == '.':
        _handle_file_edit_multi_file(orch, event, path)
    else:
        _handle_file_edit_existing(orch, event, path, added, removed)


def _handle_file_edit_observation(
    orch: 'RendererEventProcessorMixin', event: FileEditObservation
) -> None:
    clean_file_edit_content(event)
    path = (getattr(event, 'path', '') or '').strip()
    added = event.added
    removed = event.removed
    if _resolve_file_edit_pending_create(orch, event, path, added):
        return
    _route_file_edit_observation(orch, event, path, added, removed)


def _handle_file_write_observation(
    orch: 'RendererEventProcessorMixin', event: FileWriteObservation
) -> None:
    path = event.path
    pending = orch._take_pending_file_card(
        '_pending_file_create_cards_by_path',
        path,
    )
    diff_text = file_write_observation_diff(event)
    if diff_text:
        added, removed = _count_unified_diff_changes(diff_text)
        encoded = _encode_unified_diff_text(diff_text, path=path)
        if encoded and pending is not None:
            orch._update_activity_card_outcome(
                pending,
                status='ok',
                outcome=_format_diff_summary(added, removed),
                extra_content=encoded,
                diff_encoded=True,
                collapse=False,
                operation_label=f'Wrote {path}'.strip(),
            )
            return
        if encoded:
            orch._write_tui_file_card(
                'Wrote',
                path,
                secondary=_format_diff_summary(added, removed),
                secondary_kind='ok' if added or removed else 'neutral',
                extra_content=encoded,
            )
            return
    new_content = getattr(event, 'new_content', None)
    if new_content is None:
        new_content = getattr(event, 'content', '') or ''
    if pending is not None:
        _finalize_pending_create_file_card(orch, pending, path, new_content)
        return
    _write_create_file_diff_card(orch, path, new_content)
