"""checkpoint tool — save and restore progress markers.

Persists to ``.app/checkpoints.json``.  The agent can ``save`` a
checkpoint after completing a logical phase, and ``restore`` to see
what was done.  This complements the task_tracker by providing a
durable progress snapshot that survives condensation.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from backend.ledger.action.agent import AgentThinkAction

CHECKPOINT_TOOL_NAME = 'checkpoint'

_CHECKPOINTS_FILE = 'checkpoints.json'


def _checkpoints_path() -> Path:
    from backend.core.workspace_resolution import workspace_agent_state_dir

    return workspace_agent_state_dir() / _CHECKPOINTS_FILE


def _load_checkpoints() -> list[dict]:
    p = _checkpoints_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_checkpoints(checkpoints: list[dict]) -> None:
    p = _checkpoints_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(checkpoints, indent=2, ensure_ascii=False), encoding='utf-8'
    )


def create_checkpoint_tool() -> dict:
    """Return the OpenAI function-calling schema for checkpoint."""
    return {
        'type': 'function',
        'function': {
            'name': CHECKPOINT_TOOL_NAME,
            'description': (
                "Save or view progress checkpoints. Use 'save' after completing "
                "a logical phase of work (e.g., 'auth module complete'). Use "
                "'view' to see all saved checkpoints. Use 'clear' to reset."
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'command': {
                        'description': 'One of: save | view | clear',
                        'type': 'string',
                        'enum': ['save', 'view', 'clear'],
                    },
                    'label': {
                        'description': "For 'save': short description of what was completed.",
                        'type': 'string',
                    },
                    'files_modified': {
                        'description': "For 'save': comma-separated list of files that were changed.",
                        'type': 'string',
                    },
                },
                'required': ['command'],
            },
        },
    }


def build_checkpoint_action(arguments: dict) -> AgentThinkAction:
    """Execute a checkpoint command and return a think action with results."""
    command = arguments.get('command', 'view')

    if command == 'save':
        return _save_checkpoint(
            arguments.get('label', ''),
            arguments.get('files_modified', ''),
        )
    elif command == 'clear':
        return _clear_checkpoints()
    else:
        return _view_checkpoints()


def _save_checkpoint(label: str, files_modified: str) -> AgentThinkAction:
    if not label:
        return _checkpoint_result(
            command='save',
            ok=False,
            status='failed',
            reason_code='MISSING_LABEL',
            reason="save requires 'label' describing what was completed.",
            retryable=True,
            changed_state=False,
            next_best_action='Call checkpoint save with a short completion label.',
            human_message="[CHECKPOINT] save requires 'label' describing what was completed.",
        )

    checkpoints = _load_checkpoints()

    normalized_files = [f.strip() for f in files_modified.split(',') if f.strip()]
    if checkpoints:
        last = checkpoints[-1]
        last_label = str(last.get('label', ''))
        last_files = last.get('files') or []
        if not isinstance(last_files, list):
            last_files = []
        # Consecutive saves with the same label are treated as duplicate/no-op.
        # This keeps lite models from repeatedly "saving" identical progress.
        if last_label == label:
            return _checkpoint_result(
                command='save',
                ok=True,
                status='noop',
                reason_code='DUPLICATE_CHECKPOINT',
                reason='Latest checkpoint already has the same label.',
                retryable=False,
                changed_state=False,
                data={
                    'checkpoint_id': last.get('id'),
                    'label': label,
                    'files': last_files,
                    'total_checkpoints': len(checkpoints),
                },
                next_best_action=(
                    'Continue with the next task step, or call checkpoint save only after new progress.'
                ),
                human_message=(
                    f"[CHECKPOINT] No-op: latest checkpoint already matches '{label}'."
                ),
            )

    entry = {
        'id': len(checkpoints) + 1,
        'label': label,
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
    }
    if normalized_files:
        entry['files'] = normalized_files

    # Create a RollbackManager file snapshot so revert_to_checkpoint can actually
    # restore files when given this integer ID.
    try:
        from backend.core.rollback.rollback_manager import RollbackManager
        from backend.core.workspace_resolution import require_effective_workspace_root

        _manager = RollbackManager(
            workspace_path=str(require_effective_workspace_root()),
            max_checkpoints=30,
            auto_cleanup=True,
        )
        entry['rollback_id'] = _manager.create_checkpoint(
            description=label,
            checkpoint_type='manual',
            metadata={'files': normalized_files, 'checkpoint_tool_id': entry['id']},
        )
    except Exception:
        pass  # non-fatal — metadata checkpoint still saves cleanly

    checkpoints.append(entry)
    try:
        _save_checkpoints(checkpoints)
    except OSError as exc:
        return _checkpoint_result(
            command='save',
            ok=False,
            status='failed',
            reason_code='IO_ERROR',
            reason=str(exc),
            retryable=True,
            changed_state=False,
            data={'label': label, 'files': normalized_files},
            next_best_action='Check filesystem permissions and retry checkpoint save.',
            human_message=f"[CHECKPOINT] Failed to save '{label}': {exc}",
        )

    return _checkpoint_result(
        command='save',
        ok=True,
        status='saved',
        reason_code='CHECKPOINT_SAVED',
        reason='Checkpoint saved successfully.',
        retryable=False,
        changed_state=True,
        data={
            'checkpoint_id': entry['id'],
            'label': label,
            'files': normalized_files,
            'total_checkpoints': len(checkpoints),
        },
        next_best_action='Continue with the next planned step.',
        human_message=f'[CHECKPOINT] Saved #{entry["id"]}: {label}',
    )


def _view_checkpoints() -> AgentThinkAction:
    checkpoints = _load_checkpoints()
    if not checkpoints:
        return _checkpoint_result(
            command='view',
            ok=True,
            status='empty',
            reason_code='NO_CHECKPOINTS',
            reason='No checkpoints saved yet.',
            retryable=False,
            changed_state=False,
            data={'total_checkpoints': 0},
            next_best_action='Call checkpoint save after completing a logical phase.',
            human_message='[CHECKPOINT] No checkpoints saved yet.',
        )

    lines: list[str] = []
    for cp in checkpoints:
        files = ', '.join(cp.get('files', []))
        files_str = f' | files: {files}' if files else ''
        lines.append(
            f'  #{cp["id"]} [{cp.get("timestamp", "?")}] {cp["label"]}{files_str}'
        )
    return _checkpoint_result(
        command='view',
        ok=True,
        status='ok',
        reason_code='CHECKPOINTS_LISTED',
        reason='Checkpoints listed successfully.',
        retryable=False,
        changed_state=False,
        data={'total_checkpoints': len(checkpoints)},
        next_best_action='Use checkpoint save for new progress or continue execution.',
        human_message='[CHECKPOINT] Progress:\n' + '\n'.join(lines),
    )


def _clear_checkpoints() -> AgentThinkAction:
    checkpoints = _load_checkpoints()
    if not checkpoints:
        return _checkpoint_result(
            command='clear',
            ok=True,
            status='noop',
            reason_code='ALREADY_EMPTY',
            reason='Checkpoint store already empty.',
            retryable=False,
            changed_state=False,
            data={'total_checkpoints': 0},
            next_best_action='Continue with task execution.',
            human_message='[CHECKPOINT] No-op: checkpoint store already empty.',
        )
    try:
        _save_checkpoints([])
    except OSError as exc:
        return _checkpoint_result(
            command='clear',
            ok=False,
            status='failed',
            reason_code='IO_ERROR',
            reason=str(exc),
            retryable=True,
            changed_state=False,
            next_best_action='Check filesystem permissions and retry clear.',
            human_message=f'[CHECKPOINT] Failed to clear checkpoints: {exc}',
        )

    return _checkpoint_result(
        command='clear',
        ok=True,
        status='cleared',
        reason_code='CHECKPOINTS_CLEARED',
        reason='All checkpoints cleared.',
        retryable=False,
        changed_state=True,
        data={'cleared_count': len(checkpoints), 'total_checkpoints': 0},
        next_best_action='Continue with task execution.',
        human_message='[CHECKPOINT] All checkpoints cleared.',
    )


def _checkpoint_result(
    *,
    command: str,
    ok: bool,
    status: str,
    reason_code: str,
    reason: str,
    retryable: bool,
    changed_state: bool,
    next_best_action: str,
    human_message: str,
    data: dict[str, Any] | None = None,
) -> AgentThinkAction:
    """Return a human + structured checkpoint result for stronger tool feedback."""
    payload: dict[str, Any] = {
        'tool': CHECKPOINT_TOOL_NAME,
        'command': command,
        'ok': ok,
        'status': status,
        'reason_code': reason_code,
        'reason': reason,
        'retryable': retryable,
        'changed_state': changed_state,
        'next_best_action': next_best_action,
    }
    if data is not None:
        payload['data'] = data

    return AgentThinkAction(
        thought=f'{human_message}\n[CHECKPOINT_RESULT] {json.dumps(payload, ensure_ascii=False)}',
        source_tool='checkpoint',
    )
