"""revert_to_checkpoint tool — rollback the workspace to a previous checkpoint.

Integrates with RollbackManager to allow the agent to undo changes,
especially when hitting errors after CmdRunAction or FileEditAction.
"""

from __future__ import annotations
from backend.core.config.utils import load_forge_config


import os

from backend.events.action.agent import AgentThinkAction
from backend.core.rollback.rollback_manager import RollbackManager

REVERT_TO_CHECKPOINT_TOOL_NAME = "revert_to_checkpoint"

_WORKSPACE_ROOT = load_forge_config(set_logging_levels=False).workspace_base or "."


def create_revert_to_checkpoint_tool() -> dict:
    """Return the OpenAI function-calling schema for revert_to_checkpoint."""
    return {
        "type": "function",
        "function": {
            "name": REVERT_TO_CHECKPOINT_TOOL_NAME,
            "description": (
                "Revert the entire workspace to a previously saved safe state. "
                    "Use this immediately after a command fails due to a bad file edit, "
                "to instantly undo all changes and start fresh without wasting turns manually fixing syntax errors."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "checkpoint_id": {
                        "description": (
                            "The specific checkpoint ID to return to. "
                            "If omitted, rolls back to the absolute most recent checkpoint available "
                            "(which is usually the auto-generated checkpoint before your last risky action)."
                        ),
                        "type": "string",
                    },
                },
            },
        },
    }


def build_revert_to_checkpoint_action(arguments: dict) -> AgentThinkAction:
    """Execute the rollback and return a think action describing the result."""
    checkpoint_id = arguments.get("checkpoint_id")

    manager = RollbackManager(
        workspace_path=_WORKSPACE_ROOT,
        max_checkpoints=30,
        auto_cleanup=True,
    )

    if not checkpoint_id:
        latest = manager.get_latest_checkpoint()
        if not latest:
            return AgentThinkAction(
                thought="[ROLLBACK] Failure: No checkpoints found. Cannot revert to safe state."
            )
        checkpoint_id = latest.id
    else:
        # Validate existence if ID was provided
        if not manager.get_checkpoint(checkpoint_id):
            return AgentThinkAction(
                thought=f"[ROLLBACK] Failure: Checkpoint ID '{checkpoint_id}' not found."
            )

    success = manager.rollback_to(checkpoint_id)
    if success:
        return AgentThinkAction(
            thought=f"[ROLLBACK] Success: Workspace has been safely reverted to checkpoint {checkpoint_id}."
        )
    else:
        return AgentThinkAction(
            thought=f"[ROLLBACK] Failure: Revert to checkpoint {checkpoint_id} failed. See logs for details."
        )
