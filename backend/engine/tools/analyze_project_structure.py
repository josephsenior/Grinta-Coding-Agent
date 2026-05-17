"""Project Map tool — gives the LLM a quick structural overview of the workspace.

Provides directory tree, import graph, symbol index, and recently modified files
in a single call, preventing cross-file breakage by surfacing dependencies the
LLM wouldn't otherwise know about.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.engine.tools.ignore_filter import (
    get_ignore_spec,
    is_ignored_file,
    prune_ignored_dirs,
)
from backend.execution.utils.bounded_io import (
    BoundedResult,
    async_bounded_subprocess_exec,
)
from backend.ledger.action import AgentThinkAction
from backend.utils.async_utils import call_async_from_sync

ANALYZE_PROJECT_STRUCTURE_TOOL_NAME = 'analyze_project_structure'


def _run_command(
    args: list[str],
    *,
    cwd: str | None = None,
    process_timeout: float = 30.0,
    max_bytes_per_stream: int = 2 * 1024 * 1024,
) -> BoundedResult:
    return call_async_from_sync(
        async_bounded_subprocess_exec,
        process_timeout + 5.0,
        args,
        cwd=cwd,
        process_timeout=process_timeout,
        max_bytes_per_stream=max_bytes_per_stream,
    )


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
                "'dependencies' (transitive upstream/downstream dependency tree for a file), "
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
                            'dependencies',
                        ],
                        'description': (
                            'tree: directory tree (depth-limited). '
                            'imports: show what a file imports and what imports it (1 hop). '
                            'symbols: list classes/functions/top-level names in a file. '
                            'file_outline: AST signatures only (Python) or line-based heads (fallback) — '
                            'for large files before read_file. '
                            'recent: git log of recently modified files. '
                            'callers: find all files referencing a given symbol name. '
                            'test_coverage: find test files that likely test a given source file. '
                            'semantic_search: robust AST-based search for symbol references. '
                            'dependencies: transitive upstream/downstream dependency tree '
                            'for a file (multi-hop import graph, on-demand, no index).'
                        ),
                    },
                    'path': {
                        'type': 'string',
                        'description': (
                            "For 'tree': root directory to scan (default '.'). "
                            "For 'imports'/'symbols'/'file_outline'/'test_coverage'/'dependencies': "
                            'path to the file to analyze.'
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
                        'description': (
                            "For 'tree': max depth (default 1). "
                            "For 'dependencies': max transitive hops (default 2, capped at 4)."
                        ),
                        'default': 1,
                    },
                    'direction': {
                        'type': 'string',
                        'enum': ['upstream', 'downstream', 'both'],
                        'description': (
                            "For 'dependencies': 'upstream' = files that import this one; "
                            "'downstream' = files this one imports; 'both' = union. Default 'both'."
                        ),
                        'default': 'both',
                    },
                },
                'required': ['command'],
            },
        },
    }


def _analyze_depth(arguments: dict) -> int:
    try:
        return int(arguments.get('depth', 1))
    except (ValueError, TypeError):
        return 1


def _diag(
    *,
    reason: str,
    command: str,
    params: dict[str, Any] | None = None,
    next_steps: list[str] | None = None,
) -> str:
    """Render a structured diagnostic block for empty/missing-input results.

    Replaces opaque ``"(no symbols found)"`` style messages with a small
    block that tells the model *why* the result was empty, *what arguments*
    it actually used, and *what to try next*. The shape is stable enough
    for downstream agents to scan but still human-readable.
    """
    lines: list[str] = ['[ANALYZE_PROJECT_STRUCTURE] no_results']
    lines.append(f'  command: {command}')
    lines.append(f'  reason: {reason}')
    if params:
        flat = ', '.join(
            f'{k}={v!r}' for k, v in params.items() if v is not None and v != ''
        )
        if flat:
            lines.append(f'  params_used: {flat}')
    if next_steps:
        lines.append('  next_steps:')
        for step in next_steps:
            lines.append(f'    - {step}')
    return '\n'.join(lines)


def build_analyze_project_structure_action(
    arguments: dict,
) -> AgentThinkAction:
    """Build the action for the analyze_project_structure tool call."""
    command = arguments.get('command', 'tree')
    path = arguments.get('path', '.')
    depth = _analyze_depth(arguments)

    if command == 'callers':
        if not (symbol := arguments.get('symbol', '')):
            return AgentThinkAction(
                thought=_diag(
                    reason="missing required parameter 'symbol'",
                    command='callers',
                    params={'path': path},
                    next_steps=[
                        "Re-call with symbol='<name>' (function or class to find references for).",
                        'Tip: pair with command=imports to first see what a file exports.',
                    ],
                )
            )
        return _build_callers_action(symbol, path)

    if command == 'semantic_search':
        if not (symbol := arguments.get('symbol', '')):
            return AgentThinkAction(
                thought=_diag(
                    reason="missing required parameter 'symbol'",
                    command='semantic_search',
                    params={'path': path},
                    next_steps=[
                        "Re-call with symbol='<name>' to AST-search for references.",
                    ],
                )
            )
        return _build_semantic_search_action(symbol, path)

    handlers: dict[str, Callable[[], AgentThinkAction]] = {
        'tree': lambda: _build_tree_action(path, depth),
        'imports': lambda: _build_imports_action(path),
        'symbols': lambda: _build_symbols_action(path),
        'file_outline': lambda: _build_file_outline_action(path),
        'recent': lambda: _build_recent_action(),
        'test_coverage': lambda: _build_test_coverage_action(path),
        'dependencies': lambda: _build_dependencies_action(
            path,
            depth=depth,
            direction=str(arguments.get('direction', 'both') or 'both'),
        ),
    }

    if command in handlers:
        return handlers[command]()

    return AgentThinkAction(
        thought=_diag(
            reason=f'unknown command {command!r}',
            command=command,
            params={'path': path, 'depth': depth},
            next_steps=[
                'Use one of: tree, imports, symbols, file_outline, recent, '
                'callers, test_coverage, semantic_search, dependencies.',
            ],
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


def _class_outline_line(node: ast.ClassDef, methods: list[str]) -> str:
    if methods:
        head = ', '.join(methods[:3])
        if len(methods) > 3:
            head = f'{head}...'
        return f'      class {node.name} (methods: {head})'
    return f'      class {node.name}'


def _imports_forward_block(path: str) -> list[str]:
    """Lines describing import/from statements in ``path`` (lines only)."""
    out: list[str] = []
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8', errors='ignore') as f:
                for i, line in enumerate(f, 1):
                    if line.startswith('import ') or line.startswith('from '):
                        out.append(f'{i}:{line.rstrip()}')
        except Exception as e:
            out.append(f'(error reading file: {e})')
    else:
        out.append('(file not found)')
    return out


def _imports_reverse_via_rg(basename: str) -> list[str] | None:
    """Return importer paths from ripgrep when it finds hits; otherwise ``None``."""
    rg = shutil.which('rg')
    if not rg:
        return None
    try:
        res = _run_command(
            [
                rg,
                '-l',
                f'(import|from).*{basename}',
                '--type',
                'py',
                '--glob',
                '!__pycache__',
            ],
        )
        if res.stdout.strip():
            return res.stdout.splitlines()[:30]
    except Exception:
        pass
    return None


def _imports_reverse_via_walk(basename: str) -> list[str]:
    """Python traversal fallback for reverse-import search."""
    import_re = re.compile(f'(import|from).*{re.escape(basename)}')
    root = os.getcwd()
    spec = get_ignore_spec(root)
    lines: list[str] = []
    count = 0
    for root_dir, dirs, files in os.walk('.'):
        prune_ignored_dirs(root, root_dir, dirs, spec)

        for f in files:
            if f.endswith('.py'):
                if is_ignored_file(root, root_dir, f, spec):
                    continue
                fpath = os.path.join(root_dir, f)
                try:
                    with open(fpath, encoding='utf-8', errors='ignore') as fl:
                        if import_re.search(fl.read()):
                            lines.append(fpath)
                            count += 1
                            if count >= 30:
                                break
                except Exception:
                    pass
            if count >= 30:
                break
        if count >= 30:
            break
    return lines


def _ast_func_outline_signature(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    indent: str,
) -> str:
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


def _outline_append_assign_targets(node: ast.Assign) -> list[str]:
    lines: list[str] = []
    for t in node.targets:
        if isinstance(t, ast.Name) and not t.id.startswith('_'):
            try:
                lines.append(f'{t.id} = …')
            except Exception:
                lines.append('(assignment)')
            break
    return lines


def _outline_class_body_lines(
    class_node: ast.ClassDef, start_count: int, max_lines: int
) -> tuple[list[str], int]:
    out: list[str] = [f'class {class_node.name}']
    count = start_count + 1
    for item in class_node.body:
        if count >= max_lines:
            break
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name.startswith('__') and item.name not in (
                '__init__',
                '__new__',
            ):
                continue
            out.append(_ast_func_outline_signature(item, '  '))
            count += 1
    return out, count


def _python_outline_lines_from_ast(
    tree: ast.Module,
    *,
    max_lines: int = 200,
) -> list[str]:
    """Outline body lines after header for parsed Python (may truncate)."""
    out: list[str] = []
    count = 0
    for node in tree.body:
        if count >= max_lines:
            out.append('… (truncated)')
            break
        if isinstance(node, ast.ClassDef):
            cls_lines, count = _outline_class_body_lines(node, count, max_lines)
            out.extend(cls_lines)
            continue

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith('_'):
                out.append(_ast_func_outline_signature(node, ''))
                count += 1
            continue

        if isinstance(node, ast.Assign):
            assign_lines = _outline_append_assign_targets(node)
            out.extend(assign_lines)
            if assign_lines:
                count += 1
            continue

    return out


def _callers_lines_via_rg(symbol: str, safe_scope: str) -> list[str] | None:
    """Return rg output lines only when rg finds matches."""
    rg = shutil.which('rg')
    if not rg:
        return None
    try:
        res = _run_command(
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
                '--glob',
                '!__pycache__',
                '--glob',
                '!node_modules',
                '--glob',
                '!.git',
                safe_scope,
            ],
        )
        if res.stdout.strip():
            return res.stdout.splitlines()[:50]
    except Exception:
        pass
    return None


def _gather_caller_hits_in_file(
    fpath: str,
    sym_re: re.Pattern[str],
    lines: list[str],
    count: int,
    *,
    limit: int = 50,
) -> int:
    """Append matches from ``fpath`` until ``limit`` total hits."""
    try:
        with open(fpath, encoding='utf-8', errors='ignore') as fl:
            for i, line in enumerate(fl, 1):
                if sym_re.search(line):
                    lines.append(f'{fpath}:{i}:{line.rstrip()}')
                    count += 1
                    if count >= limit:
                        return count
    except Exception:
        pass
    return count


def _callers_lines_via_walk(
    *,
    symbol: str,
    safe_scope: str,
) -> tuple[list[str], int]:
    """Walk files for symbol references."""
    sym_re = re.compile(r'\b' + re.escape(symbol) + r'\b')
    lines: list[str] = []
    count = 0
    root = os.path.abspath('.')
    spec = get_ignore_spec(root)
    for root_dir, dirs, files in os.walk(safe_scope):
        prune_ignored_dirs(root, root_dir, dirs, spec)

        for f in files:
            if is_ignored_file(root, root_dir, f, spec):
                continue
            if f.endswith(('.py', '.js', '.ts', '.tsx', '.jsx')):
                fpath = os.path.join(root_dir, f)
                count = _gather_caller_hits_in_file(fpath, sym_re, lines, count)
                if count >= 50:
                    break
            if count >= 50:
                break
        if count >= 50:
            break
    return lines, count


def _extract_ast_summary(filepath: str) -> list[str]:
    if not filepath.endswith('.py'):
        return []

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
        return {
            item
            for item in result.stdout.split('\0')
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


def _collect_matching_files(
    start_dir: str,
    *,
    root: str,
    spec: Any,
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
    out.extend(_imports_forward_block(path))
    out.append('')
    out.append('=== FILES THAT IMPORT THIS MODULE ===')
    basename = os.path.splitext(os.path.basename(path))[0]

    rg_hits = _imports_reverse_via_rg(basename)
    if rg_hits is not None:
        out.extend(rg_hits)
        return AgentThinkAction(thought='\n'.join(out))

    walk_hits = _imports_reverse_via_walk(basename)
    if walk_hits:
        out.extend(walk_hits)
    else:
        out.append(
            _diag(
                reason='no other files import this module',
                command='imports',
                params={'path': path, 'basename_searched': basename},
                next_steps=[
                    'Confirm the file path is correct and committed to the repo.',
                    'Try command=callers with a public symbol name from this file.',
                    'Try command=search_code (separate tool) for non-import references.',
                ],
            )
        )
    return AgentThinkAction(thought='\n'.join(out))


def _build_file_outline_action(path: str) -> AgentThinkAction:
    """Compact API-style outline: Python AST signatures, else line-based heads."""
    base = os.path.basename(path)
    out: list[str] = [f'=== FILE OUTLINE: {base} ===']
    if not os.path.isfile(path):
        out.append(
            _diag(
                reason='file not found at given path',
                command='file_outline',
                params={'path': path},
                next_steps=[
                    'Pass a path relative to the workspace root.',
                    'Run command=tree first to discover the actual file location.',
                ],
            )
        )
        return AgentThinkAction(thought='\n'.join(out))

    if path.endswith('.py'):
        try:
            src = Path(path).read_text(encoding='utf-8', errors='ignore')
            tree = ast.parse(src)
        except (OSError, SyntaxError, ValueError) as e:
            out.append(f'(could not parse Python AST: {e}; falling back to line heads)')
            return AgentThinkAction(
                thought='\n'.join(out + _file_outline_fallback_lines(path))
            )

        out.extend(_python_outline_lines_from_ast(tree))
        if len(out) <= 1:
            out.append(
                _diag(
                    reason='no top-level definitions in file',
                    command='file_outline',
                    params={'path': path},
                    next_steps=[
                        'Use command=symbols for a regex-based listing.',
                        'Use read_file directly — the file may be small or data-only.',
                    ],
                )
            )
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
    return AgentThinkAction(thought='\n'.join(out))


def _build_recent_action() -> AgentThinkAction:
    """Recently modified files via git log."""
    out = ['=== RECENTLY MODIFIED FILES (last 20 commits) ===']
    try:
        res = _run_command(
            ['git', 'log', '--oneline', '--name-only', '-20', '--pretty=format:%h %s'],
            process_timeout=10.0,
        )
        if res.stdout.strip():
            out.extend(res.stdout.splitlines()[:100])
        else:
            out.append(
                _diag(
                    reason='no commits or current directory is not a git repository',
                    command='recent',
                    params={'cwd': os.getcwd()},
                    next_steps=[
                        'Run from inside a git repository, or skip command=recent.',
                        'Use command=tree for a directory listing instead.',
                    ],
                )
            )
    except Exception:
        out.append('(git not available or error running git)')
    return AgentThinkAction(thought='\n'.join(out))


def _build_callers_action(symbol: str, scope: str) -> AgentThinkAction:
    """Find all files that reference a given symbol (function, class, variable)."""
    trunc_sym = f'{symbol[:40]}…' if len(symbol) > 40 else symbol
    out = [f'=== CALLERS OF {trunc_sym} ===']

    safe_scope = scope if scope and scope != '.' else '.'
    rg_lines = _callers_lines_via_rg(symbol, safe_scope)
    if rg_lines is not None:
        out.extend(rg_lines)
        return AgentThinkAction(thought='\n'.join(out))

    walk_lines, count = _callers_lines_via_walk(
        symbol=symbol,
        safe_scope=safe_scope,
    )
    out.extend(walk_lines)
    if count == 0:
        out.append(
            _diag(
                reason=f'no references found for symbol {trunc_sym!r}',
                command='callers',
                params={'symbol': symbol, 'path': scope},
                next_steps=[
                    'Verify the symbol name is spelled exactly as in source.',
                    'Try command=semantic_search for AST-aware matching.',
                    'Broaden the search by passing path=. (workspace root).',
                ],
            )
        )
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
        res = _run_command(
            [sys.executable, script_path, 'find_references', symbol, path],
            process_timeout=30.0,
        )
        return AgentThinkAction(
            thought=res.stdout
            if res.stdout.strip()
            else _diag(
                reason='AST search returned no output',
                command='semantic_search',
                params={'symbol': symbol, 'path': path},
                next_steps=[
                    'Confirm path points to a parseable source file.',
                    'Try command=callers for a faster regex-based scan.',
                ],
            )
        )
    except Exception as e:
        return AgentThinkAction(thought=f'(error running semantic search: {e})')


# --------------------------------------------------------------------------- #
# Dependencies mode (transitive upstream/downstream walk, on-demand, no index).
#
# This resurrects the capability that used to live in the (removed) GraphRAG
# ``explore_tree_structure`` tool, but without a persistent graph: every call
# does a bounded, cycle-safe BFS using the existing AST + ripgrep + ignore
# plumbing. Results are useful for "what would break if I touch this file?"
# (upstream) and "what files do I need to read to understand this one?"
# (downstream).
# --------------------------------------------------------------------------- #

_DEPENDENCY_MAX_DEPTH = 4
_DEPENDENCY_MAX_NODES = 200


def _module_to_candidate_paths(module: str, root: str) -> list[str]:
    """Map a dotted Python module to candidate workspace file paths.

    ``foo.bar.baz`` → ``[foo/bar/baz.py, foo/bar/baz/__init__.py]``. Returns
    only paths that actually exist; empty list when the module is external
    (stdlib, site-packages) or unresolvable in this workspace.
    """
    if not module or module.startswith('.'):
        # Relative imports cannot be resolved from module text alone; skip.
        return []
    parts = module.split('.')
    rel_module = os.path.join(*parts) + '.py'
    rel_pkg = os.path.join(*parts, '__init__.py')
    candidates: list[str] = []
    for rel in (rel_module, rel_pkg):
        full = os.path.join(root, rel)
        if os.path.isfile(full):
            candidates.append(rel.replace('\\', '/'))
    return candidates


def _downstream_imports(file_path: str, root: str) -> list[str]:
    """Return workspace-relative paths that ``file_path`` imports (best-effort).

    Only Python files are walked via AST. Non-Python files return an empty
    list; the dependency walk silently skips them.
    """
    abs_path = file_path if os.path.isabs(file_path) else os.path.join(root, file_path)
    if not abs_path.endswith('.py') or not os.path.isfile(abs_path):
        return []
    try:
        src = Path(abs_path).read_text(encoding='utf-8', errors='ignore')
        tree = ast.parse(src)
    except (OSError, SyntaxError, ValueError):
        return []
    targets: list[str] = []
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            # ``from pkg import sub_a, sub_b`` may pull in either symbols *or*
            # sub-modules. Probe both ``pkg`` and each ``pkg.<name>`` so the
            # walk follows real sub-module imports.
            modules = [node.module]
            modules.extend(f'{node.module}.{alias.name}' for alias in node.names)
        for module in modules:
            for cand in _module_to_candidate_paths(module, root):
                if cand not in targets:
                    targets.append(cand)
    return targets


def _upstream_importers(file_path: str, root: str) -> list[str]:
    """Return workspace-relative paths that import ``file_path`` (best-effort)."""
    basename = os.path.splitext(os.path.basename(file_path))[0]
    if not basename:
        return []
    rg_hits = _imports_reverse_via_rg(basename)
    raw = rg_hits if rg_hits is not None else _imports_reverse_via_walk(basename)
    cleaned: list[str] = []
    abs_target = os.path.abspath(
        file_path if os.path.isabs(file_path) else os.path.join(root, file_path)
    )
    for hit in raw:
        norm = hit.lstrip('./').replace('\\', '/')
        if not norm:
            continue
        # Skip self-references; scanners match on basename so the file itself
        # often appears in its own importer list.
        if os.path.abspath(os.path.join(root, norm)) == abs_target:
            continue
        if norm not in cleaned:
            cleaned.append(norm)
    return cleaned


def _walk_dependency_graph(
    start: str,
    *,
    direction: str,
    max_depth: int,
    root: str,
) -> tuple[dict[str, list[str]], set[str], bool]:
    """BFS over the import graph. Returns (edges, visited, truncated)."""
    edges: dict[str, list[str]] = {}
    visited: set[str] = {start}
    queue: list[tuple[str, int]] = [(start, 0)]
    truncated = False
    while queue:
        node, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        if direction == 'downstream':
            neighbors = _downstream_imports(node, root)
        elif direction == 'upstream':
            neighbors = _upstream_importers(node, root)
        else:  # both
            neighbors = list(
                dict.fromkeys(
                    _downstream_imports(node, root) + _upstream_importers(node, root)
                )
            )
        edges[node] = neighbors
        for n in neighbors:
            if n in visited:
                continue
            if len(visited) >= _DEPENDENCY_MAX_NODES:
                truncated = True
                break
            visited.add(n)
            queue.append((n, depth + 1))
        if truncated:
            break
    return edges, visited, truncated


def _render_dependency_tree(
    start: str,
    edges: dict[str, list[str]],
    *,
    max_depth: int,
) -> list[str]:
    """ASCII tree rendering with cycle-aware ``(↺)`` markers."""
    lines: list[str] = []
    seen_on_path: set[str] = set()

    def _walk(node: str, depth: int, prefix: str) -> None:
        if depth > max_depth:
            return
        children = edges.get(node, [])
        for i, child in enumerate(children):
            is_last = i == len(children) - 1
            connector = '└── ' if is_last else '├── '
            cycle_marker = ' (↺)' if child in seen_on_path else ''
            lines.append(f'{prefix}{connector}{child}{cycle_marker}')
            if child in seen_on_path or child not in edges:
                continue
            seen_on_path.add(child)
            extension = '    ' if is_last else '│   '
            _walk(child, depth + 1, prefix + extension)
            seen_on_path.discard(child)

    lines.append(start)
    seen_on_path.add(start)
    _walk(start, 0, '')
    return lines


def _build_dependencies_action(
    path: str,
    *,
    depth: int,
    direction: str,
) -> AgentThinkAction:
    """Render an on-demand transitive import-graph for ``path``.

    Resurrects the removed GraphRAG ``explore_tree_structure`` capability
    without re-introducing a persistent index. The walk is bounded by both
    depth (capped at :data:`_DEPENDENCY_MAX_DEPTH`) and a hard node cap so
    a fan-out hub cannot explode the result.
    """
    direction = direction.lower().strip() or 'both'
    if direction not in ('upstream', 'downstream', 'both'):
        return AgentThinkAction(
            thought=_diag(
                reason=f'invalid direction {direction!r}',
                command='dependencies',
                params={'path': path, 'direction': direction, 'depth': depth},
                next_steps=["Use direction='upstream', 'downstream', or 'both'."],
            )
        )

    root = os.path.abspath('.')
    abs_path = path if os.path.isabs(path) else os.path.join(root, path)
    if not os.path.isfile(abs_path):
        return AgentThinkAction(
            thought=_diag(
                reason='anchor file not found',
                command='dependencies',
                params={'path': path, 'direction': direction, 'depth': depth},
                next_steps=[
                    'Pass a file path relative to the workspace root.',
                    'Run command=tree to discover the actual file location.',
                ],
            )
        )

    effective_depth = max(1, min(int(depth or 2), _DEPENDENCY_MAX_DEPTH))
    rel_start = os.path.relpath(abs_path, root).replace('\\', '/')

    edges, visited, truncated = _walk_dependency_graph(
        rel_start,
        direction=direction,
        max_depth=effective_depth,
        root=root,
    )

    out: list[str] = [
        '=== DEPENDENCY TREE ===',
        f'anchor: {rel_start}',
        f'direction: {direction}',
        f'depth: {effective_depth} (max={_DEPENDENCY_MAX_DEPTH})',
        f'nodes: {len(visited)} (cap={_DEPENDENCY_MAX_NODES}'
        f'{", TRUNCATED" if truncated else ""})',
        '',
    ]
    out.extend(_render_dependency_tree(rel_start, edges, max_depth=effective_depth))

    total_edges = sum(len(v) for v in edges.values())
    if total_edges == 0:
        out.append('')
        out.append(
            _diag(
                reason='no dependency edges found at this depth',
                command='dependencies',
                params={'path': path, 'direction': direction, 'depth': depth},
                next_steps=[
                    'Increase depth (capped at 4) for a wider view.',
                    "Try direction='both' to include upstream and downstream.",
                    'Verify the file actually contains/uses imports of in-workspace modules.',
                ],
            )
        )

    # Compact JSON edge sidecar for downstream tooling.
    import json

    edge_payload = {
        'anchor': rel_start,
        'direction': direction,
        'depth': effective_depth,
        'truncated': truncated,
        'edges': {k: list(v) for k, v in edges.items()},
    }
    out.append('')
    out.append('=== EDGES (json) ===')
    out.append(json.dumps(edge_payload, indent=2, sort_keys=True))

    return AgentThinkAction(thought='\n'.join(out))
