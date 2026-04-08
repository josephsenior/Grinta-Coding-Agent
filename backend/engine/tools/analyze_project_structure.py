"""Project Map tool — gives the LLM a quick structural overview of the workspace.

Provides directory tree, import graph, symbol index, and recently modified files
in a single call, preventing cross-file breakage by surfacing dependencies the
LLM wouldn't otherwise know about.
"""

from __future__ import annotations

import os
import shlex
import shutil

from backend.engine.tools.prompt import uses_powershell_terminal
from backend.ledger.action import AgentThinkAction, CmdRunAction

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
                        'description': "For 'tree': max depth (default 3).",
                        'default': 3,
                    },
                },
                'required': ['command'],
            },
        },
    }


def build_analyze_project_structure_action(
    arguments: dict,
) -> CmdRunAction | AgentThinkAction:
    """Build the action for the analyze_project_structure tool call."""
    command = arguments.get('command', 'tree')
    path = arguments.get('path', '.')
    depth = int(arguments.get('depth', 3))

    if command == 'tree':
        return _build_tree_action(path, depth)
    elif command == 'imports':
        return _build_imports_action(path)
    elif command == 'symbols':
        return _build_symbols_action(path)
    elif command == 'recent':
        return _build_recent_action()
    elif command == 'callers':
        symbol = arguments.get('symbol', '')
        if not symbol:
            return AgentThinkAction(
                thought="[ANALYZE_PROJECT_STRUCTURE] 'callers' requires the 'symbol' parameter (function/class name to search for)."
            )
        return _build_callers_action(symbol, path)
    elif command == 'test_coverage':
        return _build_test_coverage_action(path)
    elif command == 'semantic_search':
        symbol = arguments.get('symbol', '')
        if not symbol:
            return AgentThinkAction(
                thought="[ANALYZE_PROJECT_STRUCTURE] 'semantic_search' requires the 'symbol' parameter."
            )
        return _build_semantic_search_action(symbol, path)
    else:
        return AgentThinkAction(
            thought=f'[ANALYZE_PROJECT_STRUCTURE] Unknown command: {command}. Use tree/imports/symbols/recent/callers/test_coverage.'
        )


def _build_tree_action(path: str, depth: int) -> CmdRunAction:
    """Directory tree with file sizes, respecting .gitignore."""
    depth = max(1, min(depth, 5))  # Clamp 1-5
    if uses_powershell_terminal():
        cmd = _build_windows_tree_command(path, depth)
        return CmdRunAction(command=cmd, display_label=f'Mapping project structure ({path})')

    safe_path = shlex.quote(path)
    # Prefer 'tree' if available, fall back to find
    cmd = (
        f'if command -v tree >/dev/null 2>&1; then '
        f"tree -L {depth} --dirsfirst -s -I '__pycache__|node_modules|.git|.venv|venv' {safe_path} | head -200; "
        f'else '
        f'find {safe_path} -maxdepth {depth} '
        f"\\( -name '__pycache__' -o -name 'node_modules' -o -name '.git' -o -name '.venv' -o -name 'venv' \\) -prune "
        f"-o -type f -printf '%s %p\\n' | sort -k2 | head -200; "
        f'fi'
    )
    return CmdRunAction(command=cmd, display_label=f'Mapping project structure ({path})')


def _build_windows_tree_command(path: str, depth: int) -> str:
    """PowerShell-safe tree listing for Windows runtimes without Bash."""
    safe_path = _quote_powershell_literal(path)
    return (
        f'$root = {safe_path}; '
        f'$maxDepth = {depth}; '
        "$ignore = @('__pycache__', 'node_modules', '.git', '.venv', 'venv'); "
        "$rootItem = Get-Item -LiteralPath $root -ErrorAction SilentlyContinue; "
        "if (-not $rootItem) { Write-Output '(path not found)'; exit 0 }; "
        "$rootPath = $rootItem.FullName; "
        "Get-ChildItem -LiteralPath $rootPath -Force -Recurse -Depth $maxDepth | "
        "Where-Object { "
        "  $relative = $_.FullName.Substring($rootPath.Length).TrimStart('\\'); "
        "  if (-not $relative) { return $false } "
        "  $segments = $relative -split '[\\\\/]'; "
        "  -not ($segments | Where-Object { $ignore -contains $_ }) "
        "} | "
        "Sort-Object FullName | "
        "ForEach-Object { "
        "  $relative = $_.FullName.Substring($rootPath.Length).TrimStart('\\'); "
        "  if ($_.PSIsContainer) { '<dir> {0}' -f $relative } else { '{0} {1}' -f $_.Length, $relative } "
        "} | Select-Object -First 200"
    )


def _quote_powershell_literal(value: str) -> str:
    """Quote a PowerShell string literal safely."""
    return "'" + value.replace("'", "''") + "'"


def _build_imports_action(path: str) -> CmdRunAction:
    """Show what a file imports AND what other files import it."""
    import os as _os
    if uses_powershell_terminal():
        return _build_windows_imports_action(path)
    safe_path = shlex.quote(path)
    cmd = (
        f"echo '=== IMPORTS IN {safe_path} ===' && "
        f"grep -nE '^(import |from .+ import )' {safe_path} 2>/dev/null || echo '(no imports found)' && "
        f"echo '' && echo '=== FILES THAT IMPORT THIS MODULE ===' && "
        f'basename_no_ext=$(basename {safe_path} .py) && '
        f'rg -l "(import|from).*$basename_no_ext" --type py --glob \'!__pycache__\' 2>/dev/null | head -30 || '
        f'grep -rl "$basename_no_ext" --include=\'*.py\' . 2>/dev/null | head -30 || '
        f"echo '(no reverse imports found)'"
    )
    return CmdRunAction(command=cmd, display_label=f'Reading imports · {_os.path.basename(path)}')


def _build_symbols_action(path: str) -> CmdRunAction:
    """List classes, functions, and top-level assignments in a file."""
    import os as _os
    if uses_powershell_terminal():
        return _build_windows_symbols_action(path)
    safe_path = shlex.quote(path)
    # Use grep to extract class/def/assignment lines — fast and universal
    cmd = (
        f"echo '=== SYMBOLS IN {safe_path} ===' && "
        f"grep -nE '^(class |def |async def |[A-Z_][A-Z_0-9]* *=)' {safe_path} 2>/dev/null | head -100 || "
        f"echo '(no symbols found or file does not exist)'"
    )
    return CmdRunAction(command=cmd, display_label=f'Listing symbols · {_os.path.basename(path)}')


def _build_recent_action() -> CmdRunAction:
    """Recently modified files via git log."""
    if uses_powershell_terminal():
        cmd = (
            "Write-Output '=== RECENTLY MODIFIED FILES (last 20 commits) ==='; "
            "try { git log --oneline --name-only -20 --pretty=format:'%h %s' 2>$null | "
            "Select-Object -First 100 } "
            "catch { Write-Output '(not a git repository or no commits)' }"
        )
    else:
        cmd = (
            "echo '=== RECENTLY MODIFIED FILES (last 20 commits) ===' && "
            "git log --oneline --name-only -20 --pretty=format:'%h %s' 2>/dev/null | head -100 || "
            "echo '(not a git repository or no commits)'"
        )
    return CmdRunAction(command=cmd, display_label='Reading recent git history')


def _build_callers_action(symbol: str, scope: str) -> CmdRunAction:
    """Find all files that reference a given symbol (function, class, variable).

    Uses ripgrep for speed with grep fallback. Searches for word-boundary
    matches to avoid false positives on substrings.
    """
    trunc_sym = symbol[:40] + '…' if len(symbol) > 40 else symbol
    if uses_powershell_terminal():
        return _build_windows_callers_action(symbol, scope, trunc_sym)
    safe_symbol = shlex.quote(symbol)
    safe_scope = shlex.quote(scope) if scope and scope != '.' else '.'
    cmd = (
        f"echo '=== CALLERS OF {safe_symbol} ===' && "
        f'rg -n --word-regexp {safe_symbol} --type py --type js --type ts '
        f"--glob '!__pycache__' --glob '!node_modules' --glob '!.git' "
        f'{safe_scope} 2>/dev/null | head -50 || '
        f"grep -rn --word-regexp {safe_symbol} --include='*.py' --include='*.js' "
        f"--include='*.ts' --include='*.tsx' --include='*.jsx' "
        f'{safe_scope} 2>/dev/null | head -50 || '
        f"echo '(no references found for {safe_symbol})'"
    )
    return CmdRunAction(command=cmd, display_label=f'Finding callers of {trunc_sym!r}')


def _build_test_coverage_action(path: str) -> CmdRunAction:
    """Find test files that likely cover a given source file.

    Uses three heuristics:
    1. Naming convention: test_<module>.py, <module>_test.py, test/<module>.py
    2. Import analysis: test files that import from the module
    3. Conftest files in the same directory tree
    """
    import os as _os
    if uses_powershell_terminal():
        return _build_windows_test_coverage_action(path)
    safe_path = shlex.quote(path)
    cmd = (
        f"echo '=== TEST COVERAGE FOR {safe_path} ===' && "
        # Extract the module basename (e.g., 'planner' from 'backend/engines/orchestrator/planner.py')
        f'basename_no_ext=$(basename {safe_path} .py) && '
        f'dirname_path=$(dirname {safe_path}) && '
        f"echo '--- Tests by naming convention ---' && "
        # Find test files matching naming conventions
        f'find . -type f \\( '
        f'-name "test_${{basename_no_ext}}.py" -o '
        f'-name "${{basename_no_ext}}_test.py" -o '
        f'-name "test_${{basename_no_ext}}.*.py" '
        f"\\) ! -path '*/__pycache__/*' 2>/dev/null | head -20 && "
        f"echo '' && echo '--- Tests that import this module ---' && "
        # Find test files that import the module
        f"rg -l \"(import|from).*${{basename_no_ext}}\" --glob 'test_*.py' --glob '*_test.py' "
        f"--glob '!__pycache__' 2>/dev/null | head -20 || "
        f"grep -rl \"${{basename_no_ext}}\" --include='test_*.py' --include='*_test.py' . "
        f'2>/dev/null | head -20 || '
        f"echo '(no importing test files found)' && "
        f"echo '' && echo '--- Conftest files in scope ---' && "
        f'find "$dirname_path" -name \'conftest.py\' -type f 2>/dev/null | head -10 || '
        f"echo '(none)'"
    )
    return CmdRunAction(command=cmd, display_label=f'Finding tests for {_os.path.basename(path)}')


# ------------------------------------------------------------------ #
#  Windows / PowerShell command builders
# ------------------------------------------------------------------ #

def _build_windows_imports_action(path: str) -> CmdRunAction:
    """PowerShell-safe import analysis."""
    import os as _os
    sp = _quote_powershell_literal(path)
    basename = _os.path.splitext(_os.path.basename(path))[0]
    sb = _quote_powershell_literal(basename)
    cmd = (
        f"Write-Output '=== IMPORTS IN {basename} ==='; "
        f"if (Test-Path {sp}) {{ "
        f"  Select-String -Pattern '^(import |from .+ import )' -Path {sp} -ErrorAction SilentlyContinue | "
        f"  ForEach-Object {{ $_.LineNumber.ToString() + ':' + $_.Line }} | Select-Object -First 50 "
        f"}} else {{ Write-Output '(file not found)' }}; "
        f"Write-Output ''; Write-Output '=== FILES THAT IMPORT THIS MODULE ==='; "
        f"Get-ChildItem -Path . -Filter '*.py' -Recurse -File -ErrorAction SilentlyContinue | "
        f"  Where-Object {{ $_.FullName -notmatch '__pycache__' }} | "
        f"  Select-String -Pattern ('(import|from).*' + {sb}) -List -ErrorAction SilentlyContinue | "
        f"  ForEach-Object {{ $_.Path }} | Select-Object -First 30; "
        f"if (-not $?) {{ Write-Output '(no reverse imports found)' }}"
    )
    return CmdRunAction(command=cmd, display_label=f'Reading imports · {_os.path.basename(path)}')


def _build_windows_symbols_action(path: str) -> CmdRunAction:
    """PowerShell-safe symbol listing."""
    import os as _os
    sp = _quote_powershell_literal(path)
    cmd = (
        f"Write-Output '=== SYMBOLS IN {_os.path.basename(path)} ==='; "
        f"if (Test-Path {sp}) {{ "
        f"  Select-String -Pattern '^(class |def |async def |[A-Z_][A-Z_0-9]* *=)' -Path {sp} -ErrorAction SilentlyContinue | "
        f"  ForEach-Object {{ $_.LineNumber.ToString() + ':' + $_.Line }} | Select-Object -First 100 "
        f"}} else {{ Write-Output '(no symbols found or file does not exist)' }}"
    )
    return CmdRunAction(command=cmd, display_label=f'Listing symbols · {_os.path.basename(path)}')


def _build_windows_callers_action(symbol: str, scope: str, trunc_sym: str) -> CmdRunAction:
    """PowerShell-safe caller search.  Prefers ``rg`` if available."""
    ss = _quote_powershell_literal(symbol)
    safe_scope = scope if scope and scope != '.' else '.'
    sp = _quote_powershell_literal(safe_scope)
    cmd = (
        f"Write-Output '=== CALLERS OF {trunc_sym} ==='; "
        f"$rg = Get-Command rg -ErrorAction SilentlyContinue; "
        f"if ($rg) {{ "
        f"  rg -n --word-regexp {ss} --type py --type js --type ts "
        f"  --glob '!__pycache__' --glob '!node_modules' --glob '!.git' "
        f"  {sp} 2>$null | Select-Object -First 50 "
        f"}} else {{ "
        f"  Get-ChildItem -Path {sp} -Include '*.py','*.js','*.ts','*.tsx','*.jsx' -Recurse -File -ErrorAction SilentlyContinue | "
        f"  Where-Object {{ $_.FullName -notmatch '__pycache__|node_modules|\\.git' }} | "
        f"  Select-String -Pattern ('\\b' + {ss} + '\\b') -ErrorAction SilentlyContinue | "
        f"  ForEach-Object {{ $_.Path + ':' + $_.LineNumber.ToString() + ':' + $_.Line }} | "
        f"  Select-Object -First 50 "
        f"}}; "
        f"if (-not $?) {{ Write-Output '(no references found for {trunc_sym})' }}"
    )
    return CmdRunAction(command=cmd, display_label=f'Finding callers of {trunc_sym!r}')


def _build_windows_test_coverage_action(path: str) -> CmdRunAction:
    """PowerShell-safe test-coverage heuristic search."""
    import os as _os
    basename = _os.path.splitext(_os.path.basename(path))[0]
    dirname = _os.path.dirname(path) or '.'
    sb = _quote_powershell_literal(basename)
    sd = _quote_powershell_literal(dirname)
    cmd = (
        f"Write-Output '=== TEST COVERAGE FOR {_os.path.basename(path)} ==='; "
        f"Write-Output '--- Tests by naming convention ---'; "
        f"Get-ChildItem -Path . -Recurse -File -ErrorAction SilentlyContinue | "
        f"  Where-Object {{ $_.Name -match ('^test_' + {sb} + '\\.py$|^' + {sb} + '_test\\.py$') -and $_.FullName -notmatch '__pycache__' }} | "
        f"  ForEach-Object {{ $_.FullName }} | Select-Object -First 20; "
        f"Write-Output ''; Write-Output '--- Tests that import this module ---'; "
        f"Get-ChildItem -Path . -Include 'test_*.py','*_test.py' -Recurse -File -ErrorAction SilentlyContinue | "
        f"  Where-Object {{ $_.FullName -notmatch '__pycache__' }} | "
        f"  Select-String -Pattern ('(import|from).*' + {sb}) -List -ErrorAction SilentlyContinue | "
        f"  ForEach-Object {{ $_.Path }} | Select-Object -First 20; "
        f"Write-Output ''; Write-Output '--- Conftest files in scope ---'; "
        f"Get-ChildItem -Path {sd} -Filter 'conftest.py' -Recurse -File -ErrorAction SilentlyContinue | "
        f"  ForEach-Object {{ $_.FullName }} | Select-Object -First 10; "
        f"if (-not $?) {{ Write-Output '(none)' }}"
    )
    return CmdRunAction(command=cmd, display_label=f'Finding tests for {_os.path.basename(path)}')


def _build_semantic_search_action(symbol: str, path: str) -> CmdRunAction:
    """Robust AST-based reference search using the semantic_analyzer script."""
    import shlex
    import sys

    import backend.engine.tools.semantic_analyzer as sa

    safe_symbol = shlex.quote(symbol)
    safe_path = shlex.quote(path)
    python_exe = sys.executable or 'python'
    script_path = sa.__file__

    cmd = f'{python_exe} {shlex.quote(script_path)} find_references {safe_symbol} {safe_path}'
    trunc_sym = symbol[:40] + '…' if len(symbol) > 40 else symbol
    return CmdRunAction(command=cmd, display_label=f'Searching references for {trunc_sym!r}')
