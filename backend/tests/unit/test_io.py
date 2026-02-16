"""Unit tests for backend.core.io — JSON stdout helpers."""

from __future__ import annotations

import json

import pytest

from backend.core.io import format_json, print_json_stdout


class TestFormatJson:
    def test_compact(self):
        result = format_json({"a": 1})
        assert result == '{"a":1}'

    def test_pretty(self):
        result = format_json({"a": 1}, pretty=True)
        assert '"a": 1' in result
        assert "\n" in result

    def test_non_serializable_fallback(self):
        """Objects that can't be serialized use `default=str`."""
        result = format_json({"x": object()})
        assert isinstance(result, str)

    def test_ensure_ascii(self):
        result = format_json({"emoji": "😀"}, ensure_ascii=True)
        assert "\\u" in result

    def test_no_ensure_ascii(self):
        result = format_json({"emoji": "😀"}, ensure_ascii=False)
        assert "😀" in result


class TestPrintJsonStdout:
    def test_writes_to_stdout(self, capsys):
        print_json_stdout({"key": "value"})
        out = capsys.readouterr().out
        parsed = json.loads(out.strip())
        assert parsed == {"key": "value"}

    def test_pretty_output(self, capsys):
        print_json_stdout({"key": "value"}, pretty=True)
        out = capsys.readouterr().out
        assert "\n" in out
        parsed = json.loads(out.strip())
        assert parsed["key"] == "value"
