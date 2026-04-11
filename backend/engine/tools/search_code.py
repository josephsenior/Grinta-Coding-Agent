"""Fast code search tool for the Orchestrator agent.

Eliminates the grep→parse→regrep cycle by providing a single
structured search interface that tries ripgrep first, then falls
back to pure Python traversal.
"""

from __future__ import annotations

from backend.engine.tools.common import create_tool_definition
from backend.ledger.action import AgentThinkAction

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
Search for text patterns, symbols, or file paths in the codebase using ripgrep (falls back to Python traversal).

Modes:
1. Text/regex search — set `pattern` to find matching lines across files.
2. File discovery — omit `pattern`, set `file_pattern` only to list matching files.

Use this when target location is unknown. For precise symbol refs at known positions, use `lsp_query`. \
For dependency traversal, use `explore_tree_structure`.
"""

SEARCH_CODE_TOOL_NAME = 'search_code'

def create_search_code_tool() -> dict:
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
) -> AgentThinkAction:
    """Perform the code search directly in pure Python (with ripgrep fast-path).

    Tries ripgrep (rg) via subprocess first since it is much faster and respects
    .gitignore automatically. Falls back to pure Python traversal.
    """
    import shutil

    path = path or '.'
    context_lines = max(0, min(int(context_lines), 10))
    max_results = max(1, min(int(max_results), 500))
    is_case_sensitive = str(case_sensitive).lower() == 'true'
    
    # 1. Fast path: Ripgrep
    rg_path = shutil.which('rg')
    if rg_path:
        return _search_with_ripgrep(
            rg_path, pattern, path, file_pattern, context_lines, 
            is_case_sensitive, max_results
        )
    
    # 2. Fallback: Pure Python
    return _search_with_python(
        pattern, path, file_pattern, context_lines, 
        is_case_sensitive, max_results
    )

def _search_with_ripgrep(
    rg_path: str,
    pattern: str,
    path: str,
    file_pattern: str,
    context_lines: int,
    is_case_sensitive: bool,
    max_results: int,
) -> AgentThinkAction:
    """Execute ripgrep directly via subprocess."""
    import subprocess
    
    if not pattern:
        # File discovery mode
        args = [rg_path, '--files']
        for d in _SEARCH_EXCLUDED_DIRS:
            args.extend(['--glob', f'!**/{d}/**'])
        if file_pattern:
            args.extend(['--glob', file_pattern])
        args.append(path)
        
        try:
            result = subprocess.run(args, capture_output=True, text=True, check=False)
            lines = result.stdout.splitlines()[:max_results]
            out = '\\n'.join(lines)
            if not out:
                out = "No matching files found."
            return AgentThinkAction(thought=f'<search_results>\\n{out}\\n</search_results>')
        except Exception as e:
            return AgentThinkAction(thought=f'<search_results>\\nError running ripgrep: {e}\\n</search_results>')

    # Search mode
    args = [
        rg_path,
        f'--context={context_lines}',
        f'--max-count={max_results}',
        '--line-number',
        '--no-heading',
    ]
    if not is_case_sensitive:
        args.append('--ignore-case')
    for d in _SEARCH_EXCLUDED_DIRS:
        args.extend(['--glob', f'!**/{d}/**'])
    if file_pattern:
        args.extend(['--glob', file_pattern])
        
    args.append(pattern)
    args.append(path)
    
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        out = result.stdout
        limit = max_results * (context_lines * 2 + 1) + 10
        lines = out.splitlines()[:limit]
        out_limited = '\\n'.join(lines)
        if not out_limited:
            out_limited = "No matches found."
        return AgentThinkAction(thought=f'<search_results>\\n{out_limited}\\n</search_results>')
    except Exception as e:
         return AgentThinkAction(thought=f'<search_results>\\nError running ripgrep: {e}\\n</search_results>')


def _search_with_python(
    pattern: str,
    path: str,
    file_pattern: str,
    context_lines: int,
    is_case_sensitive: bool,
    max_results: int,
) -> AgentThinkAction:
    """Execute search using pure Python standard library."""
    import os
    import re
    import fnmatch
    
    if not os.path.exists(path):
        return AgentThinkAction(thought=f"<search_results>\\nPath does not exist: {path}\\n</search_results>")
        
    results = []
    
    # Compile regex if pattern provided
    regex = None
    if pattern:
        flags = 0 if is_case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return AgentThinkAction(thought=f"<search_results>\\nInvalid regex pattern: {e}\\n</search_results>")

    # Collect files
    target_files = []
    if os.path.isfile(path):
        target_files.append(path)
    else:
        for root, dirs, files in os.walk(path):
            # Prune excluded dirs
            dirs[:] = [d for d in dirs if d not in _SEARCH_EXCLUDED_DIRS]
            for f in files:
                if file_pattern and not fnmatch.fnmatch(f, file_pattern):
                    continue
                file_path = os.path.join(root, f)
                target_files.append(file_path)

    if not pattern:
        # File discovery mode
        lines = target_files[:max_results]
        out = '\\n'.join(lines)
        if not out:
            out = "No matching files found."
        return AgentThinkAction(thought=f'<search_results>\\n{out}\\n</search_results>')
        
    # Search mode
    match_count = 0
    for fpath in target_files:
        if match_count >= max_results:
            break
            
        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
        except OSError:
            continue
            
        file_matches = []
        for i, line in enumerate(lines):
            if regex.search(line):
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)
                
                # Format match block
                block = []
                for j in range(start, end):
                    prefix = f"{j+1}:" if j == i else f"{j+1}-"
                    block.append(f"{fpath}:{prefix}{lines[j].rstrip()}")
                file_matches.append('\\n'.join(block))
                
                match_count += 1
                if match_count >= max_results:
                    break
                    
        if file_matches:
            results.extend(file_matches)
            results.append("--")
            
    out = '\\n'.join(results)
    if not out:
        out = "No matches found."
    return AgentThinkAction(thought=f'<search_results>\\n{out}\\n</search_results>')
