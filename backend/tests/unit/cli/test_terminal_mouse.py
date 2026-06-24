"""Tests for focus-aware Textual mouse reporting toggles."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.cli.terminal_mouse import set_textual_mouse_reporting


def test_set_textual_mouse_reporting_enable() -> None:
    driver = MagicMock()
    app = MagicMock(_driver=driver)
    set_textual_mouse_reporting(app, enabled=True)
    driver._enable_mouse_support.assert_called_once()
    driver._disable_mouse_support.assert_not_called()


def test_set_textual_mouse_reporting_disable() -> None:
    driver = MagicMock()
    app = MagicMock(_driver=driver)
    set_textual_mouse_reporting(app, enabled=False)
    driver._disable_mouse_support.assert_called_once()
    driver._enable_mouse_support.assert_not_called()


def test_set_textual_mouse_reporting_noop_without_driver() -> None:
    set_textual_mouse_reporting(None, enabled=False)
    set_textual_mouse_reporting(MagicMock(_driver=None), enabled=True)
