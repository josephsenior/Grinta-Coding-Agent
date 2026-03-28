"""Unit tests for backend.inference.tool_names."""

from __future__ import annotations

from unittest import TestCase

from backend.inference import tool_names


class TestToolNames(TestCase):
    """Test tool_names module constants."""

    def test_execute_bash_tool_name_exported(self):
        """Test that EXECUTE_BASH_TOOL_NAME is exported."""
        self.assertTrue(hasattr(tool_names, "EXECUTE_BASH_TOOL_NAME"))
        self.assertIsInstance(tool_names.EXECUTE_BASH_TOOL_NAME, str)

    def test_finish_tool_name_exported(self):
        """Test that FINISH_TOOL_NAME is exported."""
        self.assertTrue(hasattr(tool_names, "FINISH_TOOL_NAME"))
        self.assertIsInstance(tool_names.FINISH_TOOL_NAME, str)

    def test_llm_based_edit_tool_name_exported(self):
        """Test that LLM_BASED_EDIT_TOOL_NAME is exported."""
        self.assertTrue(hasattr(tool_names, "LLM_BASED_EDIT_TOOL_NAME"))
        self.assertIsInstance(tool_names.LLM_BASED_EDIT_TOOL_NAME, str)

    def test_str_replace_editor_tool_name_exported(self):
        """Test that STR_REPLACE_EDITOR_TOOL_NAME is exported."""
        self.assertTrue(hasattr(tool_names, "STR_REPLACE_EDITOR_TOOL_NAME"))
        self.assertIsInstance(tool_names.STR_REPLACE_EDITOR_TOOL_NAME, str)

    def test_task_tracker_tool_name_exported(self):
        """Test that TASK_TRACKER_TOOL_NAME is exported."""
        self.assertTrue(hasattr(tool_names, "TASK_TRACKER_TOOL_NAME"))
        self.assertIsInstance(tool_names.TASK_TRACKER_TOOL_NAME, str)

    def test_all_exports_in_all_list(self):
        """Test that __all__ contains all expected exports."""
        expected_exports = [
            "EXECUTE_BASH_TOOL_NAME",
            "FINISH_TOOL_NAME",
            "LLM_BASED_EDIT_TOOL_NAME",
            "STR_REPLACE_EDITOR_TOOL_NAME",
            "TASK_TRACKER_TOOL_NAME",
        ]
        self.assertEqual(set(tool_names.__all__), set(expected_exports))

    def test_execute_bash_tool_name_value(self):
        """Test EXECUTE_BASH_TOOL_NAME has expected value from constants."""
        from backend.core.constants import EXECUTE_BASH_TOOL_NAME

        self.assertEqual(tool_names.EXECUTE_BASH_TOOL_NAME, EXECUTE_BASH_TOOL_NAME)

    def test_finish_tool_name_value(self):
        """Test FINISH_TOOL_NAME has expected value from constants."""
        from backend.core.constants import FINISH_TOOL_NAME

        self.assertEqual(tool_names.FINISH_TOOL_NAME, FINISH_TOOL_NAME)

    def test_llm_based_edit_tool_name_value(self):
        """Test LLM_BASED_EDIT_TOOL_NAME has expected value from constants."""
        from backend.core.constants import LLM_BASED_EDIT_TOOL_NAME

        self.assertEqual(tool_names.LLM_BASED_EDIT_TOOL_NAME, LLM_BASED_EDIT_TOOL_NAME)

    def test_str_replace_editor_tool_name_value(self):
        """Test STR_REPLACE_EDITOR_TOOL_NAME has expected value from constants."""
        from backend.core.constants import STR_REPLACE_EDITOR_TOOL_NAME

        self.assertEqual(
            tool_names.STR_REPLACE_EDITOR_TOOL_NAME, STR_REPLACE_EDITOR_TOOL_NAME
        )

    def test_task_tracker_tool_name_value(self):
        """Test TASK_TRACKER_TOOL_NAME has expected value from constants."""
        from backend.core.constants import TASK_TRACKER_TOOL_NAME

        self.assertEqual(tool_names.TASK_TRACKER_TOOL_NAME, TASK_TRACKER_TOOL_NAME)

    def test_import_from_tool_names(self):
        """Test that constants can be imported from tool_names."""
        from backend.inference.tool_names import (
            EXECUTE_BASH_TOOL_NAME,
            FINISH_TOOL_NAME,
            LLM_BASED_EDIT_TOOL_NAME,
            STR_REPLACE_EDITOR_TOOL_NAME,
            TASK_TRACKER_TOOL_NAME,
        )

        # Verify all imports succeeded
        self.assertIsNotNone(EXECUTE_BASH_TOOL_NAME)
        self.assertIsNotNone(FINISH_TOOL_NAME)
        self.assertIsNotNone(LLM_BASED_EDIT_TOOL_NAME)
        self.assertIsNotNone(STR_REPLACE_EDITOR_TOOL_NAME)
        self.assertIsNotNone(TASK_TRACKER_TOOL_NAME)

    def test_all_list_length(self):
        """Test that __all__ contains exactly 5 exports."""
        self.assertEqual(len(tool_names.__all__), 5)

    def test_no_extra_exports(self):
        """Test that only expected constants are exported in __all__."""
        # Get all public attributes
        public_attrs = [
            attr
            for attr in dir(tool_names)
            if not attr.startswith("_") and attr.isupper()
        ]

        # All public constants should be in __all__
        for attr in public_attrs:
            self.assertIn(attr, tool_names.__all__)

    def test_tool_names_are_non_empty_strings(self):
        """Test that all tool names are non-empty strings."""
        self.assertTrue(tool_names.EXECUTE_BASH_TOOL_NAME)
        self.assertTrue(tool_names.FINISH_TOOL_NAME)
        self.assertTrue(tool_names.LLM_BASED_EDIT_TOOL_NAME)
        self.assertTrue(tool_names.STR_REPLACE_EDITOR_TOOL_NAME)
        self.assertTrue(tool_names.TASK_TRACKER_TOOL_NAME)

    def test_tool_names_consistency_with_core_constants(self):
        """Test that tool_names module is consistent with core.constants."""
        from backend.core import constants as core_constants

        self.assertEqual(
            tool_names.EXECUTE_BASH_TOOL_NAME, core_constants.EXECUTE_BASH_TOOL_NAME
        )
        self.assertEqual(tool_names.FINISH_TOOL_NAME, core_constants.FINISH_TOOL_NAME)
        self.assertEqual(
            tool_names.LLM_BASED_EDIT_TOOL_NAME,
            core_constants.LLM_BASED_EDIT_TOOL_NAME,
        )
        self.assertEqual(
            tool_names.STR_REPLACE_EDITOR_TOOL_NAME,
            core_constants.STR_REPLACE_EDITOR_TOOL_NAME,
        )
        self.assertEqual(
            tool_names.TASK_TRACKER_TOOL_NAME, core_constants.TASK_TRACKER_TOOL_NAME
        )
