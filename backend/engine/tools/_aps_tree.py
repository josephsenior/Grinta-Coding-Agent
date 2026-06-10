"""Tree and symbols modes for the analyze_project_structure tool.

Contains helpers and builders for the ``tree`` and ``symbols`` modes
of the analyze_project_structure tool. The two are grouped because
``_extract_ast_summary`` (symbols helper) is also used to annotate
files in the tree output.

Extracted from ``backend.engine.tools.analyze_project_structure`` to
keep that module focused on the public tool API.
"""

from __future__ import annotations

import ast
import os
import re
from typing import Any

from backend.engine.tools._aps_shared import _diag, _run_command
from backend.engine.tools.ignore_filter import (
    get_ignore_spec,
    is_ignored_file,
    prune_ignored_dirs,
)

_TREE_FILE_PRIORITY = {
    'README.md': 0,
    'pyproject.toml': 1,
    'package.json': 2,
    'requirements.txt': 3,
    'Dockerfile': 4,
    'Makefile': 5,
    '.gitignore': 6,
}


def _tree_relative_depth(relative_path: str) -> int:
    if relative_path in ('', '.'):
        return 0
    return relative_path.count(os.sep) + 1


def _sorted_tree_files(filenames: list[str]) -> list[str]:
    return sorted(
        filenames,
        key=lambda name: (0, _TREE_FILE_PRIORITY[name])
        if name in _TREE_FILE_PRIORITY
        else (1, name.lower()),
    )


def _class_outline_line(node: ast.ClassDef, methods: list[str]) -> str:
    if methods:
        head = ', '.join(methods[:3])
        if len(methods) > 3:
            head = f'{head}...'
        return f'      class {node.name} (methods: {head})'
    return f'      class {node.name}'


def _extract_ast_summary(filepath: str) -> list[str]:
    if not filepath.endswith('.py'):
        return []

    try:
        with open(filepath, encoding='utf-8') as file_handle:
            content = file_handle.read()
        tree = ast.parse(content)
    except Exception:
        return []

    symbols: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = [
                method.name
                for method in node.body
                if isinstance(method, ast.FunctionDef)
                and not method.name.startswith('__')
            ]
            symbols.append(_class_outline_line(node, methods))
            continue
        if isinstance(node, ast.FunctionDef) and not node.name.startswith('_'):
            symbols.append(f'      def {node.name}')
    return symbols


def _git_files_for_tree(cwd: str) -> set[str]:
    try:
        result = _run_command(
            ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
            cwd=cwd,
            process_timeout=10.0,
        )
        if result.returncode != 0:
            return set()
        return {item for item in result.stdout.split('\0') if item}
    except Exception:
        return set()


def _tree_child_relative_path(relative_root: str, dirname: str) -> str:
    if relative_root in ('', '.'):
        return dirname
    return os.path.join(relative_root, dirname)


def _tree_valid_filenames(
    *,
    root: str,
    current_root: str,
    filenames: list[str],
    use_git: bool,
    git_files: set[str],
    spec: Any,
) -> list[str]:
    if use_git:
        valid_filenames: list[str] = []
        for filename in _sorted_tree_files(filenames):
            rel_file = os.path.relpath(
                os.path.join(current_root, filename),
                root,
            ).replace(os.sep, '/')
            if rel_file in git_files:
                valid_filenames.append(filename)
        return valid_filenames
    return [
        filename
        for filename in _sorted_tree_files(filenames)
        if not is_ignored_file(root, current_root, filename, spec)
    ]


def _append_tree_file_lines(
    lines: list[str],
    *,
    root: str,
    current_root: str,
    relative_root: str,
    valid_filenames: list[str],
    max_files_per_dir: int,
) -> None:
    shown_files = valid_filenames[:max_files_per_dir]
    hidden_files = len(valid_filenames) - len(shown_files)

    for filename in shown_files:
        full_path = os.path.join(current_root, filename)
        relative_path = os.path.relpath(full_path, root).replace(os.sep, '/')
        lines.append(f'  {relative_path}')
        lines.extend(_extract_ast_summary(full_path))

    if hidden_files > 0:
        hint_path = relative_root.replace(os.sep, '/') or '.'
        lines.append(
            f"  ... and {hidden_files} more files inside {relative_root or '.'} hidden. Use path='{hint_path}' to explore."
        )


def _build_tree_action(path: str, depth: int) -> str:
    """Directory tree with file sizes, respecting .gitignore."""
    depth = max(1, min(depth, 5))
    root = os.path.abspath(path)
    spec = get_ignore_spec(root)

    if not os.path.exists(root):
        return f'[ANALYZE_PROJECT_STRUCTURE] Path not found: {path}'

    git_files = _git_files_for_tree(root)
    use_git = len(git_files) > 0

    lines = [f'[ANALYZE_PROJECT_STRUCTURE] Mapping project semantic structure ({path})']
    lines.append(
        'Note: Large directories are truncated. Showing key classes/functions for Python files.'
    )
    lines.append(
        'Recovery hint: do not repeat this tool with identical arguments; pick a specific subpath or run a concrete test/build/runtime command next.'
    )

    max_files_per_dir = 50
    emitted_dirs: set[str] = set()

    def add_dir_header(relative_dir: str) -> None:
        if relative_dir in ('', '.'):
            return
        key = relative_dir.replace(os.sep, '/')
        if key in emitted_dirs:
            return
        lines.append('<dir> ' + key)
        emitted_dirs.add(key)

    for current_root, dirnames, filenames in os.walk(root):
        relative_root = os.path.relpath(current_root, root)
        current_depth = _tree_relative_depth(relative_root)

        prune_ignored_dirs(root, current_root, dirnames, spec)
        if '.git' in dirnames:
            dirnames.remove('.git')

        dirnames.sort()

        if current_depth < depth:
            for dirname in dirnames:
                rel_child = _tree_child_relative_path(relative_root, dirname)
                add_dir_header(rel_child)

        if current_depth > depth:
            add_dir_header(relative_root)
            dirnames[:] = []
            continue

        add_dir_header(relative_root)
        valid_filenames = _tree_valid_filenames(
            root=root,
            current_root=current_root,
            filenames=filenames,
            use_git=use_git,
            git_files=git_files,
            spec=spec,
        )
        _append_tree_file_lines(
            lines,
            root=root,
            current_root=current_root,
            relative_root=relative_root,
            valid_filenames=valid_filenames,
            max_files_per_dir=max_files_per_dir,
        )

    return '\n'.join(lines)


def _build_symbols_action(path: str) -> str:
    """List classes, functions, and top-level assignments in a file."""
    out = [f'=== SYMBOLS IN {os.path.basename(path)} ===']
    if os.path.isfile(path):
        sym_re = re.compile(r'^(class |def |async def |[A-Z_][A-Z_0-9]* *=)')
        try:
            with open(path, encoding='utf-8', errors='ignore') as f:
                count = 0
                for i, line in enumerate(f, 1):
                    if sym_re.match(line):
                        out.append(f'{i}:{line.rstrip()}')
                        count += 1
                        if count >= 100:
                            break
                if count == 0:
                    out.append(
                        _diag(
                            reason='no top-level class/def/CONST symbols matched',
                            command='symbols',
                            params={'path': path},
                            next_steps=[
                                'Try command=file_outline for AST-level signatures.',
                                'The file may be plain data or have non-standard formatting.',
                            ],
                        )
                    )
        except Exception as e:
            out.append(f'(error reading file: {e})')
    else:
        out.append(
            _diag(
                reason='file not found at given path',
                command='symbols',
                params={'path': path},
                next_steps=[
                    'Pass a path relative to the workspace root.',
                    'Run command=tree first to discover the actual file location.',
                ],
            )
        )
    return '\n'.join(out)
