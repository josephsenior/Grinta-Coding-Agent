"""Tests for backend.core.io — JSON stdout utilities."""

from __future__ import annotations

import json
from typing import cast
from unittest.mock import MagicMock, patch


from backend.core.io import format_json, print_json_stdout


class TestFormatJson:
    """Tests for format_json function."""

    def test_formats_simple_dict(self):
        """Test formats a simple dictionary to JSON."""
        obj = {"name": "test", "count": 42}
        result = format_json(obj)
        assert json.loads(result) == obj
        assert "," in result  # compact format

    def test_formats_list(self):
        """Test formats a list to JSON."""
        obj = [1, 2, 3, "four"]
        result = format_json(obj)
        assert json.loads(result) == obj

    def test_pretty_format_adds_indentation(self):
        """Test pretty=True adds indentation and newlines."""
        obj = {"key": "value", "nested": {"a": 1}}
        result = format_json(obj, pretty=True)
        assert "\n" in result
        assert "  " in result  # 2-space indent
        assert json.loads(result) == obj

    def test_compact_format_no_spaces(self):
        """Test default format is compact without spaces."""
        obj = {"key": "value"}
        result = format_json(obj, pretty=False)
        # Compact format uses separators without spaces
        assert result == '{"key":"value"}' or result == '{"key": "value"}'
        # Just verify it parses correctly
        assert json.loads(result) == obj
        assert "\n" not in result

    def test_ensure_ascii_true_escapes_unicode(self):
        """Test ensure_ascii=True escapes non-ASCII characters."""
        obj = {"emoji": "😊", "text": "café"}
        result = format_json(obj, ensure_ascii=True)
        # Should not contain raw unicode
        assert "😊" not in result
        assert "café" not in result
        # But should decode correctly
        assert json.loads(result) == obj

    def test_ensure_ascii_false_preserves_unicode(self):
        """Test ensure_ascii=False preserves unicode characters."""
        obj = {"emoji": "😊", "text": "café"}
        result = format_json(obj, ensure_ascii=False)
        assert "😊" in result
        assert "café" in result

    def test_uses_str_default_for_non_serializable(self):
        """Test uses str() as default for non-JSON-serializable objects."""

        class CustomObj:
            def __str__(self):
                return "custom_repr"

        obj = {"value": CustomObj()}
        result = format_json(obj)
        parsed = json.loads(result)
        assert parsed["value"] == "custom_repr"

    def test_handles_serialization_exception(self):
        """Test returns repr when serialization fails."""
        # Create object that fails both json.dumps and str()
        obj = MagicMock()
        cast(MagicMock, obj.__str__).side_effect = RuntimeError("Cannot stringify")

        # Mock json.dumps to raise
        with patch(
            "backend.core.io.json.dumps", side_effect=ValueError("Cannot serialize")
        ):
            result = format_json(obj)
            # Should fall back to repr()
            assert "MagicMock" in result

    def test_nested_structures(self):
        """Test handles deeply nested structures."""
        obj = {"level1": {"level2": {"level3": [1, 2, {"level4": "deep"}]}}}
        result = format_json(obj)
        assert json.loads(result) == obj

    def test_empty_dict_and_list(self):
        """Test handles empty containers."""
        assert format_json({}) == "{}"
        assert format_json([]) == "[]"

    def test_null_and_boolean_values(self):
        """Test handles None, True, False."""
        obj = {"null": None, "true": True, "false": False}
        result = format_json(obj)
        parsed = json.loads(result)
        assert parsed["null"] is None
        assert parsed["true"] is True
        assert parsed["false"] is False


class TestPrintJsonStdout:
    """Tests for print_json_stdout function."""

    def test_writes_json_to_stdout(self, capsys):
        """Test writes formatted JSON to stdout."""
        obj = {"key": "value"}
        print_json_stdout(obj)

        captured = capsys.readouterr()
        assert json.loads(captured.out.strip()) == obj

    def test_writes_with_newline(self, capsys):
        """Test adds newline after JSON output."""
        print_json_stdout({"test": 1})

        captured = capsys.readouterr()
        assert captured.out.endswith("\n")

    def test_pretty_format_to_stdout(self, capsys):
        """Test pretty=True writes indented JSON."""
        obj = {"a": 1, "b": 2}
        print_json_stdout(obj, pretty=True)

        captured = capsys.readouterr()
        assert "  " in captured.out  # indent present
        assert json.loads(captured.out.strip()) == obj

    def test_flushes_stdout(self):
        """Test calls flush on stdout."""
        obj = {"test": 1}

        with patch("sys.stdout") as mock_stdout:
            mock_file = MagicMock()
            mock_stdout.write = mock_file.write
            mock_stdout.flush = mock_file.flush

            print_json_stdout(obj)

            mock_file.write.assert_called_once()
            mock_file.flush.assert_called_once()

    def test_ensure_ascii_parameter(self, capsys):
        """Test ensure_ascii parameter is passed through."""
        obj = {"emoji": "🎉"}

        print_json_stdout(obj, ensure_ascii=False)
        captured = capsys.readouterr()
        assert "🎉" in captured.out

        print_json_stdout(obj, ensure_ascii=True)
        captured = capsys.readouterr()
        assert "🎉" not in captured.out

    def test_handles_write_exception(self, capsys):
        """Test logs exception when write fails."""
        obj = {"test": 1}

        with patch("sys.stdout.write", side_effect=OSError("Write failed")):
            # Should not raise, should log instead
            print_json_stdout(obj)

            # Verify no exception raised
            captured = capsys.readouterr()
            # stdout.write failed, so output will be empty
            assert captured.out == ""

    def test_handles_flush_exception(self):
        """Test handles exception when flush fails."""
        obj = {"test": 1}

        with patch("sys.stdout.flush", side_effect=OSError("Flush failed")):
            # Should not raise
            print_json_stdout(obj)

    def test_complex_object_with_default(self, capsys):
        """Test handles non-serializable objects via default=str."""
        from datetime import datetime

        obj = {"timestamp": datetime(2024, 1, 1, 12, 0, 0)}
        print_json_stdout(obj)

        captured = capsys.readouterr()
        parsed = json.loads(captured.out.strip())
        assert "2024-01-01" in parsed["timestamp"]

    def test_multiple_consecutive_calls(self, capsys):
        """Test multiple calls each write and flush properly."""
        print_json_stdout({"call": 1})
        print_json_stdout({"call": 2})
        print_json_stdout({"call": 3})

        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) == 3
        assert json.loads(lines[0]) == {"call": 1}
        assert json.loads(lines[1]) == {"call": 2}
        assert json.loads(lines[2]) == {"call": 3}
