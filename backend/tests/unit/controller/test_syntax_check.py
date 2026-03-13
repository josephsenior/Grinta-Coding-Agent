"""Tests for _get_syntax_check_cmd — JS/TS bypass fix."""

import unittest

from backend.controller.tool_pipeline import _get_syntax_check_cmd


class TestGetSyntaxCheckCmd(unittest.TestCase):
    """Verify syntax check returns None for JS/TS and valid cmd for Python."""

    def test_python_file(self):
        result = _get_syntax_check_cmd("/workspace/app.py")
        self.assertEqual(result, ["python", "-m", "py_compile", "/workspace/app.py"])

    def test_js_file_returns_none(self):
        self.assertIsNone(_get_syntax_check_cmd("/workspace/src/index.js"))

    def test_jsx_file_returns_none(self):
        self.assertIsNone(_get_syntax_check_cmd("/workspace/src/App.jsx"))

    def test_ts_file_returns_none(self):
        self.assertIsNone(_get_syntax_check_cmd("/workspace/src/utils.ts"))

    def test_tsx_file_returns_none(self):
        self.assertIsNone(_get_syntax_check_cmd("/workspace/src/page.tsx"))

    def test_mjs_file_returns_none(self):
        self.assertIsNone(_get_syntax_check_cmd("/workspace/config.mjs"))

    def test_css_file_returns_none(self):
        self.assertIsNone(_get_syntax_check_cmd("/workspace/styles.css"))

    def test_json_file_returns_none(self):
        self.assertIsNone(_get_syntax_check_cmd("/workspace/package.json"))

    def test_uppercase_py_extension(self):
        result = _get_syntax_check_cmd("/workspace/app.PY")
        self.assertEqual(result, ["python", "-m", "py_compile", "/workspace/app.PY"])

    def test_no_extension_returns_none(self):
        self.assertIsNone(_get_syntax_check_cmd("/workspace/Makefile"))

    def test_nextauth_bracket_path(self):
        self.assertIsNone(
            _get_syntax_check_cmd("/workspace/src/app/api/auth/[...nextauth]/route.ts")
        )


if __name__ == "__main__":
    unittest.main()
