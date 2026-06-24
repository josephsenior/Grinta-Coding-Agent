"""Tests for CLI logging / dotenv bootstrap in ``backend.cli.main``."""

from __future__ import annotations

import logging
import os
import sys
from unittest.mock import patch

import pytest


def test_log_to_file_effective_explicit_true() -> None:
    from backend.cli import main as cli_main

    with patch.dict(
        os.environ, {'LOG_TO_FILE': 'true', 'LOG_LEVEL': 'INFO'}, clear=False
    ):
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


def test_app_settings_dotenv_path_uses_settings_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from backend.cli import main as cli_main

    settings_root = tmp_path / 'grinta-home'
    settings_root.mkdir()
    monkeypatch.setenv('APP_ROOT', str(settings_root))
    assert cli_main._app_settings_dotenv_path() == settings_root / '.env'


def test_load_dotenv_early_reads_settings_root_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from backend.cli import main as cli_main

    settings_root = tmp_path / 'grinta-home'
    settings_root.mkdir()
    env_file = settings_root / '.env'
    env_file.write_text('LLM_API_KEY=from-settings-root\n', encoding='utf-8')
    monkeypatch.setenv('APP_ROOT', str(settings_root))
    monkeypatch.delenv('LLM_API_KEY', raising=False)

    cli_main._load_dotenv_early()

    assert os.environ.get('LLM_API_KEY') == 'from-settings-root'
