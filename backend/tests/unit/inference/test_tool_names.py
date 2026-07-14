"""Unit tests for backend.core.tool_names."""

from __future__ import annotations

from unittest import TestCase

from backend.core.tools import tool_names

EXPECTED_EXPORTS = [
    'ACCEPTANCE_CRITERIA_TOOL_NAME',
    'ANALYZE_PROJECT_STRUCTURE_TOOL_NAME',
    'ASK_USER_TOOL_NAME',
    'BROWSER_TOOL_NAME',
    'CALL_MCP_TOOL_NAME',
    'CHECKPOINT_TOOL_NAME',
    'CREATE_FILE_TOOL_NAME',
    'DEBUGGER_TOOL_NAME',
    'DELEGATE_TASK_TOOL_NAME',
    'DOCS_QUERY_TOOL_NAME',
    'DOCS_RESOLVE_TOOL_NAME',
    'TERMINAL_TOOL_NAME',
    'FIND_SYMBOLS_TOOL_NAME',
    'GLOB_TOOL_NAME',
    'GREP_TOOL_NAME',
    'LSP_TOOL_NAME',
    'MEMORY_TOOL_NAME',
    'MULTIEDIT_TOOL_NAME',
    'NOTE_TOOL_NAME',
    'READ_FILE_TOOL_NAME',
    'RECALL_TOOL_NAME',
    'REPLACE_STRING_TOOL_NAME',
    'SEARCH_HISTORY_TOOL_NAME',
    'SHARED_TASK_BOARD_TOOL_NAME',
    'TASK_STATE_TOOL_NAME',
    'TASK_TRACKER_TOOL_NAME',
    'UNDO_LAST_EDIT_TOOL_NAME',
    'WEB_FETCH_TOOL_NAME',
    'WEB_SEARCH_TOOL_NAME',
]


class TestToolNames(TestCase):
    """Test tool_names module constants."""

    def test_finish_tool_name_not_exported(self):
        """The deleted finish tool must not remain in public tool constants."""
        self.assertFalse(hasattr(tool_names, 'FINISH_TOOL_NAME'))

    def test_all_exports_in_all_list(self):
        """Test that __all__ contains all expected exports."""
        self.assertEqual(set(tool_names.__all__), set(EXPECTED_EXPORTS))

    def test_import_from_tool_names(self):
        """Test that constants can be imported from tool_names."""
        from backend.core.tools.tool_names import (
            CALL_MCP_TOOL_NAME,
            CREATE_FILE_TOOL_NAME,
            GREP_TOOL_NAME,
            LSP_TOOL_NAME,
            TASK_TRACKER_TOOL_NAME,
        )

        self.assertIsNotNone(CALL_MCP_TOOL_NAME)
        self.assertIsNotNone(CREATE_FILE_TOOL_NAME)
        self.assertIsNotNone(GREP_TOOL_NAME)
        self.assertIsNotNone(LSP_TOOL_NAME)
        self.assertIsNotNone(TASK_TRACKER_TOOL_NAME)

    def test_all_list_length(self):
        self.assertEqual(len(tool_names.__all__), len(EXPECTED_EXPORTS))

    def test_no_extra_exports(self):
        """Test that only expected constants are exported in __all__."""
        public_attrs = [
            attr
            for attr in dir(tool_names)
            if not attr.startswith('_') and attr.isupper()
        ]

        for attr in public_attrs:
            self.assertIn(attr, tool_names.__all__)

    def test_tool_names_are_non_empty_strings(self):
        """Test that all tool names are non-empty strings."""
        for name in EXPECTED_EXPORTS:
            self.assertTrue(getattr(tool_names, name))

    def test_tool_names_consistency_with_core_constants(self):
        """Canonical file/memory tool names are defined in tool_names."""
        for name in (
            'CREATE_FILE_TOOL_NAME',
            'FIND_SYMBOLS_TOOL_NAME',
            'MULTIEDIT_TOOL_NAME',
            'NOTE_TOOL_NAME',
            'READ_FILE_TOOL_NAME',
            'RECALL_TOOL_NAME',
            'REPLACE_STRING_TOOL_NAME',
            'TASK_TRACKER_TOOL_NAME',
            'UNDO_LAST_EDIT_TOOL_NAME',
        ):
            value = getattr(tool_names, name)
            self.assertIsInstance(value, str)
            self.assertTrue(value)

    def test_runtime_strings_are_unique(self):
        """Canonical tool name strings must not collide."""
        canonical = [getattr(tool_names, name) for name in EXPECTED_EXPORTS]
        self.assertEqual(len(canonical), len(set(canonical)))

