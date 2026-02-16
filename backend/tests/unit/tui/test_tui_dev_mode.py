"""Tests for TUI entry point and dev-mode hot reload wiring."""

from __future__ import annotations

import argparse
from unittest.mock import patch


from backend.tui.__main__ import _parse_args, _run_app, _run_dev_mode, main


class TestParseArgs:
    """CLI argument parsing tests."""

    def test_defaults(self):
        with patch("argparse._sys.argv", ["forge-tui"]):
            args = _parse_args()
        assert args.host == "localhost"
        assert args.port == 3000
        assert args.verbose is False
        assert args.dev is False

    def test_dev_flag(self):
        with patch("argparse._sys.argv", ["forge-tui", "--dev"]):
            args = _parse_args()
        assert args.dev is True

    def test_custom_host_port(self):
        with patch("argparse._sys.argv", ["forge-tui", "--host", "0.0.0.0", "--port", "8080"]):
            args = _parse_args()
        assert args.host == "0.0.0.0"
        assert args.port == 8080

    def test_verbose_flag(self):
        with patch("argparse._sys.argv", ["forge-tui", "-v"]):
            args = _parse_args()
        assert args.verbose is True


class TestRunApp:
    """Test _run_app creates client and runs the Textual app."""

    @patch("backend.tui.app.ForgeApp")
    @patch("backend.tui.client.ForgeClient")
    def test_run_app_creates_client_and_app(self, mock_client_cls, mock_app_cls):
        _run_app("myhost", 4000, verbose=False)

        mock_client_cls.assert_called_once_with(base_url="http://myhost:4000")
        mock_app_cls.assert_called_once()
        mock_app_cls.return_value.run.assert_called_once()


class TestRunDevMode:
    """Test dev-mode wiring without actually launching watchfiles."""

    @patch("watchfiles.run_process")
    def test_dev_mode_calls_run_process(self, mock_run_proc):
        _run_dev_mode("localhost", 3000, verbose=False)

        mock_run_proc.assert_called_once()
        call_kwargs = mock_run_proc.call_args
        assert call_kwargs.kwargs.get("debounce") == 800


class TestMain:
    """Test the main dispatch function."""

    @patch("backend.tui.__main__._run_dev_mode")
    @patch("backend.tui.__main__._run_app")
    @patch("backend.tui.__main__._parse_args")
    def test_main_dispatches_dev(self, mock_parse, mock_run, mock_dev):
        mock_parse.return_value = argparse.Namespace(
            host="localhost", port=3000, verbose=False, dev=True,
        )
        main()
        mock_dev.assert_called_once_with("localhost", 3000, False)
        mock_run.assert_not_called()

    @patch("backend.tui.__main__._run_dev_mode")
    @patch("backend.tui.__main__._run_app")
    @patch("backend.tui.__main__._parse_args")
    def test_main_dispatches_normal(self, mock_parse, mock_run, mock_dev):
        mock_parse.return_value = argparse.Namespace(
            host="localhost", port=3000, verbose=False, dev=False,
        )
        main()
        mock_run.assert_called_once_with("localhost", 3000, False)
        mock_dev.assert_not_called()
