"""Tests for FileEditor create-on-existing behavior."""

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

    def test_recreate_existing_file_rejected(self):
        """Re-creating an existing file is rejected; use targeted edits instead."""
        path = Path(self.tmpdir) / 'existing.py'
        path.write_text('original content', encoding='utf-8')

        result = self.editor._handle_write(path, 'new content', is_create=True)

        self.assertIsNotNone(result.error)
        self.assertEqual(result.error_code, 'CREATE_FILE_ALREADY_EXISTS')
        self.assertEqual(result.old_content, 'original content')
        self.assertEqual(result.new_content, 'new content')
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

    def test_recreate_result_keeps_attempted_new_content(self):
        """Rejected re-create reports both current and attempted content."""
        path = Path(self.tmpdir) / 'component.tsx'
        original = 'export default function Page() { return <div/>; }'
        path.write_text(original, encoding='utf-8')

        result = self.editor._handle_write(path, 'different content', is_create=True)

        self.assertIsNotNone(result.error)
        self.assertIsNotNone(result.old_content)
        self.assertEqual(result.old_content, original)
        self.assertEqual(result.new_content, 'different content')
        self.assertEqual(path.read_text(encoding='utf-8'), original)


if __name__ == '__main__':
    unittest.main()
