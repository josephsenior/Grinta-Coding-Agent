"""File read / edit event handlers for the TUI renderer.

Mounts :class:`EditCard` (1-line scan row with ⤢ detail) per edit.
Supports multiedit splitting — one card per entry in
``FileEditAction.structured_payload.file_edits[]``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
)
from backend.cli.tui.widgets.scan_line import (
    EditCard,
    _extract_syntax_error,
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


def _file_edit_is_undo(
    orch: 'RendererEventProcessorMixin',
    event: FileEditObservation,
    action: Any | None = None,
) -> bool:
    if action is not None and getattr(action, 'command', '') == 'undo_last_edit':
        return True
    cause_id = getattr(event, 'cause', None)
    if cause_id is not None:
        cause_action = orch._file_edit_actions_by_id.get(cause_id)
        if cause_action is not None and getattr(cause_action, 'command', '') == 'undo_last_edit':
            return True
    tool_result = getattr(event, 'tool_result', None) or {}
    if isinstance(tool_result, dict) and tool_result.get('operation') == 'undo_last_edit':
        return True
    content = getattr(event, 'content', '') or ''
    return content.startswith('Undid last edit')


def _undo_line_counts(event: FileEditObservation) -> tuple[int, int]:
    return getattr(event, 'added', 0) or 0, getattr(event, 'removed', 0) or 0


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
    content = getattr(event, 'content', '') or ''
    sys_pass = _parse_syntax_badge(content)
    syntax_error = _extract_syntax_error(content) if sys_pass == 'fail' else None

    cause_id = getattr(event, 'cause', None)
    action = None
    if cause_id is not None:
        action = orch._file_edit_actions_by_id.get(cause_id)

    is_undo = _file_edit_is_undo(orch, event, action)
    is_create = False if is_undo else file_edit_observation_is_new_file(event)
    added, removed = _undo_line_counts(event) if is_undo else (
        getattr(event, 'added', 0) or 0,
        getattr(event, 'removed', 0) or 0,
    )

    # ── create: derive add count from new_content ───────────────────
    if is_create and not added:
        nc = getattr(event, 'new_content', '') or ''
        if nc:
            added = nc.count('\n') + 1 if nc else 0

    # ── multiedit: find causing action and split per-item ────────────
    if action is not None and getattr(action, 'command', '') == 'multi_edit':
        _handle_multiedit_observation(
            orch, event, action, path, added, removed, is_create
        )
        return

    # ── single edit / undo ───────────────────────────────────────────
    encoded_diff = _resolve_edit_diff(
        orch, event, path, added, removed, is_create, is_undo=is_undo
    )
    orch._append_scan_line_card(
        EditCard(
            display_path=orch._compact_file_card_path(path),
            added=added,
            removed=removed,
            is_create=is_create,
            is_undo=is_undo,
            encoded_diff=encoded_diff,
            syntax_pass=sys_pass == 'pass' if sys_pass else None,
            syntax_error=syntax_error,
        )
    )


def _resolve_edit_diff(
    orch: 'RendererEventProcessorMixin',
    event: FileEditObservation,
    path: str,
    added: int,
    removed: int,
    is_create: bool,
    *,
    is_undo: bool = False,
) -> str | None:
    if is_create:
        new_content = getattr(event, 'new_content', '') or ''
        return encode_create_file_diff(path or event.path, new_content)

    # Check if the diff was already prepared async (avoids blocking git diff subprocess)
    event_id = getattr(event, 'id', -1)
    cache = getattr(orch, '_render_prep_cache', None)
    if cache is not None and event_id in cache:
        return cache[event_id]

    encoded = orch._extract_file_edit_group_rows(event)
    if encoded:
        return encoded

    diff_text = orch._extract_file_edit_diff(event)
    if diff_text:
        return _encode_unified_diff_text(diff_text, path=path or '')

    return None


def _structured_edit_file_receipts(event: FileEditObservation) -> list[dict[str, Any]]:
    tool_result = getattr(event, 'tool_result', None) or {}
    files = tool_result.get('files')
    if not isinstance(files, list):
        return []
    return [item for item in files if isinstance(item, dict)]


def _match_structured_edit_paths(left: str, right: str) -> bool:
    left_norm = left.replace('\\', '/').strip()
    right_norm = right.replace('\\', '/').strip()
    if not left_norm or not right_norm:
        return False
    return left_norm.endswith(right_norm) or right_norm.endswith(left_norm.split('/')[-1])


def _encode_receipt_diff(
    receipt: dict[str, Any],
    *,
    item_path: str,
    orch: 'RendererEventProcessorMixin',
) -> str | None:
    file_diff = receipt.get('diff')
    if isinstance(file_diff, str) and file_diff.strip():
        return _encode_unified_diff_text(file_diff, path=item_path)
    old_content = receipt.get('old_content')
    new_content = receipt.get('new_content')
    if isinstance(old_content, str) and isinstance(new_content, str):
        from backend.cli.tui.renderer.helpers.file import encode_create_file_diff

        if not old_content.strip() and new_content.strip():
            return encode_create_file_diff(item_path, new_content)
        encoded = orch._extract_file_edit_group_rows(
            type(
                '_Obs',
                (),
                {
                    'old_content': old_content,
                    'new_content': new_content,
                    'path': item_path,
                },
            )()
        )
        if encoded:
            return encoded
    return None


def _append_multiedit_cards_from_receipts(
    orch: 'RendererEventProcessorMixin',
    event: FileEditObservation,
    receipts: list[dict[str, Any]],
    *,
    is_create: bool,
    syntax_pass: str | None,
    syntax_error: str | None,
) -> bool:
    rendered = False
    seen_paths: set[str] = set()
    for receipt in receipts:
        if receipt.get('changed') is False:
            continue
        item_path = str(receipt.get('path') or '').strip()
        if not item_path or item_path in seen_paths:
            continue
        seen_paths.add(item_path)
        item_added = int(receipt.get('added') or 0)
        item_removed = int(receipt.get('removed') or 0)
        item_diff = _encode_receipt_diff(
            receipt,
            item_path=item_path,
            orch=orch,
        )
        orch._append_scan_line_card(
            EditCard(
                display_path=orch._compact_file_card_path(item_path),
                added=item_added,
                removed=item_removed,
                is_create=is_create,
                encoded_diff=item_diff,
                syntax_pass=syntax_pass == 'pass' if syntax_pass else None,
                syntax_error=syntax_error,
            )
        )
        rendered = True
    return rendered


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
    # Check cache first to avoid blocking git diff subprocess
    event_id = getattr(event, 'id', -1)
    cache = getattr(orch, '_render_prep_cache', None)
    if cache is not None and event_id in cache:
        diff_text = cache[event_id] or ''
    else:
        diff_text = orch._extract_file_edit_diff(event) or ''
    per_file = _split_combined_diff(diff_text) if diff_text else []

    content = getattr(event, 'content', '') or ''
    syntax_pass = _parse_syntax_badge(content)
    syntax_error = _extract_syntax_error(content) if syntax_pass == 'fail' else None

    receipts = _structured_edit_file_receipts(event)
    if receipts and _append_multiedit_cards_from_receipts(
        orch,
        event,
        receipts,
        is_create=is_create,
        syntax_pass=syntax_pass,
        syntax_error=syntax_error,
    ):
        return

    if not file_edits:
        # Fallback: one card for the whole operation
        encoded_diff = _resolve_edit_diff(orch, event, path, added, removed, is_create)
        orch._append_scan_line_card(
            EditCard(
                display_path=orch._compact_file_card_path(path),
                added=added,
                removed=removed,
                is_create=is_create,
                encoded_diff=encoded_diff,
                syntax_pass=syntax_pass == 'pass' if syntax_pass else None,
                syntax_error=syntax_error,
            )
        )
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
        receipt_match = next(
            (
                receipt
                for receipt in receipts
                if _match_structured_edit_paths(
                    str(receipt.get('path') or ''), str(item_path)
                )
            ),
            None,
        )
        if receipt_match is not None:
            item_added = int(receipt_match.get('added') or item_added)
            item_removed = int(receipt_match.get('removed') or item_removed)
            item_diff = _encode_receipt_diff(
                receipt_match,
                item_path=item_path,
                orch=orch,
            ) or item_diff
        else:
            for fp, file_diff in per_file:
                if _match_structured_edit_paths(fp, item_path):
                    item_added, item_removed = _count_unified_diff_changes(file_diff)
                    item_diff = _encode_unified_diff_text(
                        file_diff, path=item_path or fp
                    )
                    break

        orch._append_scan_line_card(
            EditCard(
                display_path=orch._compact_file_card_path(item_path),
                added=item_added,
                removed=item_removed,
                is_create=is_item_create,
                encoded_diff=item_diff,
                syntax_pass=syntax_pass == 'pass' if syntax_pass else None,
                syntax_error=syntax_error,
            )
        )
