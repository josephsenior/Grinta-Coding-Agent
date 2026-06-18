"""File read / edit event handlers for the TUI renderer.

Mounts :class:`EditCard` (1-line scan row with ⤢ detail) per edit.
Supports multiedit splitting — one card per entry in
``FileEditAction.structured_payload.file_edits[]``.
"""

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
from backend.cli.tui.widgets.scan_line import (
    EditCard,
    _compact_path,
    _extract_syntax_error,
    _format_diff_delta,
    _parse_syntax_badge,
)
from backend.ledger.action import FileEditAction, FileReadAction
from backend.ledger.observation import FileEditObservation, FileReadObservation
from backend.ledger.observation.files import file_edit_observation_is_new_file

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
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
    eid = getattr(event, 'id', -1)
    if eid >= 0:
        orch._file_edit_actions_by_id[eid] = event


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


def _handle_file_edit_observation(
    orch: 'RendererEventProcessorMixin', event: FileEditObservation
) -> None:
    clean_file_edit_content(event)
    path = (getattr(event, 'path', '') or '').strip()
    added = getattr(event, 'added', 0) or 0
    removed = getattr(event, 'removed', 0) or 0
    is_create = file_edit_observation_is_new_file(event)
    content = getattr(event, 'content', '') or ''
    sys_pass = _parse_syntax_badge(content)
    syntax_error = _extract_syntax_error(content) if sys_pass == 'fail' else None

    # ── create: derive add count from new_content ───────────────────
    if is_create and not added:
        nc = getattr(event, 'new_content', '') or ''
        if nc:
            added = nc.count('\n') + 1 if nc else 0

    # ── multiedit: find causing action and split per-item ────────────
    cause_id = getattr(event, 'cause', None)
    action = None
    if cause_id is not None:
        action = orch._file_edit_actions_by_id.get(cause_id)

    if action is not None and getattr(action, 'command', '') == 'multi_edit':
        _handle_multiedit_observation(orch, event, action, path,
                                       added, removed, is_create)
        return

    # ── single edit ──────────────────────────────────────────────────
    encoded_diff = _resolve_edit_diff(orch, event, path, added, removed, is_create)
    orch._append_scan_line_card(EditCard(
        display_path=orch._compact_file_card_path(path),
        added=added,
        removed=removed,
        is_create=is_create,
        encoded_diff=encoded_diff,
        syntax_pass=sys_pass == 'pass' if sys_pass else None,
        syntax_error=syntax_error,
    ))


def _resolve_edit_diff(
    orch: 'RendererEventProcessorMixin',
    event: FileEditObservation,
    path: str,
    added: int,
    removed: int,
    is_create: bool,
) -> str | None:
    if is_create:
        new_content = getattr(event, 'new_content', '') or ''
        return encode_create_file_diff(path or event.path, new_content)

    encoded = orch._extract_file_edit_group_rows(event)
    if encoded:
        return encoded

    diff_text = orch._extract_file_edit_diff(event)
    if diff_text:
        return _encode_unified_diff_text(diff_text, path=path or '')

    return None


def _handle_multiedit_observation(
    orch: 'RendererEventProcessorMixin',
    event: FileEditObservation,
    action: Any,
    path: str,
    added: int,
    removed: int,
    is_create: bool,
) -> None:
    payload = getattr(action, 'structured_payload', None)
    file_edits = (payload or {}).get('file_edits') or []

    # Get per-file diff chunks from the combined observation diff
    diff_text = orch._extract_file_edit_diff(event) or ''
    per_file = _split_combined_diff(diff_text) if diff_text else []

    # Map filename → diff chunk
    per_file_map: dict[str, str] = {}
    for fp, file_diff in per_file:
        key = fp.replace('\\', '/').split('/')[-1] if len(fp.replace('\\', '/').split('/')) > 1 else fp
        per_file_map[fp] = file_diff

    content = getattr(event, 'content', '') or ''
    syntax_pass = _parse_syntax_badge(content)
    syntax_error = _extract_syntax_error(content) if syntax_pass == 'fail' else None

    if not file_edits:
        # Fallback: one card for the whole operation
        encoded_diff = _resolve_edit_diff(orch, event, path, added, removed, is_create)
        orch._append_scan_line_card(EditCard(
            display_path=orch._compact_file_card_path(path),
            added=added,
            removed=removed,
            is_create=is_create,
            encoded_diff=encoded_diff,
            syntax_pass=syntax_pass == 'pass' if syntax_pass else None,
            syntax_error=syntax_error,
        ))
        return

    for item in file_edits:
        if not isinstance(item, dict):
            continue
        item_path = item.get('path', path)
        item_added = 0
        item_removed = 0
        item_diff = None
        is_item_create = item.get('command') == 'create_file' or is_create

        # Try to find a per-file diff chunk
        for fp, file_diff in per_file:
            if fp.endswith(item_path) or item_path.endswith(fp.split('/')[-1]):
                item_added, item_removed = _count_unified_diff_changes(file_diff)
                item_diff = _encode_unified_diff_text(file_diff, path=item_path or fp)
                break

        orch._append_scan_line_card(EditCard(
            display_path=orch._compact_file_card_path(item_path),
            added=item_added,
            removed=item_removed,
            is_create=is_item_create,
            encoded_diff=item_diff,
            syntax_pass=syntax_pass == 'pass' if syntax_pass else None,
            syntax_error=syntax_error,
        ))
