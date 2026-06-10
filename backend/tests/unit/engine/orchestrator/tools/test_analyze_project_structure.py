from __future__ import annotations

from backend.engine.tools.analyze_project_structure import (
    build_analyze_project_structure_action,
    execute_analyze_project_structure,
)


def test_analyze_project_structure_tree(tmp_path) -> None:
    # Build some nested structure
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'main.py').write_text("print('hello')", encoding='utf-8')

    action = build_analyze_project_structure_action(
        {'command': 'tree', 'path': str(tmp_path)}
    )
    obs = execute_analyze_project_structure(action)

    assert action.command == 'tree'
    assert 'src/main.py' in obs.content
    assert '<dir> src' in obs.content


def test_analyze_project_structure_imports(tmp_path) -> None:
    test_file = tmp_path / 'module.py'
    test_file.write_text('import os\nfrom pathlib import Path\n', encoding='utf-8')

    action = build_analyze_project_structure_action(
        {'command': 'imports', 'path': str(test_file)}
    )
    obs = execute_analyze_project_structure(action)

    assert 'import os' in obs.content
    assert 'from pathlib import Path' in obs.content


def test_analyze_project_structure_symbols(tmp_path) -> None:
    test_file = tmp_path / 'module.py'
    test_file.write_text(
        'class MyClass:\n    pass\n\ndef my_func():\n    pass\n\nMY_VAR = 1\n',
        encoding='utf-8',
    )

    action = build_analyze_project_structure_action(
        {'command': 'symbols', 'path': str(test_file)}
    )
    obs = execute_analyze_project_structure(action)

    assert 'class MyClass:' in obs.content
    assert 'def my_func():' in obs.content
    assert 'MY_VAR =' in obs.content


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
    obs = execute_analyze_project_structure(action)
    assert 'FILE OUTLINE' in obs.content
    assert 'class Foo' in obs.content
    assert 'def bar' in obs.content
    assert 'def top' in obs.content


# --------------------------------------------------------------------------- #
# Diagnostic-empty contract: when a mode has nothing to return it must emit a
# structured "[ANALYZE_PROJECT_STRUCTURE] no_results" block, never an empty
# string. The agent uses these to recover instead of looping blindly.
# --------------------------------------------------------------------------- #


def test_analyze_project_structure_callers_missing_symbol_emits_diag() -> None:
    action = build_analyze_project_structure_action({'command': 'callers'})
    obs = execute_analyze_project_structure(action)
    assert '[ANALYZE_PROJECT_STRUCTURE] no_results' in obs.content
    assert "missing required parameter 'symbol'" in obs.content
    assert 'next_steps:' in obs.content


def test_analyze_project_structure_unknown_command_emits_diag() -> None:
    action = build_analyze_project_structure_action(
        {'command': 'definitely_not_a_real_command'}
    )
    obs = execute_analyze_project_structure(action)
    assert '[ANALYZE_PROJECT_STRUCTURE] no_results' in obs.content
    assert 'unknown command' in obs.content


# --------------------------------------------------------------------------- #
# Dependencies mode (transitive import walk).
# --------------------------------------------------------------------------- #


def test_analyze_project_structure_dependencies_missing_anchor(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)
    action = build_analyze_project_structure_action(
        {'command': 'dependencies', 'path': 'does_not_exist.py'}
    )
    obs = execute_analyze_project_structure(action)
    assert '[ANALYZE_PROJECT_STRUCTURE] no_results' in obs.content
    assert 'anchor file not found' in obs.content


def test_analyze_project_structure_dependencies_invalid_direction(
    monkeypatch, tmp_path
) -> None:
    f = tmp_path / 'a.py'
    f.write_text('x = 1\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    action = build_analyze_project_structure_action(
        {'command': 'dependencies', 'path': 'a.py', 'direction': 'sideways'}
    )
    obs = execute_analyze_project_structure(action)
    assert '[ANALYZE_PROJECT_STRUCTURE] no_results' in obs.content
    assert 'invalid direction' in obs.content


def test_analyze_project_structure_dependencies_downstream(
    monkeypatch, tmp_path
) -> None:
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    (pkg / 'leaf.py').write_text('VALUE = 1\n', encoding='utf-8')
    (pkg / 'mid.py').write_text('from pkg import leaf\n', encoding='utf-8')
    (pkg / 'root.py').write_text('from pkg import mid\n', encoding='utf-8')

    monkeypatch.chdir(tmp_path)
    action = build_analyze_project_structure_action(
        {
            'command': 'dependencies',
            'path': 'pkg/root.py',
            'direction': 'downstream',
            'depth': 3,
        }
    )
    obs = execute_analyze_project_structure(action)
    assert '=== DEPENDENCY TREE ===' in obs.content
    assert 'pkg/root.py' in obs.content
    assert 'pkg/mid.py' in obs.content
    assert 'pkg/leaf.py' in obs.content
    # Sidecar JSON must be present.
    assert '=== EDGES (json) ===' in obs.content


def test_analyze_project_structure_dependencies_cycle_safe(
    monkeypatch, tmp_path
) -> None:
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    # a imports b; b imports a — classic cycle.
    (pkg / 'a.py').write_text('from pkg import b\n', encoding='utf-8')
    (pkg / 'b.py').write_text('from pkg import a\n', encoding='utf-8')

    monkeypatch.chdir(tmp_path)
    action = build_analyze_project_structure_action(
        {
            'command': 'dependencies',
            'path': 'pkg/a.py',
            'direction': 'downstream',
            'depth': 4,
        }
    )
    obs = execute_analyze_project_structure(action)
    # Cycle marker must appear instead of recursing forever.
    assert '(↺)' in obs.content
    assert 'pkg/b.py' in obs.content


def test_analyze_project_structure_dependencies_no_edges_emits_diag(
    monkeypatch, tmp_path
) -> None:
    f = tmp_path / 'standalone.py'
    f.write_text('x = 1\n', encoding='utf-8')  # no imports of in-workspace modules
    monkeypatch.chdir(tmp_path)
    action = build_analyze_project_structure_action(
        {'command': 'dependencies', 'path': 'standalone.py', 'direction': 'downstream'}
    )
    obs = execute_analyze_project_structure(action)
    assert '=== DEPENDENCY TREE ===' in obs.content
    assert '[ANALYZE_PROJECT_STRUCTURE] no_results' in obs.content
    assert 'no dependency edges found' in obs.content
