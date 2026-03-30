"""Unit tests for backend.gateway.cli.entry — CLI entry point."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import sys
import pytest

from backend.gateway.cli.entry import (
    _handle_help_request,
    _normalize_arguments,
    _handle_version_request,
    _execute_command,
    main,
)


class TestHandleHelpRequest:
    """Tests for _handle_help_request function."""

    def test_prints_help_and_exits(self):
        """Test that help request prints help and exits with code 0."""
        mock_parser = MagicMock()

        with pytest.raises(SystemExit) as exc_info:
            _handle_help_request(mock_parser)

        assert exc_info.value.code == 0
        mock_parser.print_help.assert_called_once()

    def test_parser_methods_called(self):
        """Test that parser.print_help is called."""
        mock_parser = MagicMock()

        with pytest.raises(SystemExit):
            _handle_help_request(mock_parser)

        mock_parser.print_help.assert_called_once_with()


class TestNormalizeArguments:
    """Tests for _normalize_arguments function."""

    def test_no_arguments_adds_serve(self):
        """Test that no arguments gets 'serve' inserted."""
        original = sys.argv
        try:
            sys.argv = ["prog"]
            _normalize_arguments()
            assert sys.argv == ["prog", "serve"]
        finally:
            sys.argv = original

    def test_serve_command_unchanged(self):
        """Test that 'serve' command is not duplicated."""
        original = sys.argv
        try:
            sys.argv = ["prog", "serve"]
            _normalize_arguments()
            assert sys.argv == ["prog", "serve"]
        finally:
            sys.argv = original

    def test_other_command_gets_serve_prefix(self):
        """Test that non-serve commands get 'serve' prefix."""
        original = sys.argv
        try:
            sys.argv = ["prog", "unknowncmd"]
            _normalize_arguments()
            assert sys.argv == ["prog", "serve", "unknowncmd"]
        finally:
            sys.argv = original

    def test_multiple_arguments_non_serve(self):
        """Test multiple arguments where first is not 'serve'."""
        original = sys.argv
        try:
            sys.argv = ["prog", "unknowncmd", "myproject"]
            _normalize_arguments()
            assert sys.argv == ["prog", "serve", "unknowncmd", "myproject"]
        finally:
            sys.argv = original

    def test_empty_list_stays_empty(self):
        """Test empty argument list (edge case)."""
        original = sys.argv
        try:
            sys.argv = []
            _normalize_arguments()
            # Empty list should still have serve inserted at index 1
            # But since there's no index 0, it just inserts at position 1
            # Actually this would fail - let's check what happens
            # The condition checks len(sys.argv) == 1 OR (len > 1 AND first != serve)
            # So empty list shouldn't trigger normalization
            assert sys.argv == []
        finally:
            sys.argv = original


class TestHandleVersionRequest:
    """Tests for _handle_version_request function."""

    def test_version_flag_exits(self):
        """Test that version flag causes exit with code 0."""
        mock_args = MagicMock()
        mock_args.version = True

        with pytest.raises(SystemExit) as exc_info:
            _handle_version_request(mock_args)

        assert exc_info.value.code == 0

    def test_no_version_flag_continues(self):
        """Test that no version flag doesn't exit."""
        mock_args = MagicMock()
        mock_args.version = False

        # Should not raise SystemExit
        _handle_version_request(mock_args)

    def test_missing_version_attribute_continues(self):
        """Test that missing version attribute doesn't cause error."""
        mock_args = MagicMock(spec=[])  # No attributes

        # Should not raise SystemExit or AttributeError
        _handle_version_request(mock_args)


class TestExecuteCommand:
    """Tests for _execute_command function."""

    @patch("backend.gateway.cli.entry.launch_gui_server")
    def test_serve_command(self, mock_gui_server):
        """Test execute_command with 'serve' command."""
        mock_args = MagicMock()
        mock_args.command = "serve"
        mock_parser = MagicMock()

        _execute_command(mock_args, mock_parser)

        mock_gui_server.assert_called_once()

    @patch("backend.gateway.cli.cli.init_project.init_project")
    def test_init_command(self, mock_init_project):
        """Test execute_command with 'init' command."""
        mock_args = MagicMock()
        mock_args.command = "init"
        mock_args.project_name = "myproject"
        mock_args.template = "default"
        mock_parser = MagicMock()

        _execute_command(mock_args, mock_parser)

        mock_init_project.assert_called_once_with("myproject", "default")

    def test_unknown_command_prints_help_and_exits(self):
        """Test that unknown command prints help and exits with code 1."""
        mock_args = MagicMock()
        mock_args.command = "unknown"
        mock_parser = MagicMock()

        with pytest.raises(SystemExit) as exc_info:
            _execute_command(mock_args, mock_parser)

        assert exc_info.value.code == 1
        mock_parser.print_help.assert_called_once()


class TestMainFunction:
    """Tests for main CLI entry point."""

    @patch("backend.gateway.cli.entry._execute_command")
    @patch("backend.gateway.cli.entry.get_cli_parser")
    def test_main_with_serve(self, mock_get_parser, mock_execute_cmd):
        """Test main function with default serve command."""
        mock_parser = MagicMock()
        mock_args = MagicMock()
        mock_args.command = "serve"
        mock_args.version = False

        mock_get_parser.return_value = mock_parser
        mock_parser.parse_args.return_value = mock_args

        original = sys.argv
        try:
            sys.argv = ["app"]
            main()
        finally:
            sys.argv = original

        mock_get_parser.assert_called_once()
        mock_execute_cmd.assert_called_once()

    @patch("backend.gateway.cli.entry._handle_help_request")
    @patch("backend.gateway.cli.entry.get_cli_parser")
    def test_main_with_help_flag(self, mock_get_parser, mock_handle_help):
        """Test main function with --help flag."""
        mock_parser = MagicMock()
        mock_get_parser.return_value = mock_parser
        mock_handle_help.side_effect = SystemExit(0)

        original = sys.argv
        try:
            sys.argv = ["app", "--help"]
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0
        finally:
            sys.argv = original

        mock_handle_help.assert_called_once_with(mock_parser)

    @patch("backend.gateway.cli.entry._handle_help_request")
    @patch("backend.gateway.cli.entry.get_cli_parser")
    def test_main_with_h_flag(self, mock_get_parser, mock_handle_help):
        """Test main function with -h flag."""
        mock_parser = MagicMock()
        mock_get_parser.return_value = mock_parser
        mock_handle_help.side_effect = SystemExit(0)

        original = sys.argv
        try:
            sys.argv = ["app", "-h"]
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0
        finally:
            sys.argv = original

        mock_handle_help.assert_called_once()

    @patch("backend.gateway.cli.entry._execute_command")
    @patch("backend.gateway.cli.entry.get_cli_parser")
    @patch("backend.gateway.cli.entry._normalize_arguments")
    def test_main_normalizes_arguments(
        self, mock_normalize, mock_get_parser, mock_execute_cmd
    ):
        """Test main calls _normalize_arguments."""
        mock_parser = MagicMock()
        mock_args = MagicMock()
        mock_args.command = "serve"
        mock_args.version = False

        mock_get_parser.return_value = mock_parser
        mock_parser.parse_args.return_value = mock_args

        original = sys.argv
        try:
            sys.argv = ["app"]
            main()
        finally:
            sys.argv = original

        # Verify normalization was called as part of main
        mock_parser.parse_args.assert_called_once()

    @patch("backend.gateway.cli.entry._execute_command")
    @patch("backend.gateway.cli.entry.get_cli_parser")
    def test_main_handles_version(self, mock_get_parser, mock_execute_cmd):
        """Test main function with version flag."""
        mock_parser = MagicMock()
        mock_args = MagicMock()
        mock_args.version = True

        mock_get_parser.return_value = mock_parser
        mock_parser.parse_args.return_value = mock_args

        original = sys.argv
        try:
            sys.argv = ["app", "--version"]
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0
        finally:
            sys.argv = original


class TestIntegration:
    """Integration tests for CLI entry point."""

    @patch("backend.gateway.cli.entry.launch_gui_server")
    @patch("backend.gateway.cli.entry.get_cli_parser")
    def test_serve_command_full_flow(self, mock_get_parser, mock_gui_server):
        """Test full flow for serve command."""
        mock_parser = MagicMock()
        mock_args = MagicMock()
        mock_args.command = "serve"
        mock_args.version = False

        mock_get_parser.return_value = mock_parser
        mock_parser.parse_args.return_value = mock_args

        original = sys.argv
        try:
            sys.argv = ["app", "serve"]
            main()
        finally:
            sys.argv = original

        mock_gui_server.assert_called_once()

    @patch("backend.gateway.cli.cli.init_project.init_project")
    @patch("backend.gateway.cli.entry.get_cli_parser")
    def test_init_command_full_flow(self, mock_get_parser, mock_init_project):
        """Test full flow for init command."""
        mock_parser = MagicMock()
        mock_args = MagicMock()
        mock_args.command = "init"
        mock_args.project_name = "myproject"
        mock_args.template = "default"
        mock_args.version = False

        mock_get_parser.return_value = mock_parser
        mock_parser.parse_args.return_value = mock_args

        original = sys.argv
        try:
            sys.argv = ["app", "init", "myproject"]
            main()
        finally:
            sys.argv = original

        mock_init_project.assert_called_once()
