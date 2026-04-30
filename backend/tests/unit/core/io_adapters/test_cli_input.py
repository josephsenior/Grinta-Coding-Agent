"""Tests for backend.core.io_adapters.cli_input."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import backend.core.io_adapters.cli_input as cli_input


def test_read_task_from_file_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / 'task.txt'
    p.write_text('hello task\n', encoding='utf-8')
    assert cli_input.read_task_from_file(str(p)) == 'hello task\n'


def test_read_task_prefers_file_over_task_string(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / 'f.txt'
    f.write_text('from-file', encoding='utf-8')
    args = argparse.Namespace(file=str(f), task='from-arg')
    assert cli_input.read_task(args, cli_multiline_input=False) == 'from-file'


def test_read_task_uses_task_field_when_no_file() -> None:
    args = argparse.Namespace(file=None, task='inline')
    assert cli_input.read_task(args, cli_multiline_input=False) == 'inline'


def test_read_task_stdin_non_tty_uses_read_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = argparse.Namespace(file=None, task=None)
    stdin = MagicMock()
    stdin.isatty.return_value = False
    monkeypatch.setattr(sys, 'stdin', stdin)
    monkeypatch.setattr(cli_input, 'read_input', lambda multiline=False: 'piped')
    assert cli_input.read_task(args, False) == 'piped'
