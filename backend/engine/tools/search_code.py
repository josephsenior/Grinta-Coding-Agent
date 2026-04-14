"""Fast code search tool for the Orchestrator agent.

Eliminates the grep→parse→regrep cycle by providing a single
structured search interface that tries ripgrep first, then falls
back to pure Python traversal.
"""

from __future__ import annotations

from backend.engine.tools.common import create_tool_definition
from backend.engine.tools.ignore_filter import (
    get_ignore_spec,
    is_ignored_file,
    prune_ignored_dirs,
)
from backend.ledger.action import AgentThinkAction

_SEARCH_EXCLUDED_DIRS = (
    ".git",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    ".tmp_cli_manual",
    "logs",
    "storage",
    "build",
    "dist",
)

_SEARCH_CODE_DESCRIPTION = """\
Search for text patterns, symbols, or file paths in the codebase using ripgrep (falls back to Python traversal).

Modes:
1. Text/regex search — set `pattern` to a regex pattern to find matching lines inside files.
2. File discovery — omit `pattern` entirely, and set `file_pattern` to a glob pattern to list matching files.

Use this when target location is unknown. For precise symbol refs at known positions, use `lsp_query`. \
For dependency traversal, use `explore_tree_structure`.
"""

SEARCH_CODE_TOOL_NAME = "search_code"


def create_search_code_tool() -> dict:
    """Create the search_code tool definition."""
    return create_tool_definition(  # type: ignore
        name=SEARCH_CODE_TOOL_NAME,
        description=_SEARCH_CODE_DESCRIPTION,
        properties={
            "pattern": {
                "type": "string",
                "description": (
                    "Regex pattern for text search (e.g., 'function\\s+\\w+'). "
                    "Leave empty to list files only."
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
                    "Glob pattern for file filtering (e.g., '*.ts', 'src/**/*.test.js'). "
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
) -> AgentThinkAction:
    """Perform the code search directly in pure Python (with ripgrep fast-path).

    Tries ripgrep (rg) via subprocess first since it is much faster and respects
    .gitignore automatically. Falls back to pure Python traversal.
    """
    import shutil

    path = path or "."
    context_lines = max(0, min(int(context_lines), 10))
    max_results = max(1, min(int(max_results), 500))
    is_case_sensitive = str(case_sensitive).lower() == "true"

    # Auto-fix common LLM mistake where they provide `.ext` instead of `*.ext`
    if (
        file_pattern
        and not file_pattern.startswith(("*", "?", "!"))
        and file_pattern.startswith(".")
    ):
        file_pattern = f"*{file_pattern}"

    # Auto-fix where pattern is exactly a wildcard and file_pattern is empty
    import re

    if (
        pattern
        and not file_pattern
        and re.match(r"^[\w\*\.\-\?]+$", pattern)
        and pattern.startswith(("*", "?"))
    ):
        file_pattern = pattern
        pattern = ""

    # Validate regex pattern early to prevent silent failures and hallucination loops
    if pattern:
        import re

        flags = 0 if is_case_sensitive else re.IGNORECASE
        try:
            re.compile(pattern, flags)
        except re.error as e:
            return AgentThinkAction(
                source_tool="search_code",
                thought=(
                    f"<search_results>\nInvalid regex in 'pattern': {e}. "
                    "Did you mean to use 'file_pattern' for glob patterns like '*.ts'?\n</search_results>"
                ),
            )

    # 1. Fast path: Ripgrep
    rg_path = shutil.which("rg")
    if rg_path:
        return _search_with_ripgrep(
            rg_path,
            pattern,
            path,
            file_pattern,
            context_lines,
            is_case_sensitive,
            max_results,
        )

    # 2. Fallback: Pure Python
    return _search_with_python(
        pattern, path, file_pattern, context_lines, is_case_sensitive, max_results
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
        args = [rg_path, "--files"]
        for d in _SEARCH_EXCLUDED_DIRS:
            args.extend(["--glob", f"!**/{d}/**"])
        if file_pattern:
            args.extend(["--glob", file_pattern])
        args.append(path)

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            lines = result.stdout.splitlines()[:max_results]
            out = "\n".join(lines)
            if not out:
                out = "No matching files found."
            return AgentThinkAction(
                source_tool="search_code",
                thought=f"<search_results>\n{out}\n</search_results>",
            )
        except Exception as e:
            return AgentThinkAction(
                source_tool="search_code",
                thought=f"<search_results>\nError running ripgrep: {e}\n</search_results>",
            )

    # Search mode
    args = [
        rg_path,
        f"--context={context_lines}",
        f"--max-count={max_results}",
        "--line-number",
        "--no-heading",
    ]
    if not is_case_sensitive:
        args.append("--ignore-case")
    # Let ripgrep handle .gitignore naturally, but enforce a few fail-safes
    # if the user forgot them in .gitignore
    for d in [".venv", "node_modules", "__pycache__", ".git"]:
        args.extend(["--glob", f"!**/{d}/**"])
    if file_pattern:
        args.extend(["--glob", file_pattern])

    args.append(pattern)
    args.append(path)

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        out = result.stdout
        limit = max_results * (context_lines * 2 + 1) + 10
        lines = out.splitlines()[:limit]
        out_limited = "\n".join(lines)
        if not out_limited:
            out_limited = "No matches found."
        return AgentThinkAction(
            source_tool="search_code",
            thought=f"<search_results>\n{out_limited}\n</search_results>",
        )
    except Exception as e:
        return AgentThinkAction(thought=f"<search_results>\\nError running ripgrep: {e}\
</search_results>")


def _search_with_python(
    pattern: str,
    path: str,
    file_pattern: str,
    context_lines: int,
    is_case_sensitive: bool,
    max_results: int,
) -> AgentThinkAction:
    """Execute search using pure Python standard library."""
    import fnmatch
    import os
    import re

    if not os.path.exists(path):
        return AgentThinkAction(
            source_tool="search_code",
            thought=f"<search_results>\nPath does not exist: {path}\n</search_results>",
        )

    results = []

    # Compile regex if pattern provided
    regex = None
    if pattern:
        flags = 0 if is_case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return AgentThinkAction(
                source_tool="search_code",
                thought=f"<search_results>\nInvalid regex pattern: {e}\n</search_results>",
            )

    # Setup spec using a directory root.
    # If `path` is a file, build ignores from its parent directory.
    spec_root = path if os.path.isdir(path) else os.path.dirname(path) or "."
    spec = get_ignore_spec(spec_root)

    # Collect files
    target_files = []
    if os.path.isfile(path):
        current_root = os.path.dirname(path) or "."
        if not is_ignored_file(spec_root, current_root, os.path.basename(path), spec):
            target_files.append(path)
    else:
        for root, dirs, files in os.walk(path):
            # Prune excluded dirs via pathspec
            prune_ignored_dirs(spec_root, root, dirs, spec)

            for f in files:
                if is_ignored_file(spec_root, root, f, spec):
                    continue
                file_path = os.path.join(root, f)
                if file_pattern:
                    rel_path = os.path.relpath(file_path, spec_root).replace(
                        os.path.sep, "/"
                    )
                    if not fnmatch.fnmatch(f, file_pattern) and not fnmatch.fnmatch(
                        rel_path, file_pattern
                    ):
                        continue
                target_files.append(file_path)

    if not pattern:
        # File discovery mode
        lines = target_files[:max_results]
        out = "\n".join(lines)
        if not out:
            out = "No matching files found."
        return AgentThinkAction(thought=f"<search_results>\\n{out}\
</search_results>")

    # Search mode
    match_count = 0
    for fpath in target_files:
        if match_count >= max_results:
            break

        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:  # type: ignore
                lines = f.readlines()  # type: ignore
        except OSError:
            continue

        file_matches = []
        for i, line in enumerate(lines):
            if regex.search(line):  # type: ignore
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)

                # Format match block
                block = []
                for j in range(start, end):
                    prefix = f"{j+1}:" if j == i else f"{j+1}-"
                    block.append(f"{fpath}:{prefix}{lines[j].rstrip()}")
                file_matches.append("\n".join(block))

                match_count += 1
                if match_count >= max_results:
                    break

        if file_matches:
            results.extend(file_matches)
            results.append("--")

    out = "\n".join(results)
    if not out:
        out = "No matches found."
    return AgentThinkAction(thought=f"<search_results>\\n{out}\
</search_results>")
