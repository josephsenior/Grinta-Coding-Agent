from __future__ import annotations

from backend.engine.tools.analyze_project_structure import (
    build_analyze_project_structure_action,
)


def test_analyze_project_structure_tree(tmp_path) -> None:
    # Build some nested structure
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'main.py').write_text("print('hello')", encoding='utf-8')

    action = build_analyze_project_structure_action(
        {'command': 'tree', 'path': str(tmp_path)}
    )

    assert 'src/main.py' in action.thought
    assert '<dir> src' in action.thought


def test_analyze_project_structure_imports(tmp_path) -> None:
    test_file = tmp_path / 'module.py'
    test_file.write_text('import os\nfrom pathlib import Path\n', encoding='utf-8')

    action = build_analyze_project_structure_action(
        {'command': 'imports', 'path': str(test_file)}
    )

    assert 'import os' in action.thought
    assert 'from pathlib import Path' in action.thought


def test_analyze_project_structure_symbols(tmp_path) -> None:
    test_file = tmp_path / 'module.py'
    test_file.write_text(
        'class MyClass:\n    pass\n\ndef my_func():\n    pass\n\nMY_VAR = 1\n',
        encoding='utf-8',
    )

    action = build_analyze_project_structure_action(
        {'command': 'symbols', 'path': str(test_file)}
    )

    assert 'class MyClass:' in action.thought
    assert 'def my_func():' in action.thought
    assert 'MY_VAR =' in action.thought


def test_analyze_project_structure_file_outline_python(tmp_path) -> None:
    test_file = tmp_path / 'big.py'
    test_file.write_text(
        'class Foo:\n'
        '    def bar(self, x: int) -> str:\n'
        '        return str(x)\n\n'
        'def top() -> None:\n'
        '    pass\n',
        encoding='utf-8',
    )
    action = build_analyze_project_structure_action(
        {
            'command': 'file_outline',
            'path': str(test_file),
        }
    )
    assert 'FILE OUTLINE' in action.thought
    assert 'class Foo' in action.thought
    assert 'def bar' in action.thought
    assert 'def top' in action.thought
