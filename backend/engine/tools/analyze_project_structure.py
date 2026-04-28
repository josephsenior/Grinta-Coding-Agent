"""Project Map tool — gives the LLM a quick structural overview of the workspace.

Provides directory tree, import graph, symbol index, and recently modified files
in a single call, preventing cross-file breakage by surfacing dependencies the
LLM wouldn't otherwise know about.
"""

from __future__ import annotations

from collections.abc import Callable
import os
import re
import subprocess
from pathlib import Path

from backend.engine.tools.ignore_filter import (
    get_ignore_spec,
    is_ignored_file,
    prune_ignored_dirs,
)
from backend.ledger.action import AgentThinkAction

ANALYZE_PROJECT_STRUCTURE_TOOL_NAME = 'analyze_project_structure'


def create_analyze_project_structure_tool() -> dict:
    """Return the OpenAI function-calling tool definition for analyze_project_structure."""
    return {
        'type': 'function',
        'function': {
            'name': ANALYZE_PROJECT_STRUCTURE_TOOL_NAME,
            'description': (
                'Get a structural overview of the project. '
                "Modes: 'tree' (directory tree with file sizes), "
                "'imports' (import/dependency graph for a file), "
                "'symbols' (classes, functions, top-level names in a file), "
                "'recent' (recently modified files in the repo), "
                "'callers' (find all files that reference a symbol/function), "
                "'test_coverage' (find test files that cover a given source file), "
                "'file_outline' (compact signatures for a source file — less context than a full read). "
                'Use this BEFORE multi-file edits to understand dependencies.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'command': {
                        'type': 'string',
                        'enum': [
                            'tree',
                            'imports',
                            'symbols',
                            'file_outline',
                            'recent',
                            'callers',
                            'test_coverage',
                            'semantic_search',
                        ],
                        'description': (
                            'tree: directory tree (depth-limited). '
                            'imports: show what a file imports and what imports it. '
                            'symbols: list classes/functions/top-level names in a file. '
                            'file_outline: AST signatures only (Python) or line-based heads (fallback) — '
                            'for large files before read_file. '
                            'recent: git log of recently modified files. '
                            'callers: find all files referencing a given symbol name. '
                            'test_coverage: find test files that likely test a given source file. '
                            'semantic_search: robust AST-based search for symbol references.'
                        ),
                    },
                    'path': {
                        'type': 'string',
                        'description': (
                            "For 'tree': root directory to scan (default '.'). "
                            "For 'imports'/'symbols'/'file_outline'/'test_coverage': path to the file to analyze."
                        ),
                        'default': '.',
                    },
                    'symbol': {
                        'type': 'string',
                        'description': (
                            "For 'callers': the symbol/function/class name to search for."
                        ),
                    },
                    'depth': {
                        'type': 'integer',
                        'description': "For 'tree': max depth (default 1).",
                        'default': 1,
                    },
                },
                'required': ['command'],
            },
        },
    }


def build_analyze_project_structure_action(
    arguments: dict,
) -> AgentThinkAction:
    """Build the action for the analyze_project_structure tool call."""
    command = arguments.get('command', 'tree')
    path = arguments.get('path', '.')
    try:
        depth = int(arguments.get('depth', 1))
    except (ValueError, TypeError):
        depth = 1

    if command == 'tree':
        return _build_tree_action(path, depth)
    if command == 'imports':
        return _build_imports_action(path)
    if command == 'symbols':
        return _build_symbols_action(path)
    if command == 'file_outline':
        return _build_file_outline_action(path)
    if command == 'recent':
        return _build_recent_action()
    if command == 'callers':
        if not (symbol := arguments.get('symbol', '')):
            return AgentThinkAction(
                thought="[ANALYZE_PROJECT_STRUCTURE] 'callers' requires the 'symbol' parameter (function/class name to search for)."
            )
        return _build_callers_action(symbol, path)
    if command == 'test_coverage':
        return _build_test_coverage_action(path)
    if command == 'semantic_search':
        if not (symbol := arguments.get('symbol', '')):
            return AgentThinkAction(
                thought="[ANALYZE_PROJECT_STRUCTURE] 'semantic_search' requires the 'symbol' parameter."
            )
        return _build_semantic_search_action(symbol, path)
    return AgentThinkAction(
        thought=(
            f'[ANALYZE_PROJECT_STRUCTURE] Unknown command: {command}. '
            'Use tree/imports/symbols/file_outline/recent/callers/test_coverage/semantic_search.'
        )
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


def _extract_ast_summary(filepath: str) -> list[str]:
    if not filepath.endswith('.py'):
        return []
    import ast

    try:
        with open(filepath, 'r', encoding='utf-8') as file_handle:
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
            if methods:
                symbols.append(
                    f'      class {node.name} (methods: {", ".join(methods[:3])}{"..." if len(methods) > 3 else ""})'
                )
            else:
                symbols.append(f'      class {node.name}')
            continue
        if isinstance(node, ast.FunctionDef) and not node.name.startswith('_'):
            symbols.append(f'      def {node.name}')
    return symbols


def _git_files_for_tree(cwd: str) -> set[str]:
    try:
        result = subprocess.run(
            ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
            cwd=cwd,
            capture_output=True,
            text=False,
            check=True,
        )
        return {
            item.decode('utf-8', errors='ignore')
            for item in result.stdout.split(b'\0')
            if item
        }
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
    spec: object,
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


def _collect_matching_files(
    start_dir: str,
    *,
    root: str,
    spec: object,
    limit: int,
    predicate: Callable[[str, str, str], bool],
) -> list[str]:
    matches: list[str] = []
    for root_dir, dirs, files in os.walk(start_dir):
        prune_ignored_dirs(root, root_dir, dirs, spec)
        for filename in files:
            if is_ignored_file(root, root_dir, filename, spec):
                continue
            fpath = os.path.join(root_dir, filename)
            if not predicate(root_dir, filename, fpath):
                continue
            matches.append(fpath)
            if len(matches) >= limit:
                return matches
    return matches


def _file_contains_pattern(fpath: str, pattern: re.Pattern[str]) -> bool:
    try:
        with open(fpath, 'r', encoding='utf-8', errors='ignore') as file_handle:
            return bool(pattern.search(file_handle.read()))
    except Exception:
        return False


def _extend_named_section(
    out: list[str],
    *,
    title: str,
    items: list[str],
    empty_message: str,
) -> None:
    out.append(title)
    out.extend(items)
    if not items:
        out.append(empty_message)
    out.append('')


def _build_tree_action(path: str, depth: int) -> AgentThinkAction:
    """Directory tree with file sizes, respecting .gitignore."""
    depth = max(1, min(depth, 5))
    root = os.path.abspath(path)
    spec = get_ignore_spec(root)

    if not os.path.exists(root):
        return AgentThinkAction(
            thought=f'[ANALYZE_PROJECT_STRUCTURE] Path not found: {path}'
        )

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

        # Prune ignored directories using pathspec to prevent traversing into them
        prune_ignored_dirs(root, current_root, dirnames, spec)
        # Always manually prune .git since it's typically not in .gitignore
        if '.git' in dirnames:
            dirnames.remove('.git')

        dirnames.sort()

        # Surface directories before files so important folder navigation is immediate.
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

    return AgentThinkAction(thought='\n'.join(lines))


def _build_imports_action(path: str) -> AgentThinkAction:
    """Show what a file imports AND what other files import it."""
    out = [f'=== IMPORTS IN {os.path.basename(path)} ===']
    if os.path.isfile(path):
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                for i, line in enumerate(f, 1):
                    if line.startswith('import ') or line.startswith('from '):
                        out.append(f'{i}:{line.rstrip()}')
        except Exception as e:
            out.append(f'(error reading file: {e})')
    else:
        out.append('(file not found)')

    out.append('')
    out.append('=== FILES THAT IMPORT THIS MODULE ===')
    basename = os.path.splitext(os.path.basename(path))[0]

    # Try ripgrep first
    import shutil

    rg = shutil.which('rg')
    found_any = False

    if rg:
        try:
            res = subprocess.run(
                [
                    rg,
                    '-l',
                    f'(import|from).*{basename}',
                    '--type',
                    'py',
                    '--glob',
                    '!__pycache__',
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.stdout.strip():
                lines = res.stdout.splitlines()[:30]
                out.extend(lines)
                found_any = bool(lines)
        except Exception:
            pass

    if not found_any:
        # Fallback to python traversal
        count = 0
        import_re = re.compile(f'(import|from).*{re.escape(basename)}')
        root = os.getcwd()  # Or some relevant root
        spec = get_ignore_spec(root)

        for root_dir, dirs, files in os.walk('.'):
            # Use same robust filtering
            prune_ignored_dirs(root, root_dir, dirs, spec)

            for f in files:  # type: ignore
                if f.endswith('.py'):  # type: ignore
                    if is_ignored_file(root, root_dir, f, spec):  # type: ignore
                        continue
                    fpath = os.path.join(root_dir, f)  # type: ignore
                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='ignore') as fl:
                            if import_re.search(fl.read()):
                                out.append(fpath)
                                count += 1
                                if count >= 30:
                                    break
                    except Exception:
                        pass
            if count >= 30:
                break
        if count == 0:
            out.append('(no reverse imports found)')

    return AgentThinkAction(thought='\n'.join(out))


def _build_file_outline_action(path: str) -> AgentThinkAction:
    """Compact API-style outline: Python AST signatures, else line-based heads."""
    base = os.path.basename(path)
    out: list[str] = [f'=== FILE OUTLINE: {base} ===']
    if not os.path.isfile(path):
        out.append('(file not found)')
        return AgentThinkAction(thought='\n'.join(out))

    if path.endswith('.py'):
        import ast

        try:
            src = Path(path).read_text(encoding='utf-8', errors='ignore')
            tree = ast.parse(src)
        except (OSError, SyntaxError, ValueError) as e:
            out.append(f'(could not parse Python AST: {e}; falling back to line heads)')
            return AgentThinkAction(
                thought='\n'.join(out + _file_outline_fallback_lines(path))
            )

        def fmt_func(node: ast.FunctionDef | ast.AsyncFunctionDef, indent: str) -> str:
            pref = 'async def' if isinstance(node, ast.AsyncFunctionDef) else 'def'
            try:
                args_s = ast.unparse(node.args)
            except Exception:
                args_s = '(...)'
            ret = ''
            if node.returns is not None:
                try:
                    ret = ' -> ' + ast.unparse(node.returns)
                except Exception:
                    ret = ' -> ...'
            return f'{indent}{pref} {node.name}{args_s}{ret}'

        count = 0
        max_lines = 200
        for node in tree.body:
            if count >= max_lines:
                out.append('… (truncated)')
                break
            if isinstance(node, ast.ClassDef):
                out.append(f'class {node.name}')
                count += 1
                for item in node.body:
                    if count >= max_lines:
                        break
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if item.name.startswith('__') and item.name not in (
                            '__init__',
                            '__new__',
                        ):
                            continue
                        out.append(fmt_func(item, '  '))
                        count += 1
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith('_'):
                    out.append(fmt_func(node, ''))
                    count += 1
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and not t.id.startswith('_'):
                        try:
                            out.append(f'{t.id} = …')
                        except Exception:
                            out.append('(assignment)')
                        count += 1
                        break
        if len(out) <= 1:
            out.append('(no outline entries)')
        return AgentThinkAction(thought='\n'.join(out))

    out.extend(_file_outline_fallback_lines(path))
    return AgentThinkAction(thought='\n'.join(out))


def _file_outline_fallback_lines(path: str) -> list[str]:
    """Non-Python: first line of each plausible definition (regex), capped."""
    sym_re = re.compile(r'^(class |def |async def |[A-Z_][A-Z_0-9]* *=)')
    lines_out: list[str] = []
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            for i, line in enumerate(f, 1):
                if sym_re.match(line):
                    lines_out.append(f'{i}:{line.rstrip()}')
                    if len(lines_out) >= 80:
                        lines_out.append('… (truncated)')
                        break
    except OSError as e:
        return [f'(error reading file: {e})']
    if not lines_out:
        lines_out.append('(no outline heads found — use symbols or read_file)')
    return lines_out


def _build_symbols_action(path: str) -> AgentThinkAction:
    """List classes, functions, and top-level assignments in a file."""
    out = [f'=== SYMBOLS IN {os.path.basename(path)} ===']
    if os.path.isfile(path):
        sym_re = re.compile(r'^(class |def |async def |[A-Z_][A-Z_0-9]* *=)')
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                count = 0
                for i, line in enumerate(f, 1):
                    if sym_re.match(line):
                        out.append(f'{i}:{line.rstrip()}')
                        count += 1
                        if count >= 100:
                            break
                if count == 0:
                    out.append('(no symbols found)')
        except Exception as e:
            out.append(f'(error reading file: {e})')
    else:
        out.append('(file not found)')
    return AgentThinkAction(thought='\n'.join(out))


def _build_recent_action() -> AgentThinkAction:
    """Recently modified files via git log."""
    out = ['=== RECENTLY MODIFIED FILES (last 20 commits) ===']
    try:
        res = subprocess.run(
            ['git', 'log', '--oneline', '--name-only', '-20', '--pretty=format:%h %s'],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.stdout.strip():
            out.extend(res.stdout.splitlines()[:100])
        else:
            out.append('(no commits or not a git repository)')
    except Exception:
        out.append('(git not available or error running git)')
    return AgentThinkAction(thought='\n'.join(out))


def _build_callers_action(symbol: str, scope: str) -> AgentThinkAction:
    """Find all files that reference a given symbol (function, class, variable)."""
    trunc_sym = f'{symbol[:40]}…' if len(symbol) > 40 else symbol
    out = [f'=== CALLERS OF {trunc_sym} ===']

    import shutil

    rg = shutil.which('rg')
    safe_scope = scope if scope and scope != '.' else '.'
    root = os.path.abspath('.')
    spec = get_ignore_spec(root)

    if rg:
        try:
            res = subprocess.run(
                [
                    rg,
                    '-n',
                    '--word-regexp',
                    symbol,
                    '--type',
                    'py',
                    '--type',
                    'js',
                    '--type',
                    'ts',
                    # relies on .gitignore, but add failsafes
                    '--glob',
                    '!__pycache__',
                    '--glob',
                    '!node_modules',
                    '--glob',
                    '!.git',
                    safe_scope,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.stdout.strip():
                out.extend(res.stdout.splitlines()[:50])
                return AgentThinkAction(thought='\n'.join(out))
        except Exception:
            pass

    # Python fallback
    sym_re = re.compile(rf'\b{re.escape(symbol)}\b')
    count = 0
    for root_dir, dirs, files in os.walk(safe_scope):
        prune_ignored_dirs(root, root_dir, dirs, spec)

        for f in files:
            if is_ignored_file(root, root_dir, f, spec):
                continue
            if f.endswith(('.py', '.js', '.ts', '.tsx', '.jsx')):
                fpath = os.path.join(root_dir, f)
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as fl:
                        for i, line in enumerate(fl, 1):
                            if sym_re.search(line):
                                out.append(f'{fpath}:{i}:{line.rstrip()}')
                                count += 1
                                if count >= 50:
                                    break
                except Exception:
                    pass
            if count >= 50:
                break
        if count >= 50:
            break

    if count == 0:
        out.append(f'(no references found for {trunc_sym})')
    return AgentThinkAction(thought='\n'.join(out))


def _build_test_coverage_action(path: str) -> AgentThinkAction:
    """Find test files that likely cover a given source file."""
    basename = os.path.splitext(os.path.basename(path))[0]
    dirname = os.path.dirname(path) or '.'
    out = [f'=== TEST COVERAGE FOR {os.path.basename(path)} ===']

    root = os.path.abspath('.')
    spec = get_ignore_spec(root)

    name_re = re.compile(
        rf'^(test_{re.escape(basename)}\.py|{re.escape(basename)}_test\.py)$'
    )
    test_files = _collect_matching_files(
        '.',
        root=root,
        spec=spec,
        limit=20,
        predicate=lambda _root_dir, filename, _fpath: bool(name_re.match(filename)),
    )
    _extend_named_section(
        out,
        title='--- Tests by naming convention ---',
        items=test_files,
        empty_message='(none)',
    )

    import_re = re.compile(rf'(import|from).*{re.escape(basename)}')
    import_test_files = _collect_matching_files(
        '.',
        root=root,
        spec=spec,
        limit=20,
        predicate=lambda _root_dir, filename, fpath: (
            (filename.startswith('test_') or filename.endswith('_test.py'))
            and fpath not in test_files
            and _file_contains_pattern(fpath, import_re)
        ),
    )
    _extend_named_section(
        out,
        title='--- Tests that import this module ---',
        items=import_test_files,
        empty_message='(no importing test files found)',
    )

    conftest_files = _collect_matching_files(
        dirname,
        root=root,
        spec=spec,
        limit=10,
        predicate=lambda _root_dir, filename, _fpath: filename == 'conftest.py',
    )
    _extend_named_section(
        out,
        title='--- Conftest files in scope ---',
        items=conftest_files,
        empty_message='(none)',
    )

    return AgentThinkAction(thought='\n'.join(out))


def _build_semantic_search_action(symbol: str, path: str) -> AgentThinkAction:
    """Robust AST-based reference search using the semantic_analyzer script."""
    import sys

    import backend.engine.tools.semantic_analyzer as sa

    script_path = sa.__file__
    try:
        res = subprocess.run(
            [sys.executable, script_path, 'find_references', symbol, path],
            capture_output=True,
            text=True,
            check=False,
        )
        return AgentThinkAction(
            thought=res.stdout
            if res.stdout.strip()
            else f'(no output from semantic search for {symbol})'
        )
    except Exception as e:
        return AgentThinkAction(thought=f'(error running semantic search: {e})')
