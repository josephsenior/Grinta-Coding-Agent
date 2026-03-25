"""Unit tests for backend.engines.orchestrator.tools.checkpoint."""

from __future__ import annotations

import json
from pathlib import Path

from backend.engines.orchestrator.tools import checkpoint


def _extract_payload(thought: str) -> dict:
    marker = "[CHECKPOINT_RESULT] "
    assert marker in thought
    return json.loads(thought.split(marker, 1)[1])


def test_save_checkpoint_success_and_structured_payload(monkeypatch, tmp_path: Path) -> None:
    cp_file = tmp_path / ".forge" / "checkpoints.json"
    monkeypatch.setattr(checkpoint, "_checkpoints_path", lambda: cp_file)

    action = checkpoint.build_checkpoint_action(
        {"command": "save", "label": "phase 1", "files_modified": "a.txt,b.txt"}
    )

    assert "[CHECKPOINT] Saved #1: phase 1" in action.thought
    payload = _extract_payload(action.thought)
    assert payload["ok"] is True
    assert payload["status"] == "saved"
    assert payload["reason_code"] == "CHECKPOINT_SAVED"
    assert payload["changed_state"] is True
    assert payload["data"]["checkpoint_id"] == 1
    assert payload["data"]["files"] == ["a.txt", "b.txt"]


def test_save_checkpoint_duplicate_is_noop(monkeypatch, tmp_path: Path) -> None:
    cp_file = tmp_path / ".forge" / "checkpoints.json"
    monkeypatch.setattr(checkpoint, "_checkpoints_path", lambda: cp_file)

    first = checkpoint.build_checkpoint_action(
        {"command": "save", "label": "same", "files_modified": "x.py"}
    )
    second = checkpoint.build_checkpoint_action(
        {"command": "save", "label": "same", "files_modified": "x.py"}
    )

    first_payload = _extract_payload(first.thought)
    second_payload = _extract_payload(second.thought)

    assert first_payload["status"] == "saved"
    assert second_payload["ok"] is True
    assert second_payload["status"] == "noop"
    assert second_payload["reason_code"] == "DUPLICATE_CHECKPOINT"
    assert second_payload["changed_state"] is False

    checkpoints = json.loads(cp_file.read_text(encoding="utf-8"))
    assert len(checkpoints) == 1


def test_save_checkpoint_missing_label_returns_failed_payload() -> None:
    action = checkpoint.build_checkpoint_action({"command": "save"})

    payload = _extract_payload(action.thought)
    assert payload["ok"] is False
    assert payload["status"] == "failed"
    assert payload["reason_code"] == "MISSING_LABEL"
    assert payload["retryable"] is True


def test_clear_when_empty_returns_noop(monkeypatch, tmp_path: Path) -> None:
    cp_file = tmp_path / ".forge" / "checkpoints.json"
    monkeypatch.setattr(checkpoint, "_checkpoints_path", lambda: cp_file)

    action = checkpoint.build_checkpoint_action({"command": "clear"})

    payload = _extract_payload(action.thought)
    assert payload["ok"] is True
    assert payload["status"] == "noop"
    assert payload["reason_code"] == "ALREADY_EMPTY"
    assert payload["changed_state"] is False
