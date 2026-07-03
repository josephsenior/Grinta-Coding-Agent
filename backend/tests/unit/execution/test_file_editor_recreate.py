"""Tests for FileEditor create-on-existing behavior."""

import tempfile
import unittest
from pathlib import Path

from backend.execution.utils.file_editor import FileEditor


class TestFileEditorRecreate(unittest.TestCase):
    """Verify create_file overwrites existing paths silently."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.editor = FileEditor()

    def test_create_new_file_succeeds(self):
        path = Path(self.tmpdir) / 'new_file.py'
        result = self.editor._handle_write(path, "print('hello')")
        self.assertIn('created', result.output.lower())
        self.assertIsNone(result.error)
        self.assertEqual(result.new_content, "print('hello')")
        self.assertTrue(path.exists())

    def test_recreate_existing_file_overwrites(self):
        path = Path(self.tmpdir) / 'existing.py'
        path.write_text('original content', encoding='utf-8')

        result = self.editor._handle_write(path, 'new content')

        self.assertIsNone(result.error)
        self.assertEqual(result.old_content, 'original content')
        self.assertEqual(result.new_content, 'new content')
        self.assertEqual(path.read_text(encoding='utf-8'), 'new content')

    def test_create_file_overwrites_existing_path(self):
        path = Path(self.tmpdir) / 'file.py'
        path.write_text('old', encoding='utf-8')

        result = self.editor._handle_write(path, 'new')

        self.assertIsNone(result.error)
        self.assertEqual(result.old_content, 'old')
        self.assertEqual(result.new_content, 'new')
        self.assertEqual(path.read_text(encoding='utf-8'), 'new')


if __name__ == '__main__':
    unittest.main()
