"""Session Checkpoint Manager for explicit save/resume."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.logger import forge_logger as logger
from backend.persistence.locations import get_conversation_checkpoints_dir

if TYPE_CHECKING:
    from backend.orchestration.state.state import State
    from backend.persistence.files import FileStore


class SessionCheckpointManager:
    """Manages named checkpoints for agent sessions."""

    def __init__(
        self, sid: str, file_store: FileStore, user_id: str | None = None
    ) -> None:
        """Initialize the checkpoint manager.

        Args:
            sid: Session ID
            file_store: File storage backend
            user_id: Optional user ID for scoping

        """
        self.sid = sid
        self.file_store = file_store
        self.user_id = user_id

    def save_checkpoint(self, name: str, state: State) -> None:
        """Save a named checkpoint.

        Args:
            name: Name of the checkpoint (e.g., "after_research")
            state: Current agent state to save

        """
        try:
            # Enforce valid characters in checkpoint name to prevent path traversals
            clean_name = "".join(c for c in name if c.isalnum() or c in "_-")
            if not clean_name:
                raise ValueError("Invalid checkpoint name")

            checkpoint_dir = get_conversation_checkpoints_dir(self.sid, self.user_id)
            checkpoint_path = f"{checkpoint_dir}{clean_name}.json"

            # Use State's JSON serialization logic
            if hasattr(state, "_to_json_str"):
                encoded = state._to_json_str()
            else:
                # Fallback if method is missing (should not happen with correct State)
                # This suggests State interface might have changed or we are mocking it
                logger.warning(
                    "State object missing _to_json_str, creating ad-hoc dump"
                )
                import json

                encoded = json.dumps(state.__dict__, default=str)

            self.file_store.write(checkpoint_path, encoded)
            logger.info("Saved checkpoint '%s' for session %s", clean_name, self.sid)

        except Exception as e:
            logger.error("Failed to save checkpoint '%s': %s", name, e)
            raise

    def list_checkpoints(self) -> list[str]:
        """List available named checkpoints.

        Returns:
            List of checkpoint names

        """
        checkpoint_dir = get_conversation_checkpoints_dir(self.sid, self.user_id)
        try:
            files = self.file_store.list(checkpoint_dir)
            return [f.replace(".json", "") for f in files if f.endswith(".json")]
        except Exception:
            # If directory doesn't exist or error listing
            return []

    def restore_checkpoint(self, name: str) -> State | None:
        """Restore state from a named checkpoint.

        Args:
            name: Name of the checkpoint to restore

        Returns:
            Restored State object or None if not found

        """
        from backend.orchestration.state.state import State

        try:
            clean_name = "".join(c for c in name if c.isalnum() or c in "_-")
            checkpoint_dir = get_conversation_checkpoints_dir(self.sid, self.user_id)
            checkpoint_path = f"{checkpoint_dir}{clean_name}.json"

            raw = self.file_store.read(checkpoint_path)
            state = State._from_raw(raw)

            logger.info("Restored checkpoint '%s' for session %s", clean_name, self.sid)
            return state

        except FileNotFoundError:
            logger.warning("Checkpoint '%s' not found", name)
            return None
        except Exception as e:
            logger.error("Failed to restore checkpoint '%s': %s", name, e)
            return None

    def delete_checkpoint(self, name: str) -> None:
        """Delete a named checkpoint.

        Args:
            name: Name of the checkpoint to delete

        """
        try:
            clean_name = "".join(c for c in name if c.isalnum() or c in "_-")
            checkpoint_dir = get_conversation_checkpoints_dir(self.sid, self.user_id)
            checkpoint_path = f"{checkpoint_dir}{clean_name}.json"

            self.file_store.delete(checkpoint_path)
            logger.info("Deleted checkpoint '%s'", clean_name)

        except Exception as e:
            logger.error("Failed to delete checkpoint '%s': %s", name, e)
