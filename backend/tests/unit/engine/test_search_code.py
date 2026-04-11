from __future__ import annotations

import os
import shutil
from backend.engine.tools.search_code import build_search_code_action

class TestBuildSearchCodeAction:
    def test_search_mode_with_python_fallback(self, tmp_path, monkeypatch) -> None:
        # Prevent ripgrep from being found
        monkeypatch.setattr(shutil, 'which', lambda x: None)
        
        # Create test files
        test_file = tmp_path / "test.py"
        test_file.write_text("def my_func():\n    print('hello world')\n", encoding="utf-8")
        
        ignored_dir = tmp_path / ".mypy_cache"
        ignored_dir.mkdir()
        ignored_file = ignored_dir / "hidden.py"
        ignored_file.write_text("print('hello world')\n", encoding="utf-8")

        action = build_search_code_action(pattern='hello world', path=str(tmp_path))
        
        assert "hello world" in action.thought
        assert "test.py" in action.thought
        assert ".mypy_cache" not in action.thought

    def test_file_discovery_mode_with_python_fallback(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(shutil, 'which', lambda x: None)
        
        # Create test files
        (tmp_path / "test1.py").touch()
        (tmp_path / "test2.js").touch()
        
        action = build_search_code_action(file_pattern='*.py', path=str(tmp_path))
        
        assert "test1.py" in action.thought
        assert "test2.js" not in action.thought
