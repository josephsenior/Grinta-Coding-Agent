"""Tests for CLI logging / dotenv bootstrap in ``backend.cli.main``."""

from __future__ import annotations

import logging
import os
import sys
from unittest.mock import patch

import pytest


def test_log_to_file_effective_explicit_true() -> None:
    from backend.cli import main as cli_main

    with patch.dict(os.environ, {'LOG_TO_FILE': 'true', 'LOG_LEVEL': 'INFO'}, clear=False):
        assert cli_main._log_to_file_effective() is True


def test_log_to_file_effective_explicit_false() -> None:
    from backend.cli import main as cli_main

    with patch.dict(
        os.environ,
        {'LOG_TO_FILE': 'false', 'LOG_LEVEL': 'DEBUG'},
        clear=False,
    ):
        assert cli_main._log_to_file_effective() is False


def test_log_to_file_effective_defaults_when_unset() -> None:
    from backend.cli import main as cli_main

    with patch.dict(os.environ, {'LOG_LEVEL': 'INFO'}, clear=False):
        os.environ.pop('LOG_TO_FILE', None)
        assert cli_main._log_to_file_effective() is True

    with patch.dict(os.environ, {'LOG_LEVEL': 'DEBUG'}, clear=False):
        os.environ.pop('LOG_TO_FILE', None)
        assert cli_main._log_to_file_effective() is True


def test_app_logger_level_after_silence_respects_log_level_when_file() -> None:
    from backend.cli import main as cli_main

    with patch.dict(
        os.environ,
        {'LOG_TO_FILE': 'true', 'LOG_LEVEL': 'DEBUG'},
        clear=False,
    ):
        assert cli_main._app_logger_level_after_silence() == logging.DEBUG


def test_app_logger_level_after_silence_error_when_no_file() -> None:
    from backend.cli import main as cli_main

    with patch.dict(
        os.environ,
        {'LOG_TO_FILE': 'false', 'LOG_LEVEL': 'DEBUG'},
        clear=False,
    ):
        assert cli_main._app_logger_level_after_silence() == logging.ERROR


def test_app_logger_level_after_silence_respects_log_level_when_file_default() -> None:
    """Unset LOG_TO_FILE defaults to file logging on; console app level follows LOG_LEVEL."""
    from backend.cli import main as cli_main

    with patch.dict(os.environ, {'LOG_LEVEL': 'INFO'}, clear=False):
        os.environ.pop('LOG_TO_FILE', None)
        assert cli_main._app_logger_level_after_silence() == logging.INFO


def test_parse_project_dir_from_argv_short_form(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from backend.cli import main as cli_main

    proj = tmp_path / 'myproj'
    proj.mkdir()
    monkeypatch.setattr(sys, 'argv', ['grinta', '-p', str(proj)])
    got = cli_main._parse_project_dir_from_argv()
    assert got == proj.resolve()


def test_parse_project_dir_from_argv_long_form(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from backend.cli import main as cli_main

    proj = tmp_path / 'other'
    proj.mkdir()
    monkeypatch.setattr(sys, 'argv', ['grinta', '--project', str(proj)])
    got = cli_main._parse_project_dir_from_argv()
    assert got == proj.resolve()


def test_parse_project_dir_from_argv_equals(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from backend.cli import main as cli_main

    proj = tmp_path / 'eqproj'
    proj.mkdir()
    monkeypatch.setattr(sys, 'argv', [f'grinta', f'--project={proj}'])
    got = cli_main._parse_project_dir_from_argv()
    assert got == proj.resolve()
