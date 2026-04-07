"""revert_to_checkpoint tool — rollback the workspace to a previous checkpoint.

Integrates with RollbackManager to allow the agent to undo changes,
especially when hitting errors after CmdRunAction or FileEditAction.
"""

from __future__ import annotations

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
            return AgentThinkAction(
                thought='[ROLLBACK] Failure: No checkpoints found. Cannot revert to safe state.',
                source_tool='revert_to_checkpoint',
            )
        resolved_id = latest.id
    else:
        resolved_id = _resolve_rollback_id(checkpoint_id, manager)
        if resolved_id is None:
            return AgentThinkAction(
                thought=(
                    f"[ROLLBACK] Failure: Checkpoint ID '{checkpoint_id}' not found. "
                    "Use 'checkpoint view' to list available checkpoints."
                ),
                source_tool='revert_to_checkpoint',
            )

    success = manager.rollback_to(resolved_id)
    if success:
        return AgentThinkAction(
            thought=f'[ROLLBACK] Success: Workspace has been safely reverted to checkpoint {checkpoint_id}.',
            source_tool='revert_to_checkpoint',
        )
    else:
        return AgentThinkAction(
            thought=f'[ROLLBACK] Failure: Revert to checkpoint {checkpoint_id} failed. See logs for details.',
            source_tool='revert_to_checkpoint',
        )
