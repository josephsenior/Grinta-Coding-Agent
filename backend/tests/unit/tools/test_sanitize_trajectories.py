"""Tests for backend.tools.sanitize_trajectories — trajectory sanitization utilities."""

import json
import tempfile
from pathlib import Path


from backend.tools.sanitize_trajectories import (
    _is_jsonl_file,
    _is_null_event,
    _process_dict_contents,
    _process_files,
    _process_json_file,
    _process_jsonl_content,
    _process_jsonl_file,
    _process_regular_json_data,
    _process_trajectory_data,
    _read_file_content,
    _sanitize_dict,
    _sanitize_list,
    _sanitize_primitive,
    _should_drop_cleaned_value,
    _write_json_file,
    _write_jsonl_file,
    find_candidate_files,
    process_file,
    sanitize_json_content,
)


class TestFindCandidateFiles:
    """Tests for find_candidate_files function."""

    def test_find_json_files(self):
        """Test finding JSON files in directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "test1.json").write_text("{}")
            (tmppath / "test2.json").write_text("{}")
            (tmppath / "test.txt").write_text("not json")

            files = find_candidate_files(tmppath)
            json_files = [f.name for f in files]

            assert len(files) == 2
            assert "test1.json" in json_files
            assert "test2.json" in json_files
            assert "test.txt" not in json_files

    def test_find_jsonl_files(self):
        """Test finding JSON Lines files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "events.jsonl").write_text("{}\n{}")

            files = find_candidate_files(tmppath)
            assert len(files) == 1
            assert files[0].suffix == ".jsonl"

    def test_nonexistent_directory(self):
        """Test handling non-existent directory."""
        files = find_candidate_files(Path("/nonexistent/path"))
        assert files == []

    def test_find_nested_files(self):
        """Test finding files in nested directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            subdir = tmppath / "subdir"
            subdir.mkdir()
            (subdir / "nested.json").write_text("{}")

            files = find_candidate_files(tmppath)
            assert len(files) == 1
            assert files[0].name == "nested.json"


class TestSanitizeJsonContent:
    """Tests for sanitize_json_content function."""

    def test_sanitize_dict_with_null_observation(self):
        """Test sanitizing dict with null observation."""
        obj = {"observation": "null", "other": "data"}
        result = sanitize_json_content(obj)
        assert result is None  # Null event should be dropped

    def test_sanitize_dict_with_null_action(self):
        """Test sanitizing dict with null action."""
        obj = {"action": "null", "other": "data"}
        result = sanitize_json_content(obj)
        assert result is None  # Null event should be dropped

    def test_sanitize_dict_without_nulls(self):
        """Test sanitizing dict without null values."""
        obj = {"observation": "valid", "action": "valid"}
        result = sanitize_json_content(obj)
        assert result == obj

    def test_sanitize_list_with_null_events(self):
        """Test sanitizing list containing null events."""
        obj = [
            {"observation": "null"},
            {"observation": "valid"},
            {"action": "null"},
        ]
        result = sanitize_json_content(obj)
        assert result == [{"observation": "valid"}]

    def test_sanitize_nested_structure(self):
        """Test sanitizing nested data structure."""
        obj = {
            "events": [
                {"observation": "null"},
                {"observation": "valid"},
            ],
        }
        result = sanitize_json_content(obj)
        assert result == {"events": [{"observation": "valid"}]}

    def test_sanitize_primitive_null_string(self):
        """Test sanitizing primitive 'null' string."""
        result = sanitize_json_content("null")
        assert result is None

    def test_sanitize_primitive_valid_string(self):
        """Test sanitizing valid primitive."""
        result = sanitize_json_content("hello")
        assert result == "hello"

    def test_sanitize_empty_dict(self):
        """Test sanitizing empty dict."""
        result = sanitize_json_content({})
        assert result == {}

    def test_sanitize_empty_list(self):
        """Test sanitizing empty list."""
        result = sanitize_json_content([])
        assert result == []


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_is_null_event_with_observation(self):
        """Test _is_null_event recognizes null observation."""
        assert _is_null_event({"observation": "null"}) is True

    def test_is_null_event_with_action(self):
        """Test _is_null_event recognizes null action."""
        assert _is_null_event({"action": "null"}) is True

    def test_is_null_event_with_valid_data(self):
        """Test _is_null_event returns False for valid data."""
        assert _is_null_event({"observation": "valid"}) is False
        assert _is_null_event({"action": "valid"}) is False
        assert _is_null_event({}) is False

    def test_should_drop_cleaned_value_for_null_dict(self):
        """Test _should_drop_cleaned_value drops null dicts."""
        assert _should_drop_cleaned_value(None, {}, "key") is True

    def test_should_drop_cleaned_value_for_null_list(self):
        """Test _should_drop_cleaned_value drops null lists."""
        assert _should_drop_cleaned_value(None, [], "key") is True

    def test_should_drop_cleaned_value_for_observation_key(self):
        """Test _should_drop_cleaned_value drops observation key."""
        assert _should_drop_cleaned_value(None, "val", "observation") is True

    def test_should_drop_cleaned_value_for_action_key(self):
        """Test _should_drop_cleaned_value drops action key."""
        assert _should_drop_cleaned_value(None, "val", "action") is True

    def test_should_drop_cleaned_value_non_null(self):
        """Test _should_drop_cleaned_value keeps non-null values."""
        assert _should_drop_cleaned_value("value", "orig", "key") is False


class TestSanitizePrimitive:
    """Tests for _sanitize_primitive function."""

    def test_sanitize_null_string(self):
        """Test sanitizing 'null' string."""
        assert _sanitize_primitive("null") is None

    def test_sanitize_valid_string(self):
        """Test sanitizing valid string."""
        assert _sanitize_primitive("hello") == "hello"

    def test_sanitize_number(self):
        """Test sanitizing number."""
        assert _sanitize_primitive(42) == 42

    def test_sanitize_boolean(self):
        """Test sanitizing boolean."""
        assert _sanitize_primitive(True) is True


class TestSanitizeList:
    """Tests for _sanitize_list function."""

    def test_sanitize_empty_list(self):
        """Test sanitizing empty list."""
        result = _sanitize_list([])
        assert result == []

    def test_sanitize_list_with_nulls(self):
        """Test sanitizing list with null items."""
        result = _sanitize_list(["null", "valid", "null"])
        assert result == ["valid"]

    def test_sanitize_list_unmodified(self):
        """Test sanitizing list that doesn't need changes."""
        original = ["a", "b", "c"]
        result = _sanitize_list(original)
        assert result is original  # Should return same object if unchanged

    def test_sanitize_list_with_nested_dicts(self):
        """Test sanitizing list with nested dicts."""
        result = _sanitize_list([{"observation": "null"}, {"observation": "valid"}])
        assert len(result) == 1
        assert result[0]["observation"] == "valid"


class TestSanitizeDict:
    """Tests for _sanitize_dict function."""

    def test_sanitize_null_event_dict(self):
        """Test sanitizing null event dict."""
        result = _sanitize_dict({"observation": "null"})
        assert result is None

    def test_sanitize_valid_dict(self):
        """Test sanitizing valid dict."""
        original = {"key": "value"}
        result = _sanitize_dict(original)
        assert result == original

    def test_sanitize_dict_removes_null_nested(self):
        """Test sanitizing dict removes null nested values."""
        obj = {"valid": "data", "nested": {"observation": "null"}}
        result = _sanitize_dict(obj)
        # Nested null event should be removed
        assert (
            "nested" not in result or result["nested"] is None or result["nested"] == {}
        )


class TestProcessDictContents:
    """Tests for _process_dict_contents function."""

    def test_process_dict_unchanged(self):
        """Test processing dict that doesn't change."""
        original = {"key": "value"}
        result = _process_dict_contents(original)
        assert result is original  # Should return same object

    def test_process_dict_with_null_values(self):
        """Test processing dict with null values."""
        obj = {"keep": "this", "nested": {"observation": "null"}}
        result = _process_dict_contents(obj)
        assert "keep" in result
        # Nested dict with null observation should be removed or empty
        assert "nested" not in result or result["nested"] == {}


class TestReadFileContent:
    """Tests for _read_file_content function."""

    def test_read_valid_file(self):
        """Test reading valid file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            f.write('{"test": "data"}')
            temp_path = f.name

        try:
            content = _read_file_content(temp_path)
            assert content == '{"test": "data"}'
        finally:
            Path(temp_path).unlink()

    def test_read_nonexistent_file(self):
        """Test reading non-existent file."""
        content = _read_file_content("/nonexistent/file.json")
        assert content is None


class TestIsJsonlFile:
    """Tests for _is_jsonl_file function."""

    def test_jsonl_file(self):
        """Test recognizing .jsonl file."""
        assert _is_jsonl_file("events.jsonl") is True
        assert _is_jsonl_file("data.JSONL") is True

    def test_json_file(self):
        """Test .json file is not jsonl."""
        assert _is_jsonl_file("data.json") is False

    def test_other_file(self):
        """Test other file extensions."""
        assert _is_jsonl_file("data.txt") is False


class TestProcessJsonlContent:
    """Tests for _process_jsonl_content function."""

    def test_process_valid_jsonl(self):
        """Test processing valid JSONL content."""
        raw = '{"a": 1}\n{"b": 2}\n'
        parsed, sanitized, changed = _process_jsonl_content(raw)
        assert len(parsed) == 2
        assert len(sanitized) == 2
        assert changed is False

    def test_process_jsonl_with_null_events(self):
        """Test processing JSONL with null events."""
        raw = '{"observation": "null"}\n{"observation": "valid"}\n'
        _parsed, sanitized, changed = _process_jsonl_content(raw)
        assert len(sanitized) == 1
        assert sanitized[0]["observation"] == "valid"
        assert changed is True

    def test_process_jsonl_empty_lines(self):
        """Test processing JSONL with empty lines."""
        raw = '{"a": 1}\n\n{"b": 2}\n'
        parsed, _sanitized, _changed = _process_jsonl_content(raw)
        assert len(parsed) == 2


class TestWriteJsonlFile:
    """Tests for _write_jsonl_file function."""

    def test_write_jsonl(self):
        """Test writing JSONL file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".jsonl") as f:
            temp_path = f.name

        try:
            data = [{"a": 1}, {"b": 2}]
            _write_jsonl_file(temp_path, data)

            with open(temp_path, encoding="utf-8") as f:
                lines = f.readlines()

            assert len(lines) == 2
            assert json.loads(lines[0]) == {"a": 1}
            assert json.loads(lines[1]) == {"b": 2}
        finally:
            Path(temp_path).unlink()


class TestProcessTrajectoryData:
    """Tests for _process_trajectory_data function."""

    def test_process_valid_trajectory(self):
        """Test processing valid trajectory data."""
        data = {"trajectory": [{"step": 1}, {"step": 2}]}
        result, changed = _process_trajectory_data(data)
        assert result["trajectory"] == [{"step": 1}, {"step": 2}]
        assert changed is False

    def test_process_trajectory_with_null_events(self):
        """Test processing trajectory with null events."""
        data = {"trajectory": [{"observation": "null"}, {"observation": "valid"}]}
        result, changed = _process_trajectory_data(data)
        assert len(result["trajectory"]) == 1
        assert changed is True


class TestWriteJsonFile:
    """Tests for _write_json_file function."""

    def test_write_json_dict(self):
        """Test writing JSON dict to file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            temp_path = f.name

        try:
            data = {"key": "value"}
            _write_json_file(temp_path, data)

            with open(temp_path, encoding="utf-8") as f:
                loaded = json.load(f)

            assert loaded == data
        finally:
            Path(temp_path).unlink()

    def test_write_json_none(self):
        """Test writing None to JSON file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            temp_path = f.name

        try:
            _write_json_file(temp_path, None)

            with open(temp_path, encoding="utf-8") as f:
                loaded = json.load(f)

            assert loaded == {}
        finally:
            Path(temp_path).unlink()


class TestProcessRegularJsonData:
    """Tests for _process_regular_json_data function."""

    def test_process_unchanged_data(self):
        """Test processing data that doesn't change."""
        data = {"key": "value"}
        result, changed = _process_regular_json_data(data)
        assert result == data
        assert changed is False

    def test_process_data_with_null_events(self):
        """Test processing data with null events."""
        data = {"observation": "null"}
        result, changed = _process_regular_json_data(data)
        assert result is None
        assert changed is True


class TestProcessJsonlFile:
    """Tests for _process_jsonl_file function."""

    def test_process_jsonl_no_apply(self):
        """Test processing JSONL file without applying changes."""
        raw = '{"observation": "null"}\n{"observation": "valid"}\n'
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".jsonl") as f:
            temp_path = f.name

        try:
            changed = _process_jsonl_file(raw, temp_path, apply=False)
            assert changed is True

            # File should not be modified
            content = Path(temp_path).read_text()
            assert content == ""  # File was created empty
        finally:
            Path(temp_path).unlink()


class TestProcessJsonFile:
    """Tests for _process_json_file function."""

    def test_process_trajectory_json(self):
        """Test processing JSON with trajectory."""
        raw = '{"trajectory": [{"observation": "null"}, {"observation": "valid"}]}'
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            temp_path = f.name

        try:
            changed = _process_json_file(raw, temp_path, apply=False)
            assert changed is True
        finally:
            Path(temp_path).unlink()

    def test_process_regular_json(self):
        """Test processing regular JSON."""
        raw = '{"key": "value"}'
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            temp_path = f.name

        try:
            changed = _process_json_file(raw, temp_path, apply=False)
            assert changed is False
        finally:
            Path(temp_path).unlink()


class TestProcessFile:
    """Tests for process_file function."""

    def test_process_valid_json_file(self):
        """Test processing valid JSON file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            json.dump({"key": "value"}, f)
            temp_path = f.name

        try:
            changed = process_file(temp_path, apply=False)
            assert changed is False
        finally:
            Path(temp_path).unlink()

    def test_process_json_file_with_nulls(self):
        """Test processing JSON file with null events."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            json.dump({"observation": "null"}, f)
            temp_path = f.name

        try:
            changed = process_file(temp_path, apply=False)
            assert changed is True
        finally:
            Path(temp_path).unlink()

    def test_process_invalid_json_file(self):
        """Test processing invalid JSON file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            f.write("invalid json{")
            temp_path = f.name

        try:
            changed = process_file(temp_path, apply=False)
            assert changed is False  # Should return False on error
        finally:
            Path(temp_path).unlink()


class TestProcessFiles:
    """Tests for _process_files function."""

    def test_process_multiple_files(self):
        """Test processing multiple files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create files
            file1 = tmppath / "file1.json"
            file2 = tmppath / "file2.json"
            file1.write_text('{"observation": "null"}')
            file2.write_text('{"key": "value"}')

            files = [file1, file2]
            changed = _process_files(files, apply=False)

            assert len(changed) == 1  # Only file1 should change
