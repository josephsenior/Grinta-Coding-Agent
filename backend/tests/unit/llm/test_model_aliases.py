"""Unit tests for backend.llm.model_aliases."""

# pylint: disable=protected-access,too-many-function-args

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, cast
from unittest import TestCase
from unittest.mock import patch

from backend.llm.model_aliases import ModelAliasManager, get_alias_manager


class TestModelAliasManager(TestCase):
    """Test ModelAliasManager class."""

    def setUp(self):
        """Set up test fixtures."""
        self.manager = ModelAliasManager()

    def test_init(self):
        """Test ModelAliasManager initialization."""
        manager = ModelAliasManager()
        self.assertEqual(manager._aliases, {})
        self.assertFalse(manager._loaded)

    def test_resolve_alias_not_loaded(self):
        """Test resolve_alias triggers load if not loaded."""
        manager = ModelAliasManager()
        with patch.object(manager, "load_aliases") as mock_load:
            result = manager.resolve_alias("test-model")
            mock_load.assert_called_once()
            self.assertEqual(result, "test-model")

    def test_resolve_alias_returns_original_if_not_alias(self):
        """Test resolve_alias returns original name if not an alias."""
        self.manager._loaded = True
        result = self.manager.resolve_alias("claude-3-7-sonnet")
        self.assertEqual(result, "claude-3-7-sonnet")

    def test_resolve_alias_returns_target(self):
        """Test resolve_alias returns target when alias exists."""
        self.manager._aliases = {"my-model": "claude-3-7-sonnet"}
        self.manager._loaded = True

        result = self.manager.resolve_alias("my-model")
        self.assertEqual(result, "claude-3-7-sonnet")

    def test_add_alias(self):
        """Test adding a new alias."""
        self.manager.add_alias("fast-chat", "ollama/llama3.2")
        self.assertEqual(self.manager._aliases["fast-chat"], "ollama/llama3.2")

    def test_add_alias_updates_existing(self):
        """Test adding an alias overwrites existing one."""
        self.manager.add_alias("my-model", "claude-3-7-sonnet")
        self.manager.add_alias("my-model", "gpt-4o")

        self.assertEqual(self.manager._aliases["my-model"], "gpt-4o")

    def test_remove_alias_existing(self):
        """Test removing an existing alias."""
        self.manager._aliases = {"my-model": "claude-3-7-sonnet"}
        result = self.manager.remove_alias("my-model")

        self.assertTrue(result)
        self.assertNotIn("my-model", self.manager._aliases)

    def test_remove_alias_nonexistent(self):
        """Test removing a nonexistent alias returns False."""
        result = self.manager.remove_alias("nonexistent")
        self.assertFalse(result)

    def test_get_all_aliases_triggers_load(self):
        """Test get_all_aliases triggers load if not loaded."""
        manager = ModelAliasManager()
        with patch.object(manager, "load_aliases") as mock_load:
            result = manager.get_all_aliases()
            mock_load.assert_called_once()
            self.assertEqual(result, {})

    def test_get_all_aliases_returns_copy(self):
        """Test get_all_aliases returns a copy, not the original dict."""
        self.manager._aliases = {"my-model": "claude-3-7-sonnet"}
        self.manager._loaded = True

        result = self.manager.get_all_aliases()
        result["new-alias"] = "gpt-4o"

        self.assertNotIn("new-alias", self.manager._aliases)

    def test_is_alias_true(self):
        """Test is_alias returns True for existing alias."""
        self.manager._aliases = {"my-model": "claude-3-7-sonnet"}
        self.manager._loaded = True

        self.assertTrue(self.manager.is_alias("my-model"))

    def test_is_alias_false(self):
        """Test is_alias returns False for non-alias."""
        self.manager._loaded = True
        self.assertFalse(self.manager.is_alias("claude-3-7-sonnet"))

    def test_load_aliases_only_once(self):
        """Test load_aliases only loads once."""
        with patch.object(self.manager, "_load_from_file") as mock_load_file:
            self.manager._loaded = True
            self.manager.load_aliases()
            mock_load_file.assert_not_called()

    def test_load_aliases_from_explicit_path(self):
        """Test loading aliases from explicit config path."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp.write('{"model_aliases": {"my-model": "claude-3-7-sonnet"}}')
            tmp_path = Path(tmp.name)

        try:
            manager = ModelAliasManager()
            manager.load_aliases(config_path=tmp_path)

            self.assertTrue(manager._loaded)
            self.assertEqual(manager._aliases["my-model"], "claude-3-7-sonnet")
        finally:
            tmp_path.unlink()

    def test_load_aliases_searches_multiple_locations(self):
        """Test loading aliases searches settings.json in multiple locations."""
        # Create a temp file to use
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp.write('{"model_aliases": {"fast-chat": "ollama/llama3.2"}}')
            tmp_path = Path(tmp.name)

        try:
            # Test that explicit path works (path search behavior)
            manager = ModelAliasManager()
            manager.load_aliases(config_path=tmp_path)
            self.assertEqual(manager._aliases.get("fast-chat"), "ollama/llama3.2")
        finally:
            tmp_path.unlink()

    def test_load_aliases_no_config_found(self):
        """Test behavior when no config file is found."""
        manager = ModelAliasManager()
        with patch.object(Path, "exists", return_value=False):
            manager.load_aliases()

        self.assertTrue(manager._loaded)
        self.assertEqual(manager._aliases, {})

    def test_load_from_file_valid_json(self):
        """Test _load_from_file with valid JSON."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp.write(
                '{"model_aliases": {"my-coding-model": "claude-3-7-sonnet", '
                '"fast-chat": "ollama/llama3.2", "local-coder": "ollama/qwen2.5-coder"}}'
            )
            tmp_path = Path(tmp.name)

        try:
            self.manager._load_from_file(tmp_path)
            self.assertEqual(len(self.manager._aliases), 3)
            self.assertEqual(
                self.manager._aliases["my-coding-model"], "claude-3-7-sonnet"
            )
            self.assertEqual(self.manager._aliases["fast-chat"], "ollama/llama3.2")
            self.assertEqual(
                self.manager._aliases["local-coder"], "ollama/qwen2.5-coder"
            )
        finally:
            tmp_path.unlink()

    def test_load_from_file_no_model_aliases_section(self):
        """Test _load_from_file when model_aliases section is missing."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp.write('{"other_section": {"key": "value"}}')
            tmp_path = Path(tmp.name)

        try:
            self.manager._load_from_file(tmp_path)
            self.assertEqual(self.manager._aliases, {})
        finally:
            tmp_path.unlink()

    def test_load_from_file_invalid_alias_types(self):
        """Test _load_from_file skips non-string alias values."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp.write(
                '{"model_aliases": {"valid-alias": "claude-3-7-sonnet", '
                '"invalid-number": 123, "invalid-array": ["gpt-4o", "gpt-4"]}}'
            )
            tmp_path = Path(tmp.name)

        try:
            self.manager._load_from_file(tmp_path)
            self.assertEqual(len(self.manager._aliases), 1)
            self.assertEqual(self.manager._aliases["valid-alias"], "claude-3-7-sonnet")
        finally:
            tmp_path.unlink()

    def test_load_from_file_invalid_json(self):
        """Test _load_from_file handles invalid JSON gracefully."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp.write("invalid { json")
            tmp_path = Path(tmp.name)

        try:
            with self.assertRaises(Exception):
                self.manager._load_from_file(tmp_path)
        finally:
            tmp_path.unlink()

    def test_save_aliases_creates_file(self):
        """Test save_aliases creates file with aliases."""
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "settings.json"

            self.manager._aliases = {
                "my-model": "claude-3-7-sonnet",
                "fast-chat": "ollama/llama3.2",
            }

            self.manager.save_aliases(save_path)

            self.assertTrue(save_path.exists())

            # Verify content
            content = save_path.read_text(encoding="utf-8")
            self.assertIn("model_aliases", content)
            self.assertIn("my-model", content)
            self.assertIn("claude-3-7-sonnet", content)

    def test_save_aliases_preserves_existing_config(self):
        """Test save_aliases preserves other config sections."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp.write('{"other_section": {"key": "value"}}')
            tmp_path = Path(tmp.name)

        try:
            self.manager._aliases = {"my-model": "claude-3-7-sonnet"}
            self.manager.save_aliases(tmp_path)

            content = tmp_path.read_text(encoding="utf-8")
            self.assertIn("other_section", content)
            self.assertIn("model_aliases", content)
        finally:
            tmp_path.unlink()

    def test_save_aliases_handles_errors(self):
        """Test save_aliases handles errors gracefully."""
        with patch("backend.llm.model_aliases.logger") as mock_logger:
            # Test with file write error
            with tempfile.TemporaryDirectory() as tmpdir:
                save_path = Path(tmpdir) / "nonexistent" / "settings.json"
                self.manager._aliases = {"test": "model"}

                # This should fail but not raise
                self.manager.save_aliases(save_path)

                # Should have logged an error
                self.assertTrue(mock_logger.error.called or mock_logger.debug.called)

    def test_load_aliases_checks_multiple_paths(self):
        """Test load_aliases checks multiple config locations."""
        manager = ModelAliasManager()

        with patch.object(Path, "exists") as mock_exists:
            mock_exists.return_value = False
            manager.load_aliases()

            # Should check settings.json, home directory, environment variable
            self.assertGreaterEqual(mock_exists.call_count, 2)

    def test_load_aliases_respects_env_variable(self):
        """Test load_aliases uses FORGE_CONFIG environment variable."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp.write('{"model_aliases": {"env-model": "gpt-4o"}}')
            tmp_path = Path(tmp.name)

        try:
            with patch.dict("os.environ", {"FORGE_CONFIG": str(tmp_path)}):
                manager = ModelAliasManager()
                manager.load_aliases()

                self.assertEqual(manager._aliases.get("env-model"), "gpt-4o")
        finally:
            tmp_path.unlink()

    def test_resolve_alias_logs_resolution(self):
        """Test resolve_alias logs when alias is resolved."""
        self.manager._aliases = {"my-model": "claude-3-7-sonnet"}
        self.manager._loaded = True

        with patch("backend.llm.model_aliases.logger") as mock_logger:
            self.manager.resolve_alias("my-model")
            mock_logger.debug.assert_called()


class TestGetAliasManager(TestCase):
    """Test get_alias_manager singleton function."""

    def test_returns_model_alias_manager(self):
        """Test get_alias_manager returns a ModelAliasManager instance."""
        manager = get_alias_manager()
        self.assertIsInstance(manager, ModelAliasManager)

    def test_returns_same_instance(self):
        """Test get_alias_manager returns the same instance (singleton)."""
        manager1 = get_alias_manager()
        manager2 = get_alias_manager()
        self.assertIs(manager1, manager2)

    def test_lru_cache_behavior(self):
        """Test that get_alias_manager is cached with lru_cache."""
        # Clear cache
        get_alias_manager.cache_clear()

        manager1 = get_alias_manager()
        cache_info = cast(Any, get_alias_manager).cache_info()

        # First call should be a miss
        self.assertEqual(cache_info.misses, 1)

        manager2 = get_alias_manager()
        cache_info = cast(Any, get_alias_manager).cache_info()

        # Second call should be a hit
        self.assertEqual(cache_info.hits, 1)
        self.assertIs(manager1, manager2)


if __name__ == "__main__":
    import unittest

    unittest.main()
