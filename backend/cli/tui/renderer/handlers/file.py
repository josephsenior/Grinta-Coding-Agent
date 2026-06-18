"""File read / edit event handlers for the TUI renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.cli.tool_display.orient_tools import (
    OrientLineModel,
    file_read_action_model,
    file_read_observation_model,
)
from backend.cli.tui.helpers import (
    _count_unified_diff_changes,
    _encode_unified_diff_text,
    _split_combined_diff,
)
from backend.cli.tui.renderer.helpers.file import (
    clean_file_edit_content,
    encode_create_file_diff,
    file_change_outcome,
)
from backend.ledger.action import FileEditAction, FileReadAction
from backend.ledger.observation import FileEditObservation, FileReadObservation
from backend.ledger.observation.files import file_edit_observation_is_new_file

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )


def _mount_file_change(
    orch: 'RendererEventProcessorMixin',
    path: str,
    added: int,
    removed: int,
    encoded_diff: str | None,
    *,
    is_pure_create: bool,
) -> None:
    display_path = orch._compact_file_card_path(path or '?')
    outcome = file_change_outcome(added, removed, is_pure_create=is_pure_create)
    orch._mount_file_change_card(
        display_path=display_path,
        outcome=outcome,
        encoded_diff=encoded_diff,
        diff_path=path or '',
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


def _handle_file_edit_action(
    orch: 'RendererEventProcessorMixin', event: FileEditAction
) -> None:
    del orch, event


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


def _write_multi_file_change_cards(
    orch: 'RendererEventProcessorMixin',
    per_file: list[tuple[str, str]],
) -> None:
    for fp, file_diff in per_file:
        f_added, f_removed = _count_unified_diff_changes(file_diff)
        encoded = _encode_unified_diff_text(file_diff, path=fp)
        _mount_file_change(
            orch,
            fp,
            f_added,
            f_removed,
            encoded,
            is_pure_create=False,
        )


def _handle_file_edit_multi_file(
    orch: 'RendererEventProcessorMixin',
    event: FileEditObservation,
    path: str,
) -> None:
    diff_text = orch._extract_file_edit_diff(event)
    if not diff_text:
        _mount_file_change(orch, path or '?', 0, 0, None, is_pure_create=False)
        return
    per_file = _split_combined_diff(diff_text)
    if per_file:
        _write_multi_file_change_cards(orch, per_file)
        return
    added, removed = _count_unified_diff_changes(diff_text)
    encoded = _encode_unified_diff_text(diff_text, path=path or '')
    _mount_file_change(
        orch,
        path or '?',
        added,
        removed,
        encoded,
        is_pure_create=False,
    )


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


def _handle_file_edit_new_file(
    orch: 'RendererEventProcessorMixin',
    event: FileEditObservation,
    path: str,
    added: int,
) -> None:
    new_content = getattr(event, 'new_content', '') or ''
    encoded = encode_create_file_diff(path or event.path, new_content)
    from backend.cli.tui.helpers import _count_text_lines

    line_count = added or _count_text_lines(new_content)
    _mount_file_change(
        orch,
        path or event.path,
        line_count,
        0,
        encoded,
        is_pure_create=True,
    )


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
    if encoded_diff is None and getattr(event, 'new_content', None) is not None:
        from backend.cli.tui.helpers import _encode_diff_view_from_contents

        old_content = getattr(event, 'old_content', None) or ''
        new_content = getattr(event, 'new_content', '') or ''
        encoded_diff = _encode_diff_view_from_contents(
            old_content,
            new_content,
            path=path,
        )
    _mount_file_change(
        orch,
        path,
        added,
        removed,
        encoded_diff,
        is_pure_create=False,
    )


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
    _route_file_edit_observation(orch, event, path, event.added, event.removed)
