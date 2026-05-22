"""Unit tests for backend.inference.tool_names."""

from __future__ import annotations

from unittest import TestCase

from backend.inference import tool_names


class TestToolNames(TestCase):
    """Test tool_names module constants."""

    def test_finish_tool_name_exported(self):
        """Test that FINISH_TOOL_NAME is exported."""
        self.assertTrue(hasattr(tool_names, 'FINISH_TOOL_NAME'))
        self.assertIsInstance(tool_names.FINISH_TOOL_NAME, str)

    def test_task_tracker_tool_name_exported(self):
        """Test that TASK_TRACKER_TOOL_NAME is exported."""
        self.assertTrue(hasattr(tool_names, 'TASK_TRACKER_TOOL_NAME'))
        self.assertIsInstance(tool_names.TASK_TRACKER_TOOL_NAME, str)

    def test_all_exports_in_all_list(self):
        """Test that __all__ contains all expected exports."""
        expected_exports = [
            'CREATE_FILE_TOOL_NAME',
            'FINISH_TOOL_NAME',
            'FIND_SYMBOL_TOOL_NAME',
            'READ_FILE_TOOL_NAME',
            'READ_SYMBOL_TOOL_NAME',
            'RENAME_SYMBOL_TOOL_NAME',
            'START_FILE_EDIT_TOOL_NAME',
            'TASK_TRACKER_TOOL_NAME',
            'UNDO_LAST_EDIT_TOOL_NAME',
        ]
        self.assertEqual(set(tool_names.__all__), set(expected_exports))

    def test_finish_tool_name_value(self):
        """Test FINISH_TOOL_NAME has expected value from constants."""
        from backend.core.constants import FINISH_TOOL_NAME

        self.assertEqual(tool_names.FINISH_TOOL_NAME, FINISH_TOOL_NAME)

    def test_task_tracker_tool_name_value(self):
        """Test TASK_TRACKER_TOOL_NAME has expected value from constants."""
        from backend.core.constants import TASK_TRACKER_TOOL_NAME

        self.assertEqual(tool_names.TASK_TRACKER_TOOL_NAME, TASK_TRACKER_TOOL_NAME)

    def test_import_from_tool_names(self):
        """Test that constants can be imported from tool_names."""
        from backend.inference.tool_names import (
            CREATE_FILE_TOOL_NAME,
            FINISH_TOOL_NAME,
            FIND_SYMBOL_TOOL_NAME,
            READ_FILE_TOOL_NAME,
            READ_SYMBOL_TOOL_NAME,
            RENAME_SYMBOL_TOOL_NAME,
            START_FILE_EDIT_TOOL_NAME,
            TASK_TRACKER_TOOL_NAME,
            UNDO_LAST_EDIT_TOOL_NAME,
        )

        # Verify all imports succeeded
        self.assertIsNotNone(CREATE_FILE_TOOL_NAME)
        self.assertIsNotNone(FINISH_TOOL_NAME)
        self.assertIsNotNone(FIND_SYMBOL_TOOL_NAME)
        self.assertIsNotNone(READ_FILE_TOOL_NAME)
        self.assertIsNotNone(READ_SYMBOL_TOOL_NAME)
        self.assertIsNotNone(RENAME_SYMBOL_TOOL_NAME)
        self.assertIsNotNone(START_FILE_EDIT_TOOL_NAME)
        self.assertIsNotNone(TASK_TRACKER_TOOL_NAME)
        self.assertIsNotNone(UNDO_LAST_EDIT_TOOL_NAME)

    def test_all_list_length(self):
        self.assertEqual(len(tool_names.__all__), 9)

    def test_no_extra_exports(self):
        """Test that only expected constants are exported in __all__."""
        # Get all public attributes
        public_attrs = [
            attr
            for attr in dir(tool_names)
            if not attr.startswith('_') and attr.isupper()
        ]

        # All public constants should be in __all__
        for attr in public_attrs:
            self.assertIn(attr, tool_names.__all__)

    def test_tool_names_are_non_empty_strings(self):
        """Test that all tool names are non-empty strings."""
        self.assertTrue(tool_names.FINISH_TOOL_NAME)
        self.assertTrue(tool_names.CREATE_FILE_TOOL_NAME)
        self.assertTrue(tool_names.FIND_SYMBOL_TOOL_NAME)
        self.assertTrue(tool_names.READ_FILE_TOOL_NAME)
        self.assertTrue(tool_names.READ_SYMBOL_TOOL_NAME)
        self.assertTrue(tool_names.RENAME_SYMBOL_TOOL_NAME)
        self.assertTrue(tool_names.START_FILE_EDIT_TOOL_NAME)
        self.assertTrue(tool_names.TASK_TRACKER_TOOL_NAME)
        self.assertTrue(tool_names.UNDO_LAST_EDIT_TOOL_NAME)

    def test_tool_names_consistency_with_core_constants(self):
        """Test that tool_names module is consistent with core.constants."""
        from backend.core import constants as core_constants

        self.assertEqual(
            tool_names.CREATE_FILE_TOOL_NAME, core_constants.CREATE_FILE_TOOL_NAME
        )
        self.assertEqual(tool_names.FINISH_TOOL_NAME, core_constants.FINISH_TOOL_NAME)
        self.assertEqual(
            tool_names.FIND_SYMBOL_TOOL_NAME, core_constants.FIND_SYMBOL_TOOL_NAME
        )
        self.assertEqual(
            tool_names.READ_FILE_TOOL_NAME, core_constants.READ_FILE_TOOL_NAME
        )
        self.assertEqual(
            tool_names.READ_SYMBOL_TOOL_NAME, core_constants.READ_SYMBOL_TOOL_NAME
        )
        self.assertEqual(
            tool_names.RENAME_SYMBOL_TOOL_NAME, core_constants.RENAME_SYMBOL_TOOL_NAME
        )
        self.assertEqual(
            tool_names.TASK_TRACKER_TOOL_NAME, core_constants.TASK_TRACKER_TOOL_NAME
        )
        self.assertEqual(
            tool_names.UNDO_LAST_EDIT_TOOL_NAME,
            core_constants.UNDO_LAST_EDIT_TOOL_NAME,
        )
