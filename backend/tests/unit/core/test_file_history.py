"""Unit tests for the UndoHistoryManager file modification history."""

from __future__ import annotations

import time
import pytest

from backend.core.file_history import (
    UndoHistoryManager,
    UndoSnapshot,
    global_undo_manager,
)


def test_manager_initial_state() -> None:
    manager = UndoHistoryManager()
    path = "dummy_file.txt"
    assert manager.has_history(path) is False
    assert manager.get_history_length(path) == 0
    assert manager.get_last_editor(path) is None
    assert manager.pop_with_metadata(path) is None


def test_manager_push_pop_basic() -> None:
    manager = UndoHistoryManager()
    path = "file.py"

    # Push snapshot
    manager.push(path, "print('hello')", "file_edit")
    assert manager.has_history(path) is True
    assert manager.get_history_length(path) == 1
    assert manager.get_last_editor(path) == "file_edit"

    # Push another snapshot
    manager.push(path, "print('hello world')", "symbol_edit")
    assert manager.get_history_length(path) == 2
    assert manager.get_last_editor(path) == "symbol_edit"

    # Pop last snapshot
    last_content = manager.pop(path)
    assert last_content == "print('hello world')"
    assert manager.get_history_length(path) == 1
    assert manager.get_last_editor(path) == "file_edit"

    # Pop remaining
    first_content = manager.pop(path)
    assert first_content == "print('hello')"
    assert manager.get_history_length(path) == 0
    assert manager.has_history(path) is False


def test_manager_pop_empty_raises_index_error() -> None:
    manager = UndoHistoryManager()
    path = "empty.txt"
    with pytest.raises(IndexError):
        manager.pop(path)


def test_manager_pop_with_metadata() -> None:
    manager = UndoHistoryManager()
    path = "meta.txt"

    before_time = time.time()
    manager.push(path, "some content", "file_edit")
    after_time = time.time()

    snapshot = manager.pop_with_metadata(path)
    assert isinstance(snapshot, UndoSnapshot)
    assert snapshot.content == "some content"
    assert snapshot.editor == "file_edit"
    assert before_time <= snapshot.timestamp <= after_time


def test_manager_max_history_limit() -> None:
    manager = UndoHistoryManager()
    path = "large.txt"

    # Push 35 snapshots (exceeding limit of 32)
    for i in range(35):
        manager.push(path, f"content {i}", "file_edit")

    # History length should be capped at 32
    assert manager.get_history_length(path) == 32

    # The oldest 3 snapshots (0, 1, 2) should have been evicted.
    # The oldest remaining snapshot should be "content 3"
    snapshots = []
    while manager.get_history_length(path) > 0:
        snapshots.append(manager.pop(path))

    # The pop sequence yields newest first, so:
    # content 34, content 33, ..., content 3
    assert snapshots[0] == "content 34"
    assert snapshots[-1] == "content 3"


def test_manager_clear() -> None:
    manager = UndoHistoryManager()
    path_a = "a.txt"
    path_b = "b.txt"

    manager.push(path_a, "content a", "file_edit")
    manager.push(path_b, "content b", "symbol_edit")

    # Clear only path_a
    manager.clear(path_a)
    assert manager.has_history(path_a) is False
    assert manager.get_history_length(path_a) == 0

    # path_b should still be intact
    assert manager.has_history(path_b) is True
    assert manager.get_history_length(path_b) == 1
    assert manager.pop(path_b) == "content b"


def test_global_undo_manager_singleton() -> None:
    assert isinstance(global_undo_manager, UndoHistoryManager)
    # Verify we can interact with it
    path = "global.txt"
    global_undo_manager.clear(path)
    assert global_undo_manager.has_history(path) is False
    global_undo_manager.push(path, "global content", "file_edit")
    assert global_undo_manager.has_history(path) is True
    global_undo_manager.clear(path)
