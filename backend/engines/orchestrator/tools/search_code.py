"""Fast code search tool for the CodeAct agent.

Eliminates the grep→parse→regrep cycle by providing a single
structured search interface that tries ripgrep first, then falls
back to grep.
"""

from __future__ import annotations

import shlex

from backend.engines.orchestrator.tools.common import create_tool_definition
from backend.events.action import CmdRunAction

_SEARCH_CODE_DESCRIPTION = """\
Search for text patterns, symbols, or file paths in the codebase.

Use this instead of execute_bash + grep when you need to:
- Find all usages of a function, class, or variable
- Locate files containing a specific string or pattern
- Discover which files match a glob pattern
- Find error messages or log strings

MODES:

1. **Text / regex search** (default) — finds lines matching `pattern` across files.
   - Tries ripgrep (`rg`) first, falls back to `grep -rn`
   - Results format: `file:line: matched line` with N context lines before/after
   - Supports full regex syntax (Python/Perl-compatible)

2. **File discovery** — omit `pattern`, set `file_pattern` only — lists files matching the glob.

PARAMETERS:
- `pattern` — regex/text to search (omit to just list matching files)
- `path` — directory or file to search in (default: current directory)
- `file_pattern` — glob to restrict which files are searched (e.g. `*.py`, `**/*.ts`, `src/**`)
- `context_lines` — lines of context before/after each match (default: 2)
- `case_sensitive` — "true" or "false" (default: "false" — case-insensitive)
- `max_results` — cap on returned matches (default: 50; increase if needed)

EXAMPLES:
- Find all callers of `process_data`:  pattern="process_data", file_pattern="*.py"
- Find TODO comments: pattern="TODO|FIXME|HACK", file_pattern="*.py"
- Find all TypeScript files in src/: path="src/", file_pattern="*.ts" (no pattern)
- Find imports of a module: pattern="from backend.llm import", case_sensitive="true"
"""

SEARCH_CODE_TOOL_NAME = "search_code"


def create_search_code_tool():
    """Create the search_code tool definition."""
    return create_tool_definition(
        name=SEARCH_CODE_TOOL_NAME,
        description=_SEARCH_CODE_DESCRIPTION,
        properties={
            "pattern": {
                "type": "string",
                "description": (
                    "Text or regex pattern to search for. "
                    "Omit (along with file_pattern) to list files only."
                ),
            },
            "path": {
                "type": "string",
                "description": (
                    "Directory or file path to search in. "
                    "Defaults to the current workspace directory."
                ),
            },
            "file_pattern": {
                "type": "string",
                "description": (
                    "Glob pattern to restrict which files are searched "
                    "(e.g. '*.py', '**/*.ts', 'src/**/*.js'). "
                    "Leave empty to search all text files."
                ),
            },
            "context_lines": {
                "type": "integer",
                "description": "Lines of context to show before and after each match (default: 2).",
            },
            "case_sensitive": {
                "type": "string",
                "enum": ["true", "false"],
                "description": "Whether the search is case-sensitive (default: 'false').",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of matching lines to return (default: 50).",
            },
        },
        required=[],  # all params optional; tool is flexible
    )


def build_search_code_action(
    pattern: str = "",
    path: str = ".",
    file_pattern: str = "",
    context_lines: int = 2,
    case_sensitive: str = "false",
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
    path = path or "."
    context_lines = max(0, min(int(context_lines), 10))
    max_results = max(1, min(int(max_results), 500))
    is_case_sensitive = str(case_sensitive).lower() == "true"

    if not pattern:
        # File-discovery mode: just list matching files
        if file_pattern:
            safe_path = shlex.quote(path)
            safe_glob = shlex.quote(file_pattern)
            cmd = f"find {safe_path} -type f -name {safe_glob} | head -n {max_results}"
        else:
            safe_path = shlex.quote(path)
            cmd = f"find {safe_path} -type f | head -n {max_results}"
        return CmdRunAction(command=cmd)

    # Search mode — build rg command with grep fallback, then wrap in structured XML
    safe_pattern = shlex.quote(pattern)
    safe_path = shlex.quote(path)

    rg_flags = [f"--context={context_lines}", f"--max-count={max_results}", "--line-number", "--no-heading"]
    grep_flags = [f"-{context_lines}" if context_lines > 0 else "", "-rn"]

    if not is_case_sensitive:
        rg_flags.append("--ignore-case")
        grep_flags.append("-i")

    if file_pattern:
        safe_glob = shlex.quote(file_pattern)
        rg_flags.append(f"--glob={safe_glob}")
        grep_flags.append(f"--include={safe_glob}")

    rg_flags_str = " ".join(rg_flags)
    grep_flags_str = " ".join(f for f in grep_flags if f)

    # Build the raw search command
    raw_search = (
        f"if command -v rg >/dev/null 2>&1; then "
        f"rg {rg_flags_str} {safe_pattern} {safe_path}; "
        f"else "
        f"grep {grep_flags_str} {safe_pattern} {safe_path} | head -n {max_results}; "
        f"fi"
    )

    # Wrap output in structured XML so the LLM can parse results unambiguously.
    # Format: <search_results pattern="..." path="...">\n...matches...\n</search_results>
    safe_pattern_display = pattern.replace('"', '\\"')
    safe_path_display = path.replace('"', '\\"')
    cmd = (
        f'echo "<search_results pattern=\"{safe_pattern_display}\" path=\"{safe_path_display}\">" && '
        f'( {raw_search} ) && '
        f'echo "</search_results>"'
    )
    return CmdRunAction(command=cmd)
