"""Unit tests for backend.engine.tools.error_recovery_memory."""

from __future__ import annotations

from types import SimpleNamespace
import json

from backend.engine.tools import error_recovery_memory


def test_query_requires_error_signature(monkeypatch) -> None:
    def _manager() -> SimpleNamespace:
        return SimpleNamespace()

    monkeypatch.setattr(error_recovery_memory, "_kb_manager", _manager)
    monkeypatch.setattr(
        error_recovery_memory, "_ensure_collection", lambda _m: "col-1"
    )
    monkeypatch.setattr(
        error_recovery_memory, "_run_one_time_migration", lambda *_: (0, 0)
    )

    result = error_recovery_memory.build_error_recovery_memory_action(
        {"command": "query"}
    )

    assert "query requires 'error_signature'" in result.thought


def test_record_success(monkeypatch) -> None:
    manager = SimpleNamespace(add_document=lambda **_: object())
    monkeypatch.setattr(error_recovery_memory, "_kb_manager", lambda: manager)
    monkeypatch.setattr(
        error_recovery_memory, "_ensure_collection", lambda _m: "col-1"
    )
    monkeypatch.setattr(
        error_recovery_memory, "_run_one_time_migration", lambda *_: (0, 0)
    )

    result = error_recovery_memory.build_error_recovery_memory_action(
        {
            "command": "record",
            "error_signature": "ModuleNotFoundError",
            "solution": "Install dependency",
        }
    )

    assert "Recorded recovery" in result.thought


def test_query_returns_ranked_results(monkeypatch) -> None:
    mock_result = SimpleNamespace(relevance_score=0.91, chunk_content="fix this first")
    manager = SimpleNamespace(search=lambda **_: [mock_result])
    monkeypatch.setattr(error_recovery_memory, "_kb_manager", lambda: manager)
    monkeypatch.setattr(
        error_recovery_memory, "_ensure_collection", lambda _m: "col-1"
    )
    monkeypatch.setattr(
        error_recovery_memory, "_run_one_time_migration", lambda *_: (0, 0)
    )

    result = error_recovery_memory.build_error_recovery_memory_action(
        {
            "command": "query",
            "error_signature": "timeout after 30",
            "top_k": 3,
        }
    )

    assert "Ranked recoveries" in result.thought
    assert "fix this first" in result.thought


def test_list_returns_entries(monkeypatch) -> None:
    docs = [
        SimpleNamespace(filename="doc1.json", chunk_count=1),
        SimpleNamespace(filename="doc2.json", chunk_count=2),
    ]
    manager = SimpleNamespace(list_documents=lambda *_: docs)
    monkeypatch.setattr(error_recovery_memory, "_kb_manager", lambda: manager)
    monkeypatch.setattr(
        error_recovery_memory, "_ensure_collection", lambda _m: "col-1"
    )
    monkeypatch.setattr(
        error_recovery_memory, "_run_one_time_migration", lambda *_: (0, 0)
    )

    result = error_recovery_memory.build_error_recovery_memory_action(
        {"command": "list"}
    )

    assert "Stored entries" in result.thought
    assert "doc1.json" in result.thought


def test_build_doc_name_is_deterministic() -> None:
    a = error_recovery_memory._build_doc_name("same error", "same fix")
    b = error_recovery_memory._build_doc_name("same error", "same fix")
    c = error_recovery_memory._build_doc_name("same error", "different fix")

    assert a == b
    assert a != c
    assert a.endswith(".json")


def test_migration_imports_once_and_dedupes(monkeypatch, tmp_path) -> None:
    local_file = tmp_path / ".forge" / "query_error_solutions.json"
    global_file = tmp_path / ".forge" / "global_query_error_solutions.json"
    marker_file = tmp_path / ".forge" / "error_recovery_migration_done.json"

    local_file.parent.mkdir(parents=True, exist_ok=True)
    local_file.write_text(
        json.dumps(
            [
                {"trigger": "ErrorA", "solution": "FixA"},
                {"trigger": "ErrorDup", "solution": "LocalFix"},
                {"trigger": "", "solution": "missing trigger"},
            ]
        ),
        encoding="utf-8",
    )
    global_file.write_text(
        json.dumps(
            [
                {"trigger": "ErrorDup", "solution": "GlobalFix"},
                {"trigger": "ErrorB", "solution": "FixB"},
                {"trigger": "ErrorC", "solution": ""},
            ]
        ),
        encoding="utf-8",
    )

    imported: list[tuple[str, str, str]] = []

    def _fake_record(_manager, _collection_id, error_signature, solution, source):
        imported.append((error_signature, solution, source))
        return True

    monkeypatch.setattr(error_recovery_memory, "_legacy_local_path", lambda: local_file)
    monkeypatch.setattr(error_recovery_memory, "_LEGACY_GLOBAL_FILE", global_file)
    monkeypatch.setattr(error_recovery_memory, "_migration_marker_path", lambda: marker_file)
    monkeypatch.setattr(error_recovery_memory, "_record", _fake_record)

    first = error_recovery_memory._run_one_time_migration(
        manager=SimpleNamespace(),
        collection_id="col-1",
    )
    second = error_recovery_memory._run_one_time_migration(
        manager=SimpleNamespace(),
        collection_id="col-1",
    )

    assert first == (3, 1)
    assert second == (0, 0)
    assert [x[0] for x in imported] == ["ErrorA", "ErrorDup", "ErrorB"]
    assert marker_file.exists()
