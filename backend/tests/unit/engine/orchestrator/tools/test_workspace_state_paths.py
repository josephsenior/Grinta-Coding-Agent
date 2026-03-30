"""Focused tests for .app-backed workspace state paths."""

from __future__ import annotations

import json

from backend.context.compactor.strategies.smart_compactor import SmartCompactor
from backend.engine.tools.task_tracker import TaskTracker
from backend.engine.tools import working_memory as wm


def test_working_memory_writes_under_app_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.core.workspace_resolution.get_effective_workspace_root",
        lambda: tmp_path,
    )

    action = wm.build_working_memory_action(
        {"command": "update", "section": "plan", "content": "next step"}
    )

    assert "Updated 'plan'" in action.thought
    memory_file = tmp_path / ".app" / "working_memory.json"
    assert memory_file.exists()
    assert json.loads(memory_file.read_text(encoding="utf-8"))["plan"] == "next step"


def test_task_tracker_persists_active_plan_under_app_dir(tmp_path) -> None:
    tracker = TaskTracker(tmp_path)
    task_list = [{"id": "1", "description": "Do it", "status": "in_progress"}]

    tracker.save_to_file(task_list)

    assert tracker.path == tmp_path / ".app" / "active_plan.json"
    assert tracker.load_from_file() == task_list


def test_smart_compactor_reads_in_progress_ids_from_app_plan(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APP_WORKSPACE_DIR", str(tmp_path))
    plan_file = tmp_path / ".app" / "active_plan.json"
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.write_text(
        json.dumps(
            {
                "tasks": [
                    {"id": "1", "description": "one", "status": "done"},
                    {"id": "2", "description": "two", "status": "in_progress"},
                ]
            }
        ),
        encoding="utf-8",
    )

    compactor = SmartCompactor(llm=None)

    assert compactor._load_in_progress_task_ids() == {"2"}