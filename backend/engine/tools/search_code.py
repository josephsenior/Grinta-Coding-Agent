"""Fast code search tool for the Orchestrator agent.

Eliminates the grep→parse→regrep cycle by providing a single
structured search interface that tries ripgrep first, then falls
back to grep.
"""

from __future__ import annotations

import shlex

from backend.engine.tools.common import create_tool_definition
from backend.engine.tools.prompt import uses_powershell_terminal
from backend.ledger.action import CmdRunAction

_SEARCH_EXCLUDED_DIRS = (
    '.git',
    '.venv',
    '.mypy_cache',
    '.pytest_cache',
    '.ruff_cache',
    '__pycache__',
    'node_modules',
    '.tmp_cli_manual',
    'logs',
    'storage',
    'build',
    'dist',
)

_SEARCH_CODE_DESCRIPTION = """\
Search for text patterns, symbols, or file paths in the codebase using ripgrep (falls back to grep).

Modes:
1. Text/regex search — set `pattern` to find matching lines across files.
2. File discovery — omit `pattern`, set `file_pattern` only to list matching files.

Use this when target location is unknown. For precise symbol refs at known positions, use `lsp_query`. \
For dependency traversal, use `explore_tree_structure`.
"""

SEARCH_CODE_TOOL_NAME = 'search_code'


def _build_pruned_find_command(path: str) -> str:
    """Build a find prefix that skips generated and cache directories."""
    safe_path = shlex.quote(path)
    prune_terms = ' -o '.join(
        f'-name {shlex.quote(dir_name)}' for dir_name in _SEARCH_EXCLUDED_DIRS
    )
    return f'find {safe_path} \\( {prune_terms} \\) -prune -o'


def create_search_code_tool():
    """Create the search_code tool definition."""
    return create_tool_definition(
        name=SEARCH_CODE_TOOL_NAME,
        description=_SEARCH_CODE_DESCRIPTION,
        properties={
            'pattern': {
                'type': 'string',
                'description': (
                    'Text or regex pattern to search for. '
                    'Omit (along with file_pattern) to list files only.'
                ),
            },
            'path': {
                'type': 'string',
                'description': (
                    'Directory or file path to search in. '
                    'Defaults to the current workspace directory.'
                ),
            },
            'file_pattern': {
                'type': 'string',
                'description': (
                    'Glob pattern to restrict which files are searched '
                    "(e.g. '*.py', '**/*.ts', 'src/**/*.js'). "
                    'Leave empty to search all text files.'
                ),
            },
            'context_lines': {
                'type': 'integer',
                'description': 'Lines of context to show before and after each match (default: 2).',
            },
            'case_sensitive': {
                'type': 'string',
                'enum': ['true', 'false'],
                'description': "Whether the search is case-sensitive (default: 'false').",
            },
            'max_results': {
                'type': 'integer',
                'description': 'Maximum number of matching lines to return (default: 50).',
            },
        },
        required=[],  # all params optional; tool is flexible
    )


def build_search_code_action(
    pattern: str = '',
    path: str = '.',
    file_pattern: str = '',
    context_lines: int = 2,
    case_sensitive: str = 'false',
    max_results: int = 50,
) -> CmdRunAction:
    """Build a CmdRunAction that performs the code search.

    Tries ripgrep (rg) first since it is much faster and respects
    .gitignore automatically.  Falls back to grep -rn.

    Args:
        pattern: Regex/text pattern to search for.
        path: Directory or file to search in.
        file_pattern: Glob to restrict files.
        context_lines: Context lines around matches.
        case_sensitive: "true" or "false".
        max_results: Max results to return.

    Returns:
        CmdRunAction: The bash command action.
    """
    path = path or '.'
    context_lines = max(0, min(int(context_lines), 10))
    max_results = max(1, min(int(max_results), 500))
    is_case_sensitive = str(case_sensitive).lower() == 'true'

    if uses_powershell_terminal():
        return _build_windows_search_action(
            pattern, path, file_pattern, context_lines,
            is_case_sensitive, max_results,
        )

    if not pattern:
        # File-discovery mode: just list matching files
        find_prefix = _build_pruned_find_command(path)
        if file_pattern:
            safe_glob = shlex.quote(file_pattern)
            cmd = f'{find_prefix} -type f -name {safe_glob} -print | head -n {max_results}'
        else:
            cmd = f'{find_prefix} -type f -print | head -n {max_results}'
        label = f'Listing files in {path}' if path and path != '.' else 'Listing files'
        return CmdRunAction(command=cmd, display_label=label)

    # Search mode — build rg command with grep fallback, then wrap in structured XML
    safe_pattern = shlex.quote(pattern)
    safe_path = shlex.quote(path)

    rg_flags = [
        f'--context={context_lines}',
        f'--max-count={max_results}',
        '--line-number',
        '--no-heading',
    ]
    grep_flags = [f'-{context_lines}' if context_lines > 0 else '', '-rn']

    if not is_case_sensitive:
        rg_flags.append('--ignore-case')
        grep_flags.append('-i')

    rg_flags.extend(f'--glob=!**/{dir_name}/**' for dir_name in _SEARCH_EXCLUDED_DIRS)
    grep_flags.extend(
        ['-I', '--binary-files=without-match']
        + [
            f'--exclude-dir={shlex.quote(dir_name)}'
            for dir_name in _SEARCH_EXCLUDED_DIRS
        ]
    )

    if file_pattern:
        safe_glob = shlex.quote(file_pattern)
        rg_flags.append(f'--glob={safe_glob}')
        grep_flags.append(f'--include={safe_glob}')

    rg_flags_str = ' '.join(rg_flags)
    grep_flags_str = ' '.join(f for f in grep_flags if f)

    # Build the raw search command
    raw_search = (
        f'if command -v rg >/dev/null 2>&1; then '
        f'rg {rg_flags_str} {safe_pattern} {safe_path}; '
        f'else '
        f'grep {grep_flags_str} {safe_pattern} {safe_path} | head -n {max_results}; '
        f'fi'
    )

    # Wrap output in structured XML so the LLM can parse results unambiguously.
    # Format: <search_results pattern="..." path="...">\n...matches...\n</search_results>
    safe_pattern_display = pattern.replace('"', '\\"')
    safe_path_display = path.replace('"', '\\"')
    cmd = (
        f'echo "<search_results pattern="{safe_pattern_display}" path="{safe_path_display}">" && '
        f'( {raw_search} ) && '
        f'echo "</search_results>"'
    )
    trunc_pat = pattern[:50] + '…' if len(pattern) > 50 else pattern
    scope = f' in {path}' if path and path != '.' else ''
    return CmdRunAction(command=cmd, display_label=f'Searching for {trunc_pat!r}{scope}')


def _ps_quote(value: str) -> str:
    """Quote a PowerShell string literal safely."""
    return "'" + value.replace("'", "''") + "'"


def _build_windows_search_action(
    pattern: str,
    path: str,
    file_pattern: str,
    context_lines: int,
    is_case_sensitive: bool,
    max_results: int,
) -> CmdRunAction:
    """PowerShell-safe search / file-discovery action.

    Prefers ``rg`` when available (cross-platform), falls back to
    ``Select-String`` + ``Get-ChildItem``.
    """
    excluded = ', '.join(_ps_quote(d) for d in _SEARCH_EXCLUDED_DIRS)
    sp = _ps_quote(path)

    if not pattern:
        # --- file-discovery mode ---
        if file_pattern:
            fp = _ps_quote(file_pattern)
            cmd = (
                f"Get-ChildItem -Path {sp} -Filter {fp} -Recurse -File -ErrorAction SilentlyContinue | "
                f"Where-Object {{ $n = $_.FullName; -not (@({excluded}) | Where-Object {{ $n -like \"*\\$_\\*\" }}) }} | "
                f"ForEach-Object {{ $_.FullName }} | Select-Object -First {max_results}"
            )
        else:
            cmd = (
                f"Get-ChildItem -Path {sp} -Recurse -File -ErrorAction SilentlyContinue | "
                f"Where-Object {{ $n = $_.FullName; -not (@({excluded}) | Where-Object {{ $n -like \"*\\$_\\*\" }}) }} | "
                f"ForEach-Object {{ $_.FullName }} | Select-Object -First {max_results}"
            )
        label = f'Listing files in {path}' if path and path != '.' else 'Listing files'
        return CmdRunAction(command=cmd, display_label=label)

    # --- search mode ---
    trunc_pat = pattern[:50] + '…' if len(pattern) > 50 else pattern
    scope = f' in {path}' if path and path != '.' else ''

    # Try ripgrep first (works cross-platform)
    rg_flags = [
        f'--context={context_lines}',
        f'--max-count={max_results}',
        '--line-number',
        '--no-heading',
    ]
    if not is_case_sensitive:
        rg_flags.append('--ignore-case')
    rg_flags.extend(f'--glob=!**/{d}/**' for d in _SEARCH_EXCLUDED_DIRS)
    if file_pattern:
        rg_flags.append(f'--glob={_ps_quote(file_pattern)}')
    rg_flags_str = ' '.join(rg_flags)
    safe_pattern = _ps_quote(pattern)

    # Select-String fallback
    case_flag = '' if is_case_sensitive else ' -CaseSensitive:$false'
    fp_filter = f" -Include {_ps_quote(file_pattern)}" if file_pattern else ''

    cmd = (
        f"$rg = Get-Command rg -ErrorAction SilentlyContinue; "
        f"Write-Output '<search_results>'; "
        f"if ($rg) {{ "
        f"  rg {rg_flags_str} {safe_pattern} {sp} 2>$null "
        f"}} else {{ "
        f"  Get-ChildItem -Path {sp}{fp_filter} -Recurse -File -ErrorAction SilentlyContinue | "
        f"  Where-Object {{ $n = $_.FullName; -not (@({excluded}) | Where-Object {{ $n -like \"*\\$_\\*\" }}) }} | "
        f"  Select-String -Pattern {safe_pattern}{case_flag} -Context {context_lines} -ErrorAction SilentlyContinue | "
        f"  Select-Object -First {max_results} "
        f"}}; "
        f"Write-Output '</search_results>'"
    )
    return CmdRunAction(command=cmd, display_label=f'Searching for {trunc_pat!r}{scope}')
