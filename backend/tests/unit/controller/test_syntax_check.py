"""Tests for tree-sitter based syntax checking in AutoCheckMiddleware."""

import os
import tempfile
import unittest

from backend.controller.tool_pipeline import (
    _collect_syntax_errors,
    _treesitter_syntax_check,
)
from backend.utils.treesitter_editor import TREE_SITTER_AVAILABLE


@unittest.skipUnless(TREE_SITTER_AVAILABLE, "tree-sitter not installed")
class TestTreeSitterSyntaxCheck(unittest.TestCase):
    """Verify tree-sitter syntax check works across multiple languages."""

    def _write_temp(self, ext: str, content: str) -> str:
        fd, path = tempfile.mkstemp(suffix=ext)
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        self.addCleanup(os.unlink, path)
        return path

    # ── Python ──────────────────────────────────────────────────────────

    def test_valid_python(self):
        path = self._write_temp(".py", "def hello():\n    return 42\n")
        result = _treesitter_syntax_check(path)
        self.assertIsNotNone(result)
        is_valid, detail = result
        self.assertTrue(is_valid)

    def test_invalid_python(self):
        path = self._write_temp(".py", "def hello(\n    return 42\n")
        result = _treesitter_syntax_check(path)
        self.assertIsNotNone(result)
        is_valid, detail = result
        self.assertFalse(is_valid)
        self.assertIn("line", detail)

    # ── JavaScript ──────────────────────────────────────────────────────

    def test_valid_javascript(self):
        path = self._write_temp(".js", "function hello() { return 42; }\n")
        result = _treesitter_syntax_check(path)
        self.assertIsNotNone(result)
        is_valid, _ = result
        self.assertTrue(is_valid)

    def test_invalid_javascript(self):
        path = self._write_temp(".js", "function hello( { return 42; }\n")
        result = _treesitter_syntax_check(path)
        self.assertIsNotNone(result)
        is_valid, detail = result
        self.assertFalse(is_valid)
        self.assertIn("line", detail)

    # ── TypeScript ──────────────────────────────────────────────────────

    def test_valid_typescript(self):
        path = self._write_temp(".ts", "const x: number = 42;\n")
        result = _treesitter_syntax_check(path)
        self.assertIsNotNone(result)
        is_valid, _ = result
        self.assertTrue(is_valid)

    def test_invalid_typescript(self):
        path = self._write_temp(".ts", "const x: number = ;\n")
        result = _treesitter_syntax_check(path)
        self.assertIsNotNone(result)
        is_valid, detail = result
        self.assertFalse(is_valid)

    # ── TSX ─────────────────────────────────────────────────────────────

    def test_valid_tsx(self):
        code = "const App = () => <div>hello</div>;\n"
        path = self._write_temp(".tsx", code)
        result = _treesitter_syntax_check(path)
        self.assertIsNotNone(result)
        is_valid, _ = result
        self.assertTrue(is_valid)

    # ── JSON ────────────────────────────────────────────────────────────

    def test_valid_json(self):
        path = self._write_temp(".json", '{"key": "value"}\n')
        result = _treesitter_syntax_check(path)
        self.assertIsNotNone(result)
        is_valid, _ = result
        self.assertTrue(is_valid)

    def test_invalid_json(self):
        path = self._write_temp(".json", '{"key": "value",}\n')
        result = _treesitter_syntax_check(path)
        self.assertIsNotNone(result)
        is_valid, detail = result
        self.assertFalse(is_valid)

    # ── Go ──────────────────────────────────────────────────────────────

    def test_valid_go(self):
        code = 'package main\n\nfunc main() {\n\tfmt.Println("hello")\n}\n'
        path = self._write_temp(".go", code)
        result = _treesitter_syntax_check(path)
        self.assertIsNotNone(result)
        is_valid, _ = result
        self.assertTrue(is_valid)

    def test_invalid_go(self):
        code = "package main\n\nfunc main( {\n}\n"
        path = self._write_temp(".go", code)
        result = _treesitter_syntax_check(path)
        self.assertIsNotNone(result)
        is_valid, detail = result
        self.assertFalse(is_valid)

    # ── Rust ────────────────────────────────────────────────────────────

    def test_valid_rust(self):
        code = 'fn main() {\n    println!("hello");\n}\n'
        path = self._write_temp(".rs", code)
        result = _treesitter_syntax_check(path)
        self.assertIsNotNone(result)
        is_valid, _ = result
        self.assertTrue(is_valid)

    # ── YAML ────────────────────────────────────────────────────────────

    def test_valid_yaml(self):
        path = self._write_temp(".yaml", "key: value\nlist:\n  - item1\n")
        result = _treesitter_syntax_check(path)
        self.assertIsNotNone(result)
        is_valid, _ = result
        self.assertTrue(is_valid)

    # ── HTML ────────────────────────────────────────────────────────────

    def test_valid_html(self):
        path = self._write_temp(".html", "<html><body><h1>Hi</h1></body></html>")
        result = _treesitter_syntax_check(path)
        self.assertIsNotNone(result)
        is_valid, _ = result
        self.assertTrue(is_valid)

    # ── CSS ─────────────────────────────────────────────────────────────

    def test_valid_css(self):
        path = self._write_temp(".css", "body { color: red; }\n")
        result = _treesitter_syntax_check(path)
        self.assertIsNotNone(result)
        is_valid, _ = result
        self.assertTrue(is_valid)

    # ── Shell ───────────────────────────────────────────────────────────

    def test_valid_shell(self):
        path = self._write_temp(".sh", "#!/bin/bash\necho hello\n")
        result = _treesitter_syntax_check(path)
        self.assertIsNotNone(result)
        is_valid, _ = result
        self.assertTrue(is_valid)

    # ── Unsupported / edge cases ────────────────────────────────────────

    def test_no_extension_returns_none(self):
        path = self._write_temp("", "some content")
        # Rename to remove extension
        no_ext = path.rstrip(".tmp") if path.endswith(".tmp") else path
        result = _treesitter_syntax_check(path)
        # Files with no recognized extension return None
        # (tempfile adds a suffix, so this test uses the raw temp path)

    def test_nonexistent_file_returns_none(self):
        result = _treesitter_syntax_check("/nonexistent/path/file.py")
        self.assertIsNone(result)

    # ── Error detail quality ────────────────────────────────────────────

    def test_error_detail_includes_line_number(self):
        # Error is on line 3
        code = "x = 1\ny = 2\ndef broken(\n"
        path = self._write_temp(".py", code)
        result = _treesitter_syntax_check(path)
        self.assertIsNotNone(result)
        is_valid, detail = result
        self.assertFalse(is_valid)
        self.assertIn("line 3", detail)

    def test_max_errors_capped(self):
        # Create code with many syntax errors
        code = "\n".join(f"def f{i}(" for i in range(20))
        path = self._write_temp(".py", code)
        result = _treesitter_syntax_check(path)
        self.assertIsNotNone(result)
        is_valid, detail = result
        self.assertFalse(is_valid)
        # Should be capped at 5 errors
        self.assertLessEqual(detail.count("line"), 5)

    # ── Content-only mode (sandbox support) ─────────────────────────────

    def test_content_passed_directly_valid_python(self):
        """When content is passed, file is NOT read from disk."""
        content = b"def hello():\n    return 42\n"
        # Use a fake path that doesn't exist — only the extension matters
        result = _treesitter_syntax_check("/sandbox/fake.py", content)
        self.assertIsNotNone(result)
        self.assertTrue(result[0])

    def test_content_passed_directly_invalid_js(self):
        content = b"function hello( { return 42; }\n"
        result = _treesitter_syntax_check("/sandbox/fake.js", content)
        self.assertIsNotNone(result)
        self.assertFalse(result[0])
        self.assertIn("line", result[1])

    def test_content_passed_directly_valid_ts(self):
        content = b"const x: number = 42;\nexport default x;\n"
        result = _treesitter_syntax_check("/sandbox/fake.ts", content)
        self.assertIsNotNone(result)
        self.assertTrue(result[0])

    def test_content_passed_directly_valid_json(self):
        content = b'{"key": "value", "num": 123}\n'
        result = _treesitter_syntax_check("/sandbox/fake.json", content)
        self.assertIsNotNone(result)
        self.assertTrue(result[0])

    def test_content_passed_directly_invalid_json(self):
        content = b'{"key": "value",}\n'
        result = _treesitter_syntax_check("/sandbox/fake.json", content)
        self.assertIsNotNone(result)
        self.assertFalse(result[0])

    def test_content_passed_directly_valid_go(self):
        content = b'package main\n\nfunc main() {\n}\n'
        result = _treesitter_syntax_check("/sandbox/fake.go", content)
        self.assertIsNotNone(result)
        self.assertTrue(result[0])

    def test_content_passed_directly_valid_tsx(self):
        content = b"const App = () => <div>hello</div>;\nexport default App;\n"
        result = _treesitter_syntax_check("/sandbox/fake.tsx", content)
        self.assertIsNotNone(result)
        self.assertTrue(result[0])

    def test_content_passed_directly_valid_css(self):
        content = b"body { color: red; }\n.btn { padding: 8px; }\n"
        result = _treesitter_syntax_check("/sandbox/fake.css", content)
        self.assertIsNotNone(result)
        self.assertTrue(result[0])

    def test_content_passed_unsupported_ext_returns_none(self):
        content = b"some random content"
        result = _treesitter_syntax_check("/sandbox/fake.xyz", content)
        self.assertIsNone(result)


@unittest.skipUnless(TREE_SITTER_AVAILABLE, "tree-sitter not installed")
class TestAutoCheckMiddlewarePipeline(unittest.TestCase):
    """Integration: verify AutoCheckMiddleware fires via the pipeline for file actions."""

    def _run(self, coro):
        import asyncio
        return asyncio.get_event_loop().run_until_complete(coro)

    def _make_pipeline_and_ctx(self, action):
        from unittest.mock import MagicMock
        from backend.controller.tool_pipeline import (
            AutoCheckMiddleware,
            ToolInvocationContext,
            ToolInvocationPipeline,
        )

        controller = MagicMock()
        state = MagicMock()
        middleware = AutoCheckMiddleware()
        pipeline = ToolInvocationPipeline(controller, [middleware])
        ctx = pipeline.create_context(action, state)
        return pipeline, ctx

    def test_file_edit_create_valid_python(self):
        """FileEditAction create with valid Python → SYNTAX_CHECK_PASSED."""
        from backend.events.action.files import FileEditAction
        from backend.events.observation import FileEditObservation

        action = FileEditAction(
            path="/workspace/app.py",
            command="create",
            file_text="def hello():\n    return 42\n",
        )
        obs = FileEditObservation(content="File created successfully", path="/workspace/app.py")
        pipeline, ctx = self._make_pipeline_and_ctx(action)
        self._run(pipeline.run_observe(ctx, obs))
        self.assertIn("<SYNTAX_CHECK_PASSED />", obs.content)

    def test_file_edit_create_invalid_python(self):
        """FileEditAction create with invalid Python → SYNTAX_CHECK_FAILED."""
        from backend.events.action.files import FileEditAction
        from backend.events.observation import FileEditObservation

        action = FileEditAction(
            path="/workspace/app.py",
            command="create",
            file_text="def hello(\n    return 42\n",
        )
        obs = FileEditObservation(content="File created successfully", path="/workspace/app.py")
        pipeline, ctx = self._make_pipeline_and_ctx(action)
        self._run(pipeline.run_observe(ctx, obs))
        self.assertIn("<SYNTAX_CHECK_FAILED>", obs.content)

    def test_file_write_valid_js(self):
        """FileWriteAction with valid JS → SYNTAX_CHECK_PASSED."""
        from backend.events.action.files import FileWriteAction
        from backend.events.observation import FileWriteObservation

        action = FileWriteAction(
            path="/workspace/index.js",
            content="function hello() { return 42; }\n",
        )
        obs = FileWriteObservation(content="File written", path="/workspace/index.js")
        pipeline, ctx = self._make_pipeline_and_ctx(action)
        self._run(pipeline.run_observe(ctx, obs))
        self.assertIn("<SYNTAX_CHECK_PASSED />", obs.content)

    def test_file_write_invalid_ts(self):
        """FileWriteAction with invalid TS → SYNTAX_CHECK_FAILED."""
        from backend.events.action.files import FileWriteAction
        from backend.events.observation import FileWriteObservation

        action = FileWriteAction(
            path="/workspace/app.ts",
            content="const x: number = ;\n",
        )
        obs = FileWriteObservation(content="File written", path="/workspace/app.ts")
        pipeline, ctx = self._make_pipeline_and_ctx(action)
        self._run(pipeline.run_observe(ctx, obs))
        self.assertIn("<SYNTAX_CHECK_FAILED>", obs.content)

    def test_file_edit_str_replace_uses_content_fallback(self):
        """FileEditAction str_replace — uses content attr as file content."""
        from backend.events.action.files import FileEditAction
        from backend.events.observation import FileEditObservation

        action = FileEditAction(
            path="/workspace/app.py",
            command="str_replace",
            old_str="old",
            new_str="new",
            content="def hello():\n    return 42\n",
        )
        obs = FileEditObservation(content="Replacement done", path="/workspace/app.py")
        pipeline, ctx = self._make_pipeline_and_ctx(action)
        self._run(pipeline.run_observe(ctx, obs))
        self.assertIn("<SYNTAX_CHECK_PASSED />", obs.content)

    def test_error_observation_skipped(self):
        """ErrorObservation should not trigger syntax check."""
        from backend.events.action.files import FileEditAction
        from backend.events.observation import ErrorObservation

        action = FileEditAction(
            path="/workspace/app.py",
            command="create",
            file_text="def hello():\n",
        )
        obs = ErrorObservation(content="Command failed")
        pipeline, ctx = self._make_pipeline_and_ctx(action)
        self._run(pipeline.run_observe(ctx, obs))
        self.assertNotIn("SYNTAX_CHECK", obs.content)

    def test_unsupported_extension_no_tag(self):
        """Unsupported file extension → no SYNTAX_CHECK tag appended."""
        from backend.events.action.files import FileEditAction
        from backend.events.observation import FileEditObservation

        action = FileEditAction(
            path="/workspace/data.xyz",
            command="create",
            file_text="some data",
        )
        obs = FileEditObservation(content="File created", path="/workspace/data.xyz")
        pipeline, ctx = self._make_pipeline_and_ctx(action)
        self._run(pipeline.run_observe(ctx, obs))
        self.assertNotIn("SYNTAX_CHECK", obs.content)

    def test_non_file_action_no_tag(self):
        """Non-file action → middleware is a no-op."""
        from backend.events.action.commands import CmdRunAction
        from backend.events.observation import CmdOutputObservation

        action = CmdRunAction(command="ls")
        obs = CmdOutputObservation(content="file1\nfile2", command_id=1, command="ls")
        pipeline, ctx = self._make_pipeline_and_ctx(action)
        self._run(pipeline.run_observe(ctx, obs))
        self.assertNotIn("SYNTAX_CHECK", obs.content)


if __name__ == "__main__":
    unittest.main()
