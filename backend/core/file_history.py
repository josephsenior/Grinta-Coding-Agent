"""Centralized undo history for file modifications across execution environments."""

from collections import defaultdict, deque

_UNDO_MAX_PER_FILE = 32


class UndoHistoryManager:
    """Manages cross-tool file undo history."""

    def __init__(self) -> None:
        self._history: defaultdict[str, deque[str | None]] = defaultdict(
            lambda: deque(maxlen=_UNDO_MAX_PER_FILE)
        )

    def push(self, path: str, snapshot: str | None) -> None:
        """Record a file snapshot before modification."""
        self._history[path].append(snapshot)

    def pop(self, path: str) -> str | None:
        """Pop the last snapshot for a path, raising IndexError if empty."""
        return self._history[path].pop()

    def has_history(self, path: str) -> bool:
        """Check if history exists for a path."""
        return bool(self._history.get(path))

    def clear(self, path: str) -> None:
        """Clear history for a specific path."""
        if path in self._history:
            del self._history[path]


# The global singleton holding cross-tool state
global_undo_manager = UndoHistoryManager()
