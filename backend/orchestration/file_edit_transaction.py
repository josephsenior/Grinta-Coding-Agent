"""Response-scoped transaction guard for model-emitted file edits.

The public file tools should stay simple for the model: emit the clear edit
intent and let the runtime/orchestrator handle reliability. This coordinator
wraps adjacent file-edit tool calls from one model response with a best-effort
rollback boundary so a later stale anchor does not leave earlier edits committed.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.core.logger import app_logger as logger
from backend.core.type_safety.path_validation import PathValidationError, SafePath
from backend.ledger import EventSource
from backend.ledger.action import FileEditAction
from backend.ledger.observation import ErrorObservation, Observation

_TRANSACTIONAL_EDIT_COMMANDS = frozenset(
    {
        'create_file',
        'edit',
        'insert_text',
        'multi_edit',
        'replace_string',
    }
)


@dataclass(slots=True)
class _FileSnapshot:
    path: Path
    display_path: str
    existed: bool
    was_file: bool
    content: bytes | None


@dataclass(slots=True)
class _EditTransaction:
    response_id: str
    tool_call_ids: set[str] = field(default_factory=set)
    completed_tool_call_ids: set[str] = field(default_factory=set)
    snapshots: dict[Path, _FileSnapshot] = field(default_factory=dict)


def get_file_edit_transaction_coordinator(
    controller: Any,
) -> 'FileEditTransactionCoordinator':
    coordinator = getattr(controller, '_file_edit_transaction_coordinator', None)
    if isinstance(coordinator, FileEditTransactionCoordinator):
        return coordinator
    coordinator = FileEditTransactionCoordinator(controller)
    setattr(controller, '_file_edit_transaction_coordinator', coordinator)
    return coordinator


def _is_transactional_file_edit(action: Any) -> bool:
    if not isinstance(action, FileEditAction):
        return False
    command = str(getattr(action, 'command', '') or '').strip().lower()
    return command in _TRANSACTIONAL_EDIT_COMMANDS


def _tool_call_id(action: Any) -> str | None:
    metadata = getattr(action, 'tool_call_metadata', None)
    tool_call_id = getattr(metadata, 'tool_call_id', None)
    if isinstance(tool_call_id, str) and tool_call_id.strip():
        return tool_call_id.strip()
    return None


def _response_id(action: Any) -> str | None:
    response_id = getattr(action, 'response_id', None)
    if isinstance(response_id, str) and response_id.strip():
        return response_id.strip()

    metadata = getattr(action, 'tool_call_metadata', None)
    model_response = getattr(metadata, 'model_response', None)
    if isinstance(model_response, dict):
        response_id = model_response.get('id')
        if isinstance(response_id, str) and response_id.strip():
            return response_id.strip()
    return None


def _workspace_root(controller: Any) -> Path | None:
    runtime = getattr(controller, 'runtime', None)
    for attr in ('workspace_root', 'initial_cwd'):
        value = getattr(runtime, attr, None)
        if value:
            try:
                return Path(value).expanduser().resolve()
            except (OSError, TypeError, ValueError):
                pass

    try:
        from backend.core.workspace_resolution import get_effective_workspace_root

        root = get_effective_workspace_root()
        return root.expanduser().resolve() if root is not None else None
    except Exception:
        return None


def _resolve_action_path(root: Path, raw_path: str) -> Path:
    return SafePath.validate(
        raw_path,
        workspace_root=str(root),
        must_be_relative=True,
    ).path


def _structured_edit_paths(action: FileEditAction) -> Iterable[str]:
    payload = getattr(action, 'structured_payload', None)
    if not isinstance(payload, dict):
        return ()
    file_edits = payload.get('file_edits')
    if not isinstance(file_edits, list):
        return ()
    paths: list[str] = []
    for item in file_edits:
        if not isinstance(item, dict):
            continue
        path = item.get('path')
        if isinstance(path, str) and path.strip():
            paths.append(path.strip())
    return paths


def _target_paths_for_action(root: Path, action: FileEditAction) -> list[Path]:
    command = str(getattr(action, 'command', '') or '').strip().lower()
    raw_paths: Iterable[str]
    if command == 'multi_edit':
        raw_paths = _structured_edit_paths(action)
    else:
        path = str(getattr(action, 'path', '') or '').strip()
        raw_paths = (path,) if path else ()

    resolved: list[Path] = []
    seen: set[Path] = set()
    for raw_path in raw_paths:
        try:
            resolved_path = _resolve_action_path(root, raw_path).resolve()
        except (PathValidationError, OSError, ValueError) as exc:
            logger.debug(
                'Skipping file edit transaction snapshot for invalid path %r: %s',
                raw_path,
                exc,
            )
            continue
        if resolved_path in seen:
            continue
        seen.add(resolved_path)
        resolved.append(resolved_path)
    return resolved


def _observation_failed(observation: Observation) -> bool:
    if isinstance(observation, ErrorObservation):
        return True
    tool_result = getattr(observation, 'tool_result', None)
    return isinstance(tool_result, dict) and tool_result.get('ok') is False


class FileEditTransactionCoordinator:
    """Best-effort transaction boundary for adjacent same-response file edits."""

    def __init__(self, controller: Any) -> None:
        self._controller = controller
        self._transactions: dict[str, _EditTransaction] = {}

    def before_action(self, action: Any) -> None:
        if not _is_transactional_file_edit(action):
            return
        response_id = _response_id(action)
        tool_call_id = _tool_call_id(action)
        if response_id is None or tool_call_id is None:
            return

        transaction = self._transactions.get(response_id)
        if transaction is not None:
            transaction.tool_call_ids.add(tool_call_id)
            self._snapshot_action_paths(transaction, action)
            return

        group = self._contiguous_edit_group(action, response_id)
        if len(group) < 2:
            return

        transaction = _EditTransaction(response_id=response_id)
        for grouped in group:
            grouped_tool_call_id = _tool_call_id(grouped)
            if grouped_tool_call_id:
                transaction.tool_call_ids.add(grouped_tool_call_id)
            self._snapshot_action_paths(transaction, grouped)

        if transaction.tool_call_ids and transaction.snapshots:
            self._transactions[response_id] = transaction

    def after_observation(
        self,
        action: Any,
        observation: Observation,
    ) -> Observation:
        if not _is_transactional_file_edit(action):
            return observation
        response_id = _response_id(action)
        tool_call_id = _tool_call_id(action)
        if response_id is None or tool_call_id is None:
            return observation

        transaction = self._transactions.get(response_id)
        if transaction is None:
            return observation

        transaction.completed_tool_call_ids.add(tool_call_id)
        if _observation_failed(observation):
            restored, restore_errors = self._restore_snapshots(transaction)
            skipped = self._drop_remaining_queued_edits(
                transaction,
                current_tool_call_id=tool_call_id,
            )
            self._mark_rolled_back(
                observation,
                restored=restored,
                restore_errors=restore_errors,
                skipped_tool_call_ids=skipped,
            )
            self._emit_skipped_observations(skipped)
            self._transactions.pop(response_id, None)
            return observation

        if transaction.tool_call_ids.issubset(transaction.completed_tool_call_ids):
            self._transactions.pop(response_id, None)
        return observation

    def _contiguous_edit_group(
        self,
        action: FileEditAction,
        response_id: str,
    ) -> list[FileEditAction]:
        group = [action]
        pending = getattr(
            getattr(self._controller, 'agent', None), 'pending_actions', None
        )
        if not pending:
            return group
        for queued in list(pending):
            if (
                not _is_transactional_file_edit(queued)
                or _response_id(queued) != response_id
            ):
                break
            group.append(queued)
        return group

    def _snapshot_action_paths(
        self,
        transaction: _EditTransaction,
        action: FileEditAction,
    ) -> None:
        root = _workspace_root(self._controller)
        if root is None:
            logger.debug('Skipping file edit transaction snapshot: no workspace root')
            return
        for path in _target_paths_for_action(root, action):
            if path in transaction.snapshots:
                continue
            display_path = self._display_path(root, path)
            try:
                existed = path.exists()
                was_file = path.is_file()
                content = path.read_bytes() if was_file else None
            except OSError as exc:
                logger.debug(
                    'Could not snapshot %s for file edit transaction: %s',
                    path,
                    exc,
                )
                continue
            transaction.snapshots[path] = _FileSnapshot(
                path=path,
                display_path=display_path,
                existed=existed,
                was_file=was_file,
                content=content,
            )

    @staticmethod
    def _display_path(root: Path, path: Path) -> str:
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return str(path)

    def _restore_snapshots(
        self,
        transaction: _EditTransaction,
    ) -> tuple[list[str], list[str]]:
        restored: list[str] = []
        errors: list[str] = []
        for snapshot in transaction.snapshots.values():
            try:
                if snapshot.existed and snapshot.was_file:
                    snapshot.path.parent.mkdir(parents=True, exist_ok=True)
                    snapshot.path.write_bytes(snapshot.content or b'')
                    restored.append(snapshot.display_path)
                    continue
                if not snapshot.existed:
                    if snapshot.path.exists() and snapshot.path.is_file():
                        snapshot.path.unlink()
                        restored.append(snapshot.display_path)
                    elif snapshot.path.exists():
                        errors.append(
                            f'{snapshot.display_path}: created path is not a file; left in place'
                        )
                    continue
                errors.append(
                    f'{snapshot.display_path}: original path was not a regular file; left in place'
                )
            except OSError as exc:
                errors.append(f'{snapshot.display_path}: {exc}')
        return restored, errors

    def _drop_remaining_queued_edits(
        self,
        transaction: _EditTransaction,
        *,
        current_tool_call_id: str,
    ) -> dict[str, Any]:
        pending = getattr(
            getattr(self._controller, 'agent', None), 'pending_actions', None
        )
        if pending is None:
            return {}
        remaining = transaction.tool_call_ids - transaction.completed_tool_call_ids
        remaining.discard(current_tool_call_id)
        if not remaining:
            return {}

        kept: deque[Any] = deque()
        skipped: dict[str, Any] = {}
        for queued in list(pending):
            queued_tool_call_id = _tool_call_id(queued)
            if (
                _is_transactional_file_edit(queued)
                and _response_id(queued) == transaction.response_id
                and queued_tool_call_id in remaining
            ):
                skipped[queued_tool_call_id] = queued
                continue
            kept.append(queued)

        try:
            pending.clear()
            pending.extend(kept)
        except AttributeError:
            if isinstance(pending, list):
                pending[:] = list(kept)
        return skipped

    @staticmethod
    def _mark_rolled_back(
        observation: Observation,
        *,
        restored: list[str],
        restore_errors: list[str],
        skipped_tool_call_ids: dict[str, Any],
    ) -> None:
        restored_lines = '\n'.join(f'- {path}' for path in sorted(restored))
        skipped_lines = '\n'.join(
            f'- {tool_id}' for tool_id in sorted(skipped_tool_call_ids)
        )
        error_lines = '\n'.join(f'- {err}' for err in restore_errors)
        sections = [
            '[FILE_EDIT_TRANSACTION_ROLLBACK]',
            (
                'A file edit from this assistant response failed. The runtime '
                'restored files touched by the adjacent edit batch to their '
                'pre-response contents. Re-read the affected files before retrying.'
            ),
        ]
        if restored_lines:
            sections.append('Restored files:\n' + restored_lines)
        if skipped_lines:
            sections.append('Skipped queued edit tool calls:\n' + skipped_lines)
        if error_lines:
            sections.append('Rollback warnings:\n' + error_lines)

        suffix = '\n\n'.join(sections)
        observation.content = (
            f'{observation.content}\n\n{suffix}' if observation.content else suffix
        )

        tool_result = dict(observation.tool_result or {})
        tool_result.update(
            {
                'ok': False,
                'retryable': True,
                'error_code': 'FILE_EDIT_TRANSACTION_ROLLED_BACK',
                'rolled_back': True,
                'restored_files': sorted(restored),
                'rollback_warnings': restore_errors,
                'skipped_tool_call_ids': sorted(skipped_tool_call_ids),
            }
        )
        observation.tool_result = tool_result

    def _emit_skipped_observations(self, skipped: dict[str, Any]) -> None:
        event_stream = getattr(self._controller, 'event_stream', None)
        if event_stream is None:
            return
        for tool_call_id, action in skipped.items():
            obs = ErrorObservation(
                content=(
                    'FILE_EDIT_TRANSACTION_ABORTED: this queued edit was skipped '
                    'because an earlier adjacent edit from the same assistant '
                    'response failed. The runtime rolled back the batch; re-read '
                    'the affected files and retry only the edits still needed.'
                ),
                error_id='FILE_EDIT_TRANSACTION_ABORTED',
            )
            obs.tool_call_metadata = getattr(action, 'tool_call_metadata', None)
            obs.tool_result = {
                'ok': False,
                'retryable': True,
                'error_code': 'FILE_EDIT_TRANSACTION_ABORTED',
                'action': getattr(action, 'action', None),
                'skipped_tool_call_id': tool_call_id,
            }
            event_stream.add_event(obs, EventSource.ENVIRONMENT)


__all__ = [
    'FileEditTransactionCoordinator',
    'get_file_edit_transaction_coordinator',
]
