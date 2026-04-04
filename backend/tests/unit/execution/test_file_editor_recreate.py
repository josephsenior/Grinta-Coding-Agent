"""Tests for FileEditor silent re-create fix.

When a file already exists and the agent issues a 'create' command,
the editor should return silent success with old_content == new_content
instead of raising an error (which derails weak models).
"""

import tempfile
import unittest
from pathlib import Path

from backend.execution.utils.file_editor import FileEditor


class TestFileEditorRecreate(unittest.TestCase):
    """Verify silent success on file re-creation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.editor = FileEditor()

    def test_create_new_file_succeeds(self):
        """Creating a genuinely new file works normally."""
        path = Path(self.tmpdir) / 'new_file.py'
        result = self.editor._handle_write(path, "print('hello')", is_create=True)
        self.assertIn('created', result.output.lower())
        self.assertIsNone(result.error)
        self.assertEqual(result.new_content, "print('hello')")
        self.assertTrue(path.exists())

    def test_recreate_existing_file_silent_success(self):
        """Re-creating an existing file returns silent success."""
        path = Path(self.tmpdir) / 'existing.py'
        path.write_text('original content', encoding='utf-8')

        result = self.editor._handle_write(path, 'new content', is_create=True)

        # Should succeed silently
        self.assertIn('created', result.output.lower())
        self.assertIsNone(result.error)
        # old_content == new_content signals re-creation to stuck detector
        self.assertEqual(result.old_content, result.new_content)
        self.assertEqual(result.old_content, 'original content')
        # File should NOT be overwritten
        self.assertEqual(path.read_text(encoding='utf-8'), 'original content')

    def test_write_existing_file_overwrites(self):
        """Normal write (not create) to existing file overwrites content."""
        path = Path(self.tmpdir) / 'file.py'
        path.write_text('old', encoding='utf-8')

        result = self.editor._handle_write(path, 'new', is_create=False)

        self.assertIn('written', result.output.lower())
        self.assertEqual(result.old_content, 'old')
        self.assertEqual(result.new_content, 'new')
        self.assertEqual(path.read_text(encoding='utf-8'), 'new')

    def test_recreate_sets_old_equals_new(self):
        """Re-creation sets old_content == new_content for stuck detection."""
        path = Path(self.tmpdir) / 'component.tsx'
        original = 'export default function Page() { return <div/>; }'
        path.write_text(original, encoding='utf-8')

        result = self.editor._handle_write(path, 'different content', is_create=True)

        # Key invariant: old == new so stuck detector sees "no_change"
        self.assertIsNotNone(result.old_content)
        self.assertEqual(result.old_content, result.new_content)


if __name__ == '__main__':
    unittest.main()
