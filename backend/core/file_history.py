"""Centralized undo history for file modifications across execution environments."""

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Literal

_UNDO_MAX_PER_FILE = 32


@dataclass
class UndoSnapshot:
    """A snapshot of file content with metadata."""

    content: str | None  # None means file didn't exist
    editor: Literal["text_editor", "symbol_editor"]
    timestamp: float


class UndoHistoryManager:
    """Manages cross-tool file undo history with unified stack."""

    def __init__(self) -> None:
        self._history: defaultdict[str, deque[UndoSnapshot]] = defaultdict(
            lambda: deque(maxlen=_UNDO_MAX_PER_FILE)
        )

    def push(
        self, path: str, snapshot: str | None, editor: Literal["text_editor", "symbol_editor"]
    ) -> None:
        """Record a file snapshot before modification."""
        import time

        self._history[path].append(UndoSnapshot(content=snapshot, editor=editor, timestamp=time.time()))

    def pop(self, path: str) -> str | None:
        """Pop the last snapshot for a path, raising IndexError if empty."""
        snapshot = self._history[path].pop()
        return snapshot.content

    def pop_with_metadata(self, path: str) -> UndoSnapshot | None:
        """Pop the last snapshot including metadata."""
        if not self._history.get(path):
            return None
        return self._history[path].pop()

    def has_history(self, path: str) -> bool:
        """Check if history exists for a path."""
        return bool(self._history.get(path))

    def get_last_editor(self, path: str) -> str | None:
        """Get the editor type of the last edit."""
        if not self._history.get(path):
            return None
        return self._history[path][-1].editor

    def clear(self, path: str) -> None:
        """Clear history for a specific path."""
        if path in self._history:
            del self._history[path]

    def get_history_length(self, path: str) -> int:
        """Get the number of snapshots for a path."""
        return len(self._history.get(path, []))


# The global singleton holding cross-tool state
global_undo_manager = UndoHistoryManager()
