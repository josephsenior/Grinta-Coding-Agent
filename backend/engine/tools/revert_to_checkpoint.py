"""revert_to_checkpoint tool — rollback the workspace to a previous checkpoint.

Integrates with RollbackManager to allow the agent to undo changes,
especially when hitting errors after CmdRunAction or FileEditAction.
"""

from __future__ import annotations

import json

from backend.core.rollback.rollback_manager import RollbackManager
from backend.ledger.action.agent import AgentThinkAction

REVERT_TO_CHECKPOINT_TOOL_NAME = 'revert_to_checkpoint'


def create_revert_to_checkpoint_tool() -> dict:
    """Return the OpenAI function-calling schema for revert_to_checkpoint."""
    return {
        'type': 'function',
        'function': {
            'name': REVERT_TO_CHECKPOINT_TOOL_NAME,
            'description': (
                'Revert the entire workspace to a previously saved safe state. '
                'Use this immediately after a command fails due to a bad file edit, '
                'to instantly undo all changes and start fresh without wasting turns manually fixing syntax errors.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'checkpoint_id': {
                        'description': (
                            'The specific checkpoint ID to return to. '
                            'If omitted, rolls back to the absolute most recent checkpoint available '
                            '(which is usually the auto-generated checkpoint before your last risky action).'
                        ),
                        'type': 'string',
                    },
                },
            },
        },
    }


def _resolve_rollback_id(checkpoint_id: str, manager: RollbackManager) -> str | None:
    """Map a user-facing checkpoint ID to a RollbackManager ID.

    The ``checkpoint`` tool assigns simple integer IDs (1, 2, 3…) and stores a
    ``rollback_id`` cross-reference in checkpoints.json alongside each entry.
    RollbackManager uses its own ``cp_<timestamp>_<hex>`` IDs internally.
    This helper bridges the two so that ``revert_to_checkpoint(1)`` works.
    """
    if checkpoint_id.isdigit():
        import json as _json

        from backend.engine.tools.checkpoint import _checkpoints_path

        path = _checkpoints_path()
        if path.exists():
            try:
                entries = _json.loads(path.read_text(encoding='utf-8'))
                if isinstance(entries, list):
                    for cp in entries:
                        if str(cp.get('id', '')) == checkpoint_id:
                            rid = cp.get('rollback_id')
                            return str(rid) if rid else None
            except Exception:
                pass
        return None

    # Native RollbackManager ID — verify it exists.
    return checkpoint_id if manager.get_checkpoint(checkpoint_id) else None


def build_revert_to_checkpoint_action(arguments: dict) -> AgentThinkAction:
    """Execute the rollback and return a think action describing the result."""
    from backend.core.workspace_resolution import require_effective_workspace_root

    checkpoint_id = (arguments.get('checkpoint_id') or '').strip()

    manager = RollbackManager(
        workspace_path=str(require_effective_workspace_root()),
        max_checkpoints=30,
        auto_cleanup=True,
    )

    if not checkpoint_id:
        latest = manager.get_latest_checkpoint()
        if not latest:
            return _revert_result(
                ok=False,
                status='failed',
                reason_code='NO_CHECKPOINTS',
                reason='No checkpoints found. Cannot revert to a safe state.',
                retryable=True,
                changed_state=False,
                next_best_action='Create a checkpoint after a safe milestone, then retry revert_to_checkpoint.',
                human_message='[ROLLBACK] Failure: No checkpoints found. Cannot revert to safe state.',
            )
        resolved_id = latest.id
        target_label = 'latest checkpoint'
    else:
        resolved_id = _resolve_rollback_id(checkpoint_id, manager)  # type: ignore
        if resolved_id is None:
            return _revert_result(  # type: ignore
                ok=False,
                status='failed',
                reason_code='CHECKPOINT_NOT_FOUND',
                reason=(
                    f"Checkpoint ID '{checkpoint_id}' was not found. "
                    'Use checkpoint view to list available checkpoints.'
                ),
                retryable=True,
                changed_state=False,
                data={'requested_checkpoint_id': checkpoint_id},
                next_best_action='Call checkpoint view to inspect valid checkpoints, then retry revert_to_checkpoint.',
                human_message=(
                    f"[ROLLBACK] Failure: Checkpoint ID '{checkpoint_id}' not found. "
                    "Use 'checkpoint view' to list available checkpoints."
                ),
            )
        target_label = f'checkpoint {checkpoint_id}'

    success = manager.rollback_to(resolved_id)
    if success:
        return _revert_result(
            ok=True,
            status='reverted',
            reason_code='ROLLBACK_COMPLETED',
            reason='Workspace rollback completed successfully.',
            retryable=False,
            changed_state=True,
            data={
                'requested_checkpoint_id': checkpoint_id or None,
                'resolved_checkpoint_id': resolved_id,
            },
            next_best_action='Re-run the next safe step or continue from the restored checkpoint state.',
            human_message=(
                f'[ROLLBACK] Success: Workspace has been safely reverted to {target_label}.'
            ),
        )
    else:
        return _revert_result(
            ok=False,
            status='failed',
            reason_code='ROLLBACK_FAILED',
            reason='Rollback failed. See logs for details.',
            retryable=True,
            changed_state=False,
            data={
                'requested_checkpoint_id': checkpoint_id or None,
                'resolved_checkpoint_id': resolved_id,
            },
            next_best_action='Inspect the rollback logs, then retry revert_to_checkpoint or recover manually.',
            human_message=(
                f'[ROLLBACK] Failure: Revert to {target_label} failed. See logs for details.'
            ),
        )


def _revert_result(
    *,
    ok: bool,
    status: str,
    reason_code: str,
    reason: str,
    retryable: bool,
    changed_state: bool,
    next_best_action: str,
    human_message: str,
    data: dict | None = None,
) -> AgentThinkAction:
    payload: dict[str, object] = {
        'tool': REVERT_TO_CHECKPOINT_TOOL_NAME,
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

    action = AgentThinkAction(
        thought=f'{human_message}\n[REVERT_RESULT] {json.dumps(payload, ensure_ascii=False)}',
        source_tool=REVERT_TO_CHECKPOINT_TOOL_NAME,
    )
    action.tool_result = payload
    return action
