"""Unit tests for backend.inference.discover_models."""

from __future__ import annotations

import sys
from io import StringIO
from unittest import TestCase
from unittest.mock import patch

from backend.inference.discover_models import (
    discover_command,
    main,
    print_section,
    status_command,
)


class TestPrintSection(TestCase):
    """Test print_section utility function."""

    def test_print_section_basic(self):
        """Test printing a basic section header."""
        with patch("sys.stdout", new=StringIO()) as fake_out:
            print_section("Test Title")
            output = fake_out.getvalue()

        self.assertIn("=" * 60, output)
        self.assertIn("Test Title", output)

    def test_print_section_long_title(self):
        """Test printing a section with long title."""
        with patch("sys.stdout", new=StringIO()) as fake_out:
            print_section("A Very Long Title That Should Still Work Fine")
            output = fake_out.getvalue()

        self.assertIn("A Very Long Title That Should Still Work Fine", output)

    def test_print_section_formatting(self):
        """Test section has proper formatting."""
        with patch("sys.stdout", new=StringIO()) as fake_out:
            print_section("Header")
            output = fake_out.getvalue()

        lines = output.strip().split("\n")
        self.assertGreaterEqual(len(lines), 3)


class TestDiscoverCommand(TestCase):
    """Test discover_command function."""

    @patch("backend.inference.discover_models.discover_all_local_models")
    def test_discover_no_models(self, mock_discover):
        """Test discover when no local models are found."""
        mock_discover.return_value = {}

        with patch("sys.stdout", new=StringIO()) as fake_out:
            discover_command()
            output = fake_out.getvalue()

        self.assertIn("No local providers found", output)
        self.assertIn("Install Ollama", output)

    @patch("backend.inference.discover_models.discover_all_local_models")
    def test_discover_with_ollama_models(self, mock_discover):
        """Test discover with Ollama models."""
        mock_discover.return_value = {"ollama": ["llama3.2", "codellama"]}

        with patch("sys.stdout", new=StringIO()) as fake_out:
            discover_command()
            output = fake_out.getvalue()

        self.assertIn("Found 2 models", output)
        self.assertIn("OLLAMA", output)
        self.assertIn("llama3.2", output)
        self.assertIn("codellama", output)
        self.assertIn("Usage examples", output)

    @patch("backend.inference.discover_models.discover_all_local_models")
    def test_discover_multiple_providers(self, mock_discover):
        """Test discover with multiple providers."""
        mock_discover.return_value = {
            "ollama": ["model1", "model2"],
            "lmstudio": ["model3"],
        }

        with patch("sys.stdout", new=StringIO()) as fake_out:
            discover_command()
            output = fake_out.getvalue()

        self.assertIn("Found 3 models", output)
        self.assertIn("2 providers", output)
        self.assertIn("OLLAMA", output)
        self.assertIn("LMSTUDIO", output)

    @patch("backend.inference.discover_models.discover_all_local_models")
    def test_discover_shows_usage_examples(self, mock_discover):
        """Test that discover shows usage examples for Ollama."""
        mock_discover.return_value = {"ollama": ["llama3.2"]}

        with patch("sys.stdout", new=StringIO()) as fake_out:
            discover_command()
            output = fake_out.getvalue()

        self.assertIn("ollama/llama3.2", output)
        self.assertIn("llm_model", output)


class TestStatusCommand(TestCase):
    """Test status_command function."""

    @patch("backend.inference.discover_models.check_local_providers")
    def test_status_all_running(self, mock_check):
        """Test status when all providers are running."""
        mock_check.return_value = {"ollama": True, "lmstudio": True}

        with patch("sys.stdout", new=StringIO()) as fake_out:
            status_command()
            output = fake_out.getvalue()

        self.assertIn("OLLAMA", output)
        self.assertIn("RUNNING", output)
        self.assertIn("LMSTUDIO", output)

    @patch("backend.inference.discover_models.check_local_providers")
    def test_status_none_running(self, mock_check):
        """Test status when no providers are running."""
        mock_check.return_value = {"ollama": False, "lmstudio": False}

        with patch("sys.stdout", new=StringIO()) as fake_out:
            status_command()
            output = fake_out.getvalue()

        self.assertIn("NOT FOUND", output)
        self.assertIn("No local providers are running", output)
        self.assertIn("ollama serve", output)

    @patch("backend.inference.discover_models.check_local_providers")
    def test_status_mixed(self, mock_check):
        """Test status with mixed provider availability."""
        mock_check.return_value = {"ollama": True, "lmstudio": False}

        with patch("sys.stdout", new=StringIO()) as fake_out:
            status_command()
            output = fake_out.getvalue()

        lines = output.split("\n")
        status_lines = [ln for ln in lines if "RUNNING" in ln or "NOT FOUND" in ln]
        self.assertGreaterEqual(len(status_lines), 2)

    @patch("backend.inference.discover_models.check_local_providers")
    def test_status_empty_providers(self, mock_check):
        """Test status when no providers are configured."""
        mock_check.return_value = {}

        with patch("sys.stdout", new=StringIO()) as fake_out:
            status_command()
            output = fake_out.getvalue()

        self.assertIn("No local providers are running", output)


class TestMain(TestCase):
    """Test main entry point function."""

    @patch("backend.inference.discover_models.discover_command")
    def test_main_no_args_default_discover(self, mock_discover):
        """Test main with no arguments defaults to discover."""
        with patch.object(sys, "argv", ["discover_models.py"]):
            result = main()

        mock_discover.assert_called_once()
        self.assertEqual(result, 0)

    @patch("backend.inference.discover_models.discover_command")
    def test_main_discover_command(self, mock_discover):
        """Test main with explicit discover command."""
        with patch.object(sys, "argv", ["discover_models.py", "discover"]):
            result = main()

        mock_discover.assert_called_once()
        self.assertEqual(result, 0)

    @patch("backend.inference.discover_models.status_command")
    def test_main_status_command(self, mock_status):
        """Test main with status command."""
        with patch.object(sys, "argv", ["discover_models.py", "status"]):
            result = main()

        mock_status.assert_called_once()
        self.assertEqual(result, 0)

    def test_main_unknown_command(self):
        """Test main with unknown command."""
        with patch.object(sys, "argv", ["discover_models.py", "unknown"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                result = main()
                output = fake_out.getvalue()

        self.assertEqual(result, 1)
        self.assertIn("Unknown command", output)
        self.assertIn("discover", output)
        self.assertIn("status", output)

    @patch("backend.inference.discover_models.discover_command")
    @patch("backend.inference.discover_models.logger")
    def test_main_exception_handling(self, mock_logger, mock_discover):
        """Test main handles exceptions gracefully."""
        mock_discover.side_effect = RuntimeError("Test error")

        with patch.object(sys, "argv", ["discover_models.py", "discover"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                result = main()
                fake_out.getvalue()

        self.assertEqual(result, 1)
        mock_logger.error.assert_called_once()

    def test_main_case_insensitive_commands(self):
        """Test that commands are case-insensitive."""
        with patch("backend.inference.discover_models.status_command") as mock_status:
            with patch.object(sys, "argv", ["discover_models.py", "STATUS"]):
                result = main()

        mock_status.assert_called_once()
        self.assertEqual(result, 0)

    @patch("backend.inference.discover_models.discover_command")
    def test_main_extra_args_ignored(self, mock_discover):
        """Test that extra arguments are ignored."""
        with patch.object(
            sys, "argv", ["discover_models.py", "discover", "extra", "args"]
        ):
            result = main()

        mock_discover.assert_called_once()
        self.assertEqual(result, 0)

    def test_main_empty_command(self):
        """Test main with empty command string."""
        with patch.object(sys, "argv", ["discover_models.py", ""]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                result = main()
                output = fake_out.getvalue()

        self.assertEqual(result, 1)
        self.assertIn("Unknown command", output)


if __name__ == "__main__":
    import unittest

    unittest.main()
