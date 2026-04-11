"""Project Map tool — gives the LLM a quick structural overview of the workspace.

Provides directory tree, import graph, symbol index, and recently modified files
in a single call, preventing cross-file breakage by surfacing dependencies the
LLM wouldn't otherwise know about.
"""

from __future__ import annotations

import os
import re
import subprocess
from backend.engine.tools.ignore_filter import get_ignore_spec, prune_ignored_dirs, is_ignored_file
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
                "'test_coverage' (find test files that cover a given source file). "
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
                            'recent',
                            'callers',
                            'test_coverage',
                            'semantic_search',
                        ],
                        'description': (
                            'tree: directory tree (depth-limited). '
                            'imports: show what a file imports and what imports it. '
                            'symbols: list classes/functions/top-level names in a file. '
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
                            "For 'imports'/'symbols'/'test_coverage': path to the file to analyze."
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
        thought=f'[ANALYZE_PROJECT_STRUCTURE] Unknown command: {command}. Use tree/imports/symbols/recent/callers/test_coverage.'
    )

def _build_tree_action(path: str, depth: int) -> AgentThinkAction:
    """Directory tree with file sizes, respecting .gitignore."""
    depth = max(1, min(depth, 5))
    root = os.path.abspath(path)
    spec = get_ignore_spec(root)

    if not os.path.exists(root):
        return AgentThinkAction(thought=f'[ANALYZE_PROJECT_STRUCTURE] Path not found: {path}')

    def rel_depth(relative_path: str) -> int:
        if relative_path in ('', '.'):
            return 0
        return relative_path.count(os.sep) + 1

    def sort_files(filenames: list[str]) -> list[str]:
        """Sort files with key project files first, then alphabetical."""
        priority = {
            'README.md': 0,
            'pyproject.toml': 1,
            'package.json': 2,
            'requirements.txt': 3,
            'Dockerfile': 4,
            'Makefile': 5,
            '.gitignore': 6,
        }
        return sorted(
            filenames,
            key=lambda name: (0, priority[name])
            if name in priority
            else (1, name.lower()),
        )
        
    def extract_ast_summary(filepath: str) -> list[str]:
        if not filepath.endswith('.py'):
            return []
        import ast
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            tree = ast.parse(content)
            symbols = []
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    methods = [m.name for m in node.body if isinstance(m, ast.FunctionDef) and not m.name.startswith('__')]
                    if methods:
                        symbols.append(f"      class {node.name} (methods: {', '.join(methods[:3])}{'...' if len(methods)>3 else ''})")
                    else:
                        symbols.append(f"      class {node.name}")
                elif isinstance(node, ast.FunctionDef) and not node.name.startswith('_'):
                    symbols.append(f"      def {node.name}")
            return symbols
        except Exception:
            return []

    def get_git_files(cwd: str) -> set[str]:
        """Try to get all tracked and untracked not-ignored files via git."""
        try:
            res = subprocess.run(
                ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                cwd=cwd, capture_output=True, text=False, check=True
            )
            return {f.decode('utf-8', errors='ignore') for f in res.stdout.split(b'\0') if f}
        except Exception:
            return set()

    git_files = get_git_files(root)
    use_git = len(git_files) > 0

    lines = [f"[ANALYZE_PROJECT_STRUCTURE] Mapping project semantic structure ({path})"]
    lines.append("Note: Large directories are truncated. Showing key classes/functions for Python files.")
    lines.append(
        "Recovery hint: do not repeat this tool with identical arguments; pick a specific subpath or run a concrete test/build/runtime command next."
    )
    
    emitted = 0
    max_total_items = float('inf')  # No hard limit on total items
    max_files_per_dir = 50
    emitted_dirs: set[str] = set()

    def add_dir_header(relative_dir: str) -> None:
        nonlocal emitted
        if relative_dir in ('', '.'):
            return
        key = relative_dir.replace(os.sep, '/')
        if key in emitted_dirs:
            return
        lines.append('<dir> ' + key)
        emitted_dirs.add(key)
        emitted += 1
    
    for current_root, dirnames, filenames in os.walk(root):
        relative_root = os.path.relpath(current_root, root)
        current_depth = rel_depth(relative_root)
        
        # Prune ignored directories using pathspec to prevent traversing into them
        prune_ignored_dirs(root, current_root, dirnames, spec)
        # Always manually prune .git since it's typically not in .gitignore
        if '.git' in dirnames:
            dirnames.remove('.git')
            
        dirnames.sort()

        # Surface directories before files so important folder navigation is immediate.
        if current_depth < depth:
            for dirname in dirnames:
                rel_child = (
                    dirname
                    if relative_root in ('', '.')
                    else os.path.join(relative_root, dirname)
                )
                add_dir_header(rel_child)

        if current_depth > depth:
            add_dir_header(relative_root)
            dirnames[:] = []
            continue

        add_dir_header(relative_root)

        # Filter filenames
        if use_git:
            valid_filenames = []
            for f in sort_files(filenames):
                rel_file = os.path.relpath(os.path.join(current_root, f), root).replace(os.sep, '/')
                if rel_file in git_files:
                    valid_filenames.append(f)
        else:
            valid_filenames = [
                f
                for f in sort_files(filenames)
                if not is_ignored_file(root, current_root, f, spec)
            ]
            
        shown_files = valid_filenames[:max_files_per_dir]
        hidden_files = len(valid_filenames) - len(shown_files)

        for filename in shown_files:
            full_path = os.path.join(current_root, filename)
            relative_path = os.path.relpath(full_path, root).replace(os.sep, '/')
            
            lines.append(f"  {relative_path}")
            emitted += 1
            
            # AST extraction purely in Python
            summary = extract_ast_summary(full_path)
            for sym in summary:
                lines.append(sym)
                emitted += 1
                
            if emitted >= max_total_items:
                lines.append(f"\n(Output truncated at {max_total_items} total items. Try lower depth or a more specific path directory.)")
                break
                
        if hidden_files > 0 and emitted < max_total_items:
            hint_path = relative_root.replace(os.sep, '/') or '.'
            lines.append(f"  ... and {hidden_files} more files inside {relative_root or '.'} hidden. Use path='{hint_path}' to explore.")
            emitted += 1

        if emitted >= max_total_items:
            break
            
    return AgentThinkAction(thought='\n'.join(lines))

def _build_imports_action(path: str) -> AgentThinkAction:
    """Show what a file imports AND what other files import it."""
    out = [f"=== IMPORTS IN {os.path.basename(path)} ==="]
    if os.path.isfile(path):
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                for i, line in enumerate(f, 1):
                    if line.startswith('import ') or line.startswith('from '):
                        out.append(f"{i}:{line.rstrip()}")
        except Exception as e:
            out.append(f'(error reading file: {e})')
    else:
        out.append('(file not found)')
        
    out.append("")
    out.append("=== FILES THAT IMPORT THIS MODULE ===")
    basename = os.path.splitext(os.path.basename(path))[0]
    
    # Try ripgrep first
    import shutil
    rg = shutil.which('rg')
    found_any = False
    
    if rg:
        try:
            res = subprocess.run([
                rg, '-l', f'(import|from).*{basename}',
                '--type', 'py', '--glob', '!__pycache__'
            ], capture_output=True, text=True, check=False)
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
        root = os.getcwd() # Or some relevant root
        spec = get_ignore_spec(root)
        
        for root_dir, dirs, files in os.walk('.'):
            # Use same robust filtering
            prune_ignored_dirs(root, root_dir, dirs, spec)
            
            for f in files:
                if f.endswith('.py'):
                    if is_ignored_file(root, root_dir, f, spec):
                        continue
                    fpath = os.path.join(root_dir, f)
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
            out.append("(no reverse imports found)")
            
    return AgentThinkAction(thought='\n'.join(out))

def _build_symbols_action(path: str) -> AgentThinkAction:
    """List classes, functions, and top-level assignments in a file."""
    out = [f"=== SYMBOLS IN {os.path.basename(path)} ==="]
    if os.path.isfile(path):
        sym_re = re.compile(r'^(class |def |async def |[A-Z_][A-Z_0-9]* *=)')
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                count = 0
                for i, line in enumerate(f, 1):
                    if sym_re.match(line):
                        out.append(f"{i}:{line.rstrip()}")
                        count += 1
                        if count >= 100:
                            break
                if count == 0:
                    out.append("(no symbols found)")
        except Exception as e:
            out.append(f"(error reading file: {e})")
    else:
        out.append('(file not found)')
    return AgentThinkAction(thought='\n'.join(out))

def _build_recent_action() -> AgentThinkAction:
    """Recently modified files via git log."""
    out = ["=== RECENTLY MODIFIED FILES (last 20 commits) ==="]
    try:
        res = subprocess.run(
            ['git', 'log', '--oneline', '--name-only', '-20', '--pretty=format:%h %s'],
            capture_output=True, text=True, check=False
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
    out = [f"=== CALLERS OF {trunc_sym} ==="]
    
    import shutil
    rg = shutil.which('rg')
    safe_scope = scope if scope and scope != '.' else '.'
    root = os.path.abspath('.')
    spec = get_ignore_spec(root)
    
    if rg:
        try:
            res = subprocess.run([
                rg, '-n', '--word-regexp', symbol,
                '--type', 'py', '--type', 'js', '--type', 'ts',
                # relies on .gitignore, but add failsafes
                '--glob', '!__pycache__', '--glob', '!node_modules', '--glob', '!.git',
                safe_scope
            ], capture_output=True, text=True, check=False)
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
                                out.append(f"{fpath}:{i}:{line.rstrip()}")
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
        out.append(f"(no references found for {trunc_sym})")
    return AgentThinkAction(thought='\n'.join(out))

def _build_test_coverage_action(path: str) -> AgentThinkAction:
    """Find test files that likely cover a given source file."""
    basename = os.path.splitext(os.path.basename(path))[0]
    dirname = os.path.dirname(path) or '.'
    out = [
        f"=== TEST COVERAGE FOR {os.path.basename(path)} ===",
        "--- Tests by naming convention ---"
    ]
    
    root = os.path.abspath('.')
    spec = get_ignore_spec(root)
    
    name_re = re.compile(rf'^(test_{re.escape(basename)}\.py|{re.escape(basename)}_test\.py)$')
    count = 0
    test_files = []
    
    for root_dir, dirs, files in os.walk('.'):
        prune_ignored_dirs(root, root_dir, dirs, spec)
        for f in files:
            if is_ignored_file(root, root_dir, f, spec):
                continue
            if name_re.match(f):
                test_files.append(os.path.join(root_dir, f))
                count += 1
                if count >= 20: break
        if count >= 20: break
        
    out.extend(test_files)
    if not test_files:
        out.append("(none)")
        
    out.append("")
    out.append("--- Tests that import this module ---")
    import_re = re.compile(rf'(import|from).*{re.escape(basename)}')
    count = 0
    import_test_files = []
    
    for root_dir, dirs, files in os.walk('.'):
        prune_ignored_dirs(root, root_dir, dirs, spec)
        for f in files:
            if is_ignored_file(root, root_dir, f, spec):
                continue
            if f.startswith('test_') or f.endswith('_test.py'):
                fpath = os.path.join(root_dir, f)
                if fpath in test_files:
                    continue # Already found
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as fl:
                        if import_re.search(fl.read()):
                            import_test_files.append(fpath)
                            count += 1
                            if count >= 20: break
                except Exception:
                    pass
        if count >= 20: break
        
    out.extend(import_test_files)
    if not import_test_files:
        out.append("(no importing test files found)")
        
    out.append("")
    out.append("--- Conftest files in scope ---")
    count = 0
    conftest_files = []
    for root_dir, dirs, files in os.walk(dirname):
        prune_ignored_dirs(root, root_dir, dirs, spec)
        for f in files:
            if is_ignored_file(root, root_dir, f, spec):
                continue
            if f == 'conftest.py':
                conftest_files.append(os.path.join(root_dir, f))
                count += 1
                if count >= 10: break
        if count >= 10: break
        
    out.extend(conftest_files)
    if not conftest_files:
        out.append("(none)")
        
    return AgentThinkAction(thought='\n'.join(out))

def _build_semantic_search_action(symbol: str, path: str) -> AgentThinkAction:
    """Robust AST-based reference search using the semantic_analyzer script."""
    import sys
    import backend.engine.tools.semantic_analyzer as sa
    
    script_path = sa.__file__
    try:
        res = subprocess.run(
            [sys.executable, script_path, 'find_references', symbol, path],
            capture_output=True, text=True, check=False
        )
        return AgentThinkAction(thought=res.stdout if res.stdout.strip() else f"(no output from semantic search for {symbol})")
    except Exception as e:
        return AgentThinkAction(thought=f"(error running semantic search: {e})")
