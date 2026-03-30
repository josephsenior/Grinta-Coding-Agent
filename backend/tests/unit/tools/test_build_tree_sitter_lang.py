"""Comprehensive tests for Tree-sitter language builder tool.

Tests grammar building, platform-specific output, and argument parsing.
"""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import tempfile
import types

from backend.tools.tools.build_tree_sitter_lang import _default_out_file, main


def _make_tree_sitter_module():
    """Create a fake tree_sitter module with a Language mock."""
    mod = types.ModuleType("tree_sitter")
    mod.Language = MagicMock()  # type: ignore[attr-defined]
    return mod


class TestDefaultOutFile(unittest.TestCase):
    """Tests for _default_out_file platform-specific extension logic."""

    def test_windows_platform_returns_dll(self) -> None:
        out_base = Path("/path/to/my-langs")
        with patch.dict("os.environ", {"APP_PLATFORM": "win32"}):
            result = _default_out_file(out_base)
        self.assertTrue(result.endswith(".dll"))

    def test_windows_64_platform_returns_dll(self) -> None:
        out_base = Path("c:\\grammars\\build")
        with patch.dict("os.environ", {"APP_PLATFORM": "win_amd64"}):
            result = _default_out_file(out_base)
        self.assertTrue(result.endswith(".dll"))

    def test_darwin_platform_returns_dylib(self) -> None:
        out_base = Path("/usr/local/grammars/lang")
        with patch.dict("os.environ", {"APP_PLATFORM": "darwin"}):
            result = _default_out_file(out_base)
        self.assertTrue(result.endswith(".dylib"))

    def test_linux_platform_returns_so(self) -> None:
        out_base = Path("/opt/grammars/parser")
        with patch.dict("os.environ", {"APP_PLATFORM": "linux"}):
            result = _default_out_file(out_base)
        self.assertTrue(result.endswith(".so"))

    def test_fallback_to_sys_platform(self) -> None:
        out_base = Path("/tmp/build")
        env = dict(__import__("os").environ)
        env.pop("APP_PLATFORM", None)
        with patch.dict("os.environ", env, clear=True):
            with patch("backend.tools.tools.build_tree_sitter_lang.sys") as mock_sys:
                mock_sys.platform = "linux"
                result = _default_out_file(out_base)
        self.assertTrue(result.endswith(".so"))

    def test_unknown_platform_defaults_to_so(self) -> None:
        out_base = Path("/opt/lib")
        with patch.dict("os.environ", {"APP_PLATFORM": "freebsd"}):
            result = _default_out_file(out_base)
        self.assertTrue(result.endswith(".so"))


class TestMainFunction(unittest.TestCase):
    """Tests for main() build orchestration."""

    def test_import_error_returns_exit_code_2(self) -> None:
        """tree_sitter not importable → exit code 2."""
        with patch.dict("sys.modules", {"tree_sitter": None}):
            result = main(["--grammar-dir", str(Path(tempfile.gettempdir()))])
        self.assertEqual(result, 2)

    def test_no_grammars_found_returns_1(self) -> None:
        fake_ts = _make_tree_sitter_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("sys.modules", {"tree_sitter": fake_ts}):
                result = main(
                    [
                        "--grammar-dir",
                        tmpdir,
                        "--lang",
                        "nonexistent-grammar",
                    ]
                )
        self.assertEqual(result, 1)

    def test_successful_build_returns_0(self) -> None:
        fake_ts = _make_tree_sitter_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "tree-sitter-python").mkdir()
            with patch.dict("sys.modules", {"tree_sitter": fake_ts}):
                result = main(
                    [
                        "--grammar-dir",
                        tmpdir,
                        "--lang",
                        "tree-sitter-python",
                        "--out",
                        str(Path(tmpdir) / "output"),
                    ]
                )
        self.assertEqual(result, 0)
        fake_ts.Language.build_library.assert_called_once()

    def test_default_output_location(self) -> None:
        fake_ts = _make_tree_sitter_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "tree-sitter-python").mkdir()
            with patch.dict("sys.modules", {"tree_sitter": fake_ts}):
                with patch.dict("os.environ", {"APP_PLATFORM": "linux"}):
                    main(["--grammar-dir", tmpdir, "--lang", "tree-sitter-python"])
            call_args = fake_ts.Language.build_library.call_args
            output_path = call_args[0][0]
            self.assertTrue(output_path.endswith("my-langs.so"))

    def test_multiple_grammars(self) -> None:
        fake_ts = _make_tree_sitter_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "tree-sitter-python").mkdir()
            (Path(tmpdir) / "tree-sitter-javascript").mkdir()
            with patch.dict("sys.modules", {"tree_sitter": fake_ts}):
                result = main(
                    [
                        "--grammar-dir",
                        tmpdir,
                        "--lang",
                        "tree-sitter-python",
                        "--lang",
                        "tree-sitter-javascript",
                    ]
                )
        self.assertEqual(result, 0)
        call_args = fake_ts.Language.build_library.call_args
        grammars = call_args[0][1]
        # default=["tree-sitter-python"] + append "tree-sitter-python" + append
        # "tree-sitter-javascript" → 3 entries (default is included)
        self.assertEqual(len(grammars), 3)

    def test_warns_on_missing_grammar(self) -> None:
        fake_ts = _make_tree_sitter_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "tree-sitter-python").mkdir()
            with patch.dict("sys.modules", {"tree_sitter": fake_ts}):
                # Should still succeed (one grammar found)
                result = main(
                    [
                        "--grammar-dir",
                        tmpdir,
                        "--lang",
                        "tree-sitter-python",
                        "--lang",
                        "tree-sitter-nonexistent",
                    ]
                )
        self.assertEqual(result, 0)

    def test_custom_output_path(self) -> None:
        fake_ts = _make_tree_sitter_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "tree-sitter-python").mkdir()
            custom_out = Path(tmpdir) / "custom" / "location"
            custom_out.parent.mkdir(parents=True, exist_ok=True)
            with patch.dict("sys.modules", {"tree_sitter": fake_ts}):
                with patch.dict("os.environ", {"APP_PLATFORM": "darwin"}):
                    main(
                        [
                            "--grammar-dir",
                            tmpdir,
                            "--lang",
                            "tree-sitter-python",
                            "--out",
                            str(custom_out),
                        ]
                    )
            call_args = fake_ts.Language.build_library.call_args
            output_path = call_args[0][0]
            self.assertIn("custom", output_path)
            self.assertTrue(output_path.endswith(".dylib"))

    def test_default_lang_is_python(self) -> None:
        fake_ts = _make_tree_sitter_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "tree-sitter-python").mkdir()
            with patch.dict("sys.modules", {"tree_sitter": fake_ts}):
                main(["--grammar-dir", tmpdir])
            call_args = fake_ts.Language.build_library.call_args
            grammars = call_args[0][1]
            self.assertEqual(len(grammars), 1)
            self.assertIn("tree-sitter-python", grammars[0])


class TestCommandLineIntegration(unittest.TestCase):
    """Integration tests for command-line interface."""

    def test_help_message_available(self) -> None:
        import io

        with patch("sys.stdout", new=io.StringIO()):
            with patch("sys.stderr", new=io.StringIO()):
                try:
                    main(["--help"])
                except SystemExit as e:
                    self.assertEqual(e.code, 0)


if __name__ == "__main__":
    unittest.main()
