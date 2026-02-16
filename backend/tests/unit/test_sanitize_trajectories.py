"""Tests for backend.tools.sanitize_trajectories — JSON sanitization pure logic."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.tools.sanitize_trajectories import (
    _is_null_event,
    _parse_arguments,
    _process_trajectory_data,
    _sanitize_dict,
    _sanitize_list,
    _sanitize_primitive,
    find_candidate_files,
    process_file,
    sanitize_json_content,
)


# ── _is_null_event ───────────────────────────────────────────────────


class TestIsNullEvent:
    def test_null_observation(self):
        assert _is_null_event({"observation": "null"}) is True

    def test_null_action(self):
        assert _is_null_event({"action": "null"}) is True

    def test_normal_event(self):
        assert _is_null_event({"action": "run", "command": "ls"}) is False

    def test_empty(self):
        assert _is_null_event({}) is False


# ── _sanitize_primitive ──────────────────────────────────────────────


class TestSanitizePrimitive:
    def test_null_string(self):
        assert _sanitize_primitive("null") is None

    def test_normal_string(self):
        assert _sanitize_primitive("hello") == "hello"

    def test_number(self):
        assert _sanitize_primitive(42) == 42

    def test_bool(self):
        assert _sanitize_primitive(True) is True


# ── _sanitize_list ───────────────────────────────────────────────────


class TestSanitizeList:
    def test_removes_null_events(self):
        items = [{"action": "null"}, {"action": "run"}]
        result = _sanitize_list(items)
        assert len(result) == 1
        assert result[0]["action"] == "run"

    def test_empty_list(self):
        assert _sanitize_list([]) == []

    def test_no_changes(self):
        items = [{"key": "val"}, {"other": 1}]
        result = _sanitize_list(items)
        assert result is items  # identity — no changes made

    def test_nested_null_removed(self):
        items = [{"observation": "null"}]
        result = _sanitize_list(items)
        assert result == []


# ── _sanitize_dict ───────────────────────────────────────────────────


class TestSanitizeDict:
    def test_null_event_returns_none(self):
        assert _sanitize_dict({"observation": "null"}) is None

    def test_normal_dict_unchanged(self):
        d = {"key": "value", "num": 42}
        result = _sanitize_dict(d)
        assert result is d  # identity — no changes

    def test_nested_null_cleaned(self):
        d = {"events": [{"action": "null"}, {"action": "run"}]}
        result = _sanitize_dict(d)
        assert len(result["events"]) == 1


# ── sanitize_json_content (top-level) ────────────────────────────────


class TestSanitizeJsonContent:
    def test_dict_pass_through(self):
        obj = {"key": "val"}
        assert sanitize_json_content(obj) is obj

    def test_list(self):
        result = sanitize_json_content([1, 2, 3])
        assert result == [1, 2, 3]

    def test_string(self):
        assert sanitize_json_content("hello") == "hello"

    def test_null_string(self):
        assert sanitize_json_content("null") is None

    def test_null_event_dict(self):
        assert sanitize_json_content({"action": "null"}) is None


# ── _process_trajectory_data ─────────────────────────────────────────


class TestProcessTrajectoryData:
    def test_clean_trajectory(self):
        data = {"trajectory": [{"action": "run"}, {"action": "null"}]}
        result, changed = _process_trajectory_data(data)
        assert changed is True
        assert len(result["trajectory"]) == 1

    def test_already_clean(self):
        data = {"trajectory": [{"action": "run"}]}
        result, changed = _process_trajectory_data(data)
        assert changed is False

    def test_empty_trajectory(self):
        data = {"trajectory": []}
        result, changed = _process_trajectory_data(data)
        assert changed is False


# ── find_candidate_files ─────────────────────────────────────────────


class TestFindCandidateFiles:
    def test_nonexistent_root(self, tmp_path):
        assert find_candidate_files(tmp_path / "nope") == []

    def test_finds_json(self, tmp_path):
        (tmp_path / "a.json").write_text("{}")
        (tmp_path / "b.jsonl").write_text("{}")
        (tmp_path / "c.txt").write_text("hi")
        files = find_candidate_files(tmp_path)
        names = {f.name for f in files}
        assert "a.json" in names
        assert "b.jsonl" in names
        assert "c.txt" not in names

    def test_recursive(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.json").write_text("{}")
        files = find_candidate_files(tmp_path)
        assert any(f.name == "deep.json" for f in files)


# ── process_file ─────────────────────────────────────────────────────


class TestProcessFile:
    def test_clean_file_no_change(self, tmp_path):
        f = tmp_path / "clean.json"
        f.write_text(json.dumps({"key": "value"}), encoding="utf-8")
        assert process_file(f) is False

    def test_dirty_file_dry_run(self, tmp_path):
        f = tmp_path / "dirty.json"
        data = {"action": "null", "other": "keep"}
        f.write_text(json.dumps(data), encoding="utf-8")
        changed = process_file(f, apply=False)
        assert changed is True
        # File unchanged in dry-run
        assert json.loads(f.read_text()) == data

    def test_dirty_file_apply(self, tmp_path):
        f = tmp_path / "dirty.json"
        f.write_text(json.dumps({"action": "null"}), encoding="utf-8")
        changed = process_file(f, apply=True)
        assert changed is True
        result = json.loads(f.read_text(encoding="utf-8"))
        assert "action" not in result or result.get("action") != "null"

    def test_invalid_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json at all", encoding="utf-8")
        assert process_file(f) is False

    def test_trajectory_cleaned(self, tmp_path):
        f = tmp_path / "traj.json"
        data = {"trajectory": [{"action": "null"}, {"action": "run"}]}
        f.write_text(json.dumps(data), encoding="utf-8")
        changed = process_file(f, apply=True)
        assert changed is True
        result = json.loads(f.read_text(encoding="utf-8"))
        assert len(result["trajectory"]) == 1

    def test_jsonl_file(self, tmp_path):
        f = tmp_path / "events.jsonl"
        lines = [
            json.dumps({"action": "null"}),
            json.dumps({"action": "run", "cmd": "ls"}),
        ]
        f.write_text("\n".join(lines), encoding="utf-8")
        changed = process_file(f, apply=True)
        assert changed is True
        content = f.read_text(encoding="utf-8").strip().split("\n")
        assert len(content) == 1
        assert json.loads(content[0])["action"] == "run"


# ── _parse_arguments ─────────────────────────────────────────────────


class TestParseArguments:
    def test_defaults(self):
        args = _parse_arguments([])
        assert args.paths == ["tests/runtime/trajs"]
        assert args.apply is False

    def test_custom_paths(self):
        args = _parse_arguments(["--paths", "a", "b"])
        assert args.paths == ["a", "b"]

    def test_apply_flag(self):
        args = _parse_arguments(["--apply"])
        assert args.apply is True

    def test_dry_run_flag(self):
        args = _parse_arguments(["--dry-run"])
        assert args.dry_run is True
