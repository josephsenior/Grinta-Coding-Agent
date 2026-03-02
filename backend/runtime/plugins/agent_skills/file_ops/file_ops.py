"""File operations module for Forge agent.

This module provides a collection of file manipulation skills that enable the Forge
agent to perform various file operations such as opening, searching, and navigating
through files and directories.

Functions:
- open_file(path: str, line_number: int | None = 1, context_lines: int = 100): Opens a file and optionally moves to a specific line.
- goto_line(line_number: int): Moves the window to show the specified line number.
- scroll_down(): Moves the window down by the number of lines specified in WINDOW.
- scroll_up(): Moves the window up by the number of lines specified in WINDOW.
- search_dir(search_term: str, dir_path: str = './'): Searches for a term in all files in the specified directory.
- search_file(search_term: str, file_path: str | None = None): Searches for a term in the specified file or the currently open file.
- find_file(file_name: str, dir_path: str = './'): Finds all files with the given name in the specified directory.

Note:
    All functions return string representations of their results.

"""

from __future__ import annotations

import os

from backend.code_quality import DefaultLinter, LintResult

CURRENT_FILE: str | None = None
CURRENT_LINE = 1
WINDOW = 100
MSG_FILE_UPDATED = "[File updated (edited at line {line_number}). Please review the changes and make sure they are correct (correct indentation, no duplicate lines, etc). Edit the file again if necessary.]"
LINTER_ERROR_MSG = "[Your proposed edit has introduced new syntax error(s). Please understand the errors and retry your edit command.]\n"


def _output_error(error_msg: str) -> bool:
    """Emit a standardized error message."""
    print(f"ERROR: {error_msg}")
    return False


def _is_valid_filename(file_name: str) -> bool:
    if not file_name or not isinstance(file_name, str) or (not file_name.strip()):
        return False
    invalid_chars = '<>:"/\\|?*'
    if os.name == "nt":
        invalid_chars = '<>:"/\\|?*'
    elif os.name == "posix":
        invalid_chars = "\x00"
    return all(char not in file_name for char in invalid_chars)


def _is_valid_path(path: str) -> bool:
    if not path or not isinstance(path, str):
        return False
    try:
        return os.path.exists(os.path.normpath(path))
    except PermissionError:
        return False


def _create_paths(file_name: str) -> bool:
    try:
        if dirname := os.path.dirname(file_name):
            os.makedirs(dirname, exist_ok=True)
        return True
    except PermissionError:
        return False


def _check_current_file(file_path: str | None = None) -> bool:
    global CURRENT_FILE
    if not file_path:
        file_path = CURRENT_FILE
    if not file_path or not os.path.isfile(file_path):
        return _output_error("No file open. Use the open_file function first.")
    return True


def _clamp(value: int, min_value: int, max_value: int) -> int:
    return max(min_value, min(value, max_value))


def _lint_file(file_path: str) -> tuple[str | None, int | None]:
    """Perform linting on a file and identify the first error location.

    Lint the file at the given path and return a tuple with a boolean indicating if there are errors,
    and the line number of the first error, if any.

    Args:
        file_path: str: The path to the file to lint.

    Returns:
    A tuple containing:
        - The lint error message if found, None otherwise
        - The line number of the first error, None if no errors

    """
    linter = DefaultLinter()
    lint_result: LintResult = linter.lint(file_path)
    if not lint_result.errors:
        return (None, None)
    first_error_line = lint_result.errors[0].line if lint_result.errors else None
    error_text = "ERRORS:\n" + "\n".join(
        [
            f"{file_path}:{err.line}:{err.column}: {err.message}"
            for err in lint_result.errors
        ]
    )
    return (error_text, first_error_line)


def _read_file_content(file_path: str) -> list[str]:
    """Read file content and return as list of lines.

    Args:
        file_path: Path to the file to read.

    Returns:
        list[str]: List of file lines.

    """
    with open(file_path, encoding="utf-8") as file:
        content = file.read()
        if not content.endswith("\n"):
            content += "\n"
        return content.splitlines(True)


def _calculate_window_bounds(
    current_line: int, total_lines: int, window: int, ignore_window: bool
) -> tuple[int, int]:
    """Calculate the start and end bounds for the window display.

    Args:
        current_line: The current line number.
        total_lines: Total number of lines in the file.
        window: Window size for display.
        ignore_window: Whether to ignore window centering.

    Returns:
        tuple[int, int]: Start and end line numbers for the window.

    """
    half_window = max(1, window // 2)

    if ignore_window:
        start = max(1, current_line)
        end = min(total_lines, current_line + window)
    else:
        start = max(1, current_line - half_window)
        end = min(total_lines, current_line + half_window)

    # Adjust bounds to show full window when possible
    if start == 1:
        end = min(total_lines, start + window - 1)
    if end == total_lines:
        start = max(1, end - window + 1)

    return start, end


def _format_window_output(
    lines: list[str], start: int, end: int, total_lines: int
) -> str:
    """Format the window output with line numbers and context indicators.

    Args:
        lines: List of file lines.
        start: Start line number.
        end: End line number.
        total_lines: Total number of lines in file.

    Returns:
        str: Formatted output string.

    """
    output = ""

    # Add header
    if start > 1:
        output += f"({start - 1} more lines above)\n"
    else:
        output += "(this is the beginning of the file)\n"

    # Add line content
    for i in range(start, end + 1):
        new_line = f"{i}|{lines[i - 1]}"
        if not new_line.endswith("\n"):
            new_line += "\n"
        output += new_line

    # Add footer
    if end < total_lines:
        output += f"({total_lines - end} more lines below)\n"
    else:
        output += "(this is the end of the file)\n"

    return output.rstrip()


def _print_window(
    file_path: str | None,
    targeted_line: int,
    window: int,
    return_str: bool = False,
    ignore_window: bool = False,
) -> str:
    """Print or return a window of lines from a file around the targeted line.

    Args:
        file_path: Path to the file to display.
        targeted_line: Line number to center the window around.
        window: Number of lines to show in the window.
        return_str: Whether to return the output as string instead of printing.
        ignore_window: Whether to ignore window centering.

    Returns:
        str: Empty string if printed, or the formatted output if return_str is True.

    """
    global CURRENT_LINE

    if not _check_current_file(file_path) or file_path is None:
        return ""

    # Read file content
    lines = _read_file_content(file_path)
    total_lines = len(lines)
    CURRENT_LINE = _clamp(targeted_line, 1, total_lines)

    # Calculate window bounds
    start, end = _calculate_window_bounds(
        CURRENT_LINE, total_lines, window, ignore_window
    )

    # Format and output
    output = _format_window_output(lines, start, end, total_lines)

    if return_str:
        return output
    if not output.endswith("\n"):
        output += "\n"
    print(output, end="")
    return ""


def _cur_file_header(current_file: str | None, total_lines: int) -> str:
    if not current_file:
        return ""
    return f"[File: {os.path.abspath(current_file)} ({total_lines} lines total)]\n"


def _validate_line_number(
    line_number: int | None, total_lines: int
) -> bool:
    """Validate line_number for open_file. Returns False and outputs error if invalid."""
    if not isinstance(line_number, int) or line_number < 1 or line_number > total_lines:
        _output_error(f"Line number must be between 1 and {total_lines}.")
        return False
    return True


def open_file(
    path: str, line_number: int | None = 1, context_lines: int | None = None
) -> None:
    """Opens a file in the editor and optionally positions at a specific line.

    The function displays a limited window of content, centered around the specified line
    number if provided. To view the complete file content, the agent should use scroll_down and scroll_up
    commands iteratively.

    Args:
        path: The path to the file to open. Absolute path is recommended.
        line_number: The target line number to center the view on (if possible).
            Defaults to 1.
        context_lines: Maximum number of lines to display in the view window.
            Limited to 100 lines. Defaults to 100.

    """
    global CURRENT_FILE, CURRENT_LINE, WINDOW
    context_lines = context_lines if context_lines is not None and context_lines >= 1 else WINDOW
    abs_path = os.path.abspath(path)
    if not os.path.isfile(path):
        _output_error(f"File {path} not found.")
        return
    with open(abs_path, encoding="utf-8") as file:
        total_lines = max(1, sum(1 for _ in file))
    if not _validate_line_number(line_number, total_lines):
        return
    CURRENT_FILE = abs_path
    CURRENT_LINE = line_number or 1
    output = _cur_file_header(CURRENT_FILE, total_lines)
    output += _print_window(
        CURRENT_FILE,
        CURRENT_LINE,
        _clamp(context_lines, 1, 100),
        return_str=True,
        ignore_window=False,
    )
    if output.strip().endswith("more lines below)"):
        output += "\n[Use `scroll_down` to view the next 100 lines of the file!]"
    if not output.endswith("\n"):
        output += "\n"
    print(output, end="")


def goto_line(line_number: int) -> None:
    """Moves the window to show the specified line number.

    Args:
        line_number: int: The line number to move to.

    """
    global CURRENT_FILE, CURRENT_LINE, WINDOW
    if not _check_current_file():
        return
    assert CURRENT_FILE is not None
    with open(CURRENT_FILE, encoding="utf-8") as file:
        total_lines = max(1, sum(1 for _ in file))
    if not isinstance(line_number, int) or line_number < 1 or line_number > total_lines:
        _output_error(f"Line number must be between 1 and {total_lines}.")
        return
    CURRENT_LINE = _clamp(line_number, 1, total_lines)
    output = _cur_file_header(CURRENT_FILE, total_lines)
    output += _print_window(
        CURRENT_FILE, CURRENT_LINE, WINDOW, return_str=True, ignore_window=False
    )
    if not output.endswith("\n"):
        output += "\n"
    print(output, end="")


def scroll_down() -> None:
    """Moves the window down by 100 lines.

    Args:
        None

    """
    global CURRENT_FILE, CURRENT_LINE, WINDOW
    if not _check_current_file():
        return
    assert CURRENT_FILE is not None
    with open(CURRENT_FILE, encoding="utf-8") as file:
        total_lines = max(1, sum(1 for _ in file))
    CURRENT_LINE = _clamp(CURRENT_LINE + WINDOW, 1, total_lines)
    output = _cur_file_header(CURRENT_FILE, total_lines)
    output += _print_window(
        CURRENT_FILE, CURRENT_LINE, WINDOW, return_str=True, ignore_window=True
    )
    if not output.endswith("\n"):
        output += "\n"
    print(output, end="")


def scroll_up() -> None:
    """Moves the window up by 100 lines.

    Args:
        None

    """
    global CURRENT_FILE, CURRENT_LINE, WINDOW
    if not _check_current_file():
        return
    assert CURRENT_FILE is not None
    with open(CURRENT_FILE, encoding="utf-8") as file:
        total_lines = max(1, sum(1 for _ in file))
    CURRENT_LINE = _clamp(CURRENT_LINE - WINDOW, 1, total_lines)
    output = _cur_file_header(CURRENT_FILE, total_lines)
    output += _print_window(
        CURRENT_FILE, CURRENT_LINE, WINDOW, return_str=True, ignore_window=True
    )
    if not output.endswith("\n"):
        output += "\n"
    print(output, end="")


class LineNumberError(Exception):
    """Error raised when a requested line number is invalid or missing."""


def search_dir(search_term: str, dir_path: str = "./") -> None:
    """Searches for search_term in all files in dir.

    Args:
        search_term: The term to search for
        dir_path: The path to the directory to search

    """
    if not os.path.isdir(dir_path):
        _output_error(f"Directory {dir_path} not found")
        return

    matches = _find_matches_in_directory(search_term, dir_path)
    _print_search_results(search_term, dir_path, matches)


def _find_matches_in_directory(
    search_term: str, dir_path: str
) -> list[tuple[str, int, str]]:
    """Find all matches of search term in directory.

    Args:
        search_term: Term to search for
        dir_path: Directory to search in

    Returns:
        List of (file_path, line_num, line_content) tuples

    """
    matches: list[tuple[str, int, str]] = []

    for root, _, files in os.walk(dir_path):
        for file in files:
            if file.startswith("."):
                continue

            file_path = os.path.join(root, file)
            matches.extend(_search_file_for_term(file_path, search_term))

    return matches


def _search_file_for_term(
    file_path: str, search_term: str
) -> list[tuple[str, int, str]]:
    """Search a single file for search term.

    Args:
        file_path: Path to file
        search_term: Term to search for

    Returns:
        List of (file_path, line_num, line_content) tuples

    """
    matches: list[tuple[str, int, str]] = []
    try:
        with open(file_path, errors="ignore", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                if search_term in line:
                    matches.append((file_path, line_num, line.strip()))
    except Exception:
        # Silently skip files that can't be read
        pass

    return matches


def _print_search_results(
    search_term: str, dir_path: str, matches: list[tuple[str, int, str]]
) -> None:
    """Print search results to console.

    Args:
        search_term: Search term used
        dir_path: Directory searched
        matches: List of matches found

    """
    if not matches:
        print(f'No matches found for "{search_term}" in {dir_path}')
        return

    num_files = len({match[0] for match in matches})
    if num_files >= 999:
        print(
            f'More than 999 files matched for "{search_term}" in {dir_path}. Please narrow your search.'
        )
        return

    print(f'[Found {len(matches)} matches for "{search_term}" in {dir_path}]')
    for file_path, line_num, line in matches:
        print(f"{file_path} (Line {line_num}): {line}")
    print(f'[End of matches for "{search_term}" in {dir_path}]')


def search_file(search_term: str, file_path: str | None = None) -> None:
    """Searches for search_term in file. If file is not provided, searches in the current open file.

    Args:
        search_term: The term to search for.
        file_path: The path to the file to search.

    """
    global CURRENT_FILE
    if file_path is None:
        file_path = CURRENT_FILE
    if file_path is None:
        _output_error("No file specified or open. Use the open_file function first.")
        return
    if not os.path.isfile(file_path):
        _output_error(f"File {file_path} not found.")
        return
    matches: list[tuple[int, str]] = []
    with open(file_path, encoding="utf-8") as file:
        for i, line in enumerate(file, 1):
            if search_term in line:
                matches.append((i, line.strip()))
    if matches:
        print(f'[Found {len(matches)} matches for "{search_term}" in {file_path}]')
        for line_num, line in matches:
            print(f"Line {line_num}: {line}")
        print(f'[End of matches for "{search_term}" in {file_path}]')
    else:
        print(f'[No matches found for "{search_term}" in {file_path}]')


def find_file(file_name: str, dir_path: str = "./") -> None:
    """Finds all files with the given name in the specified directory.

    Args:
        file_name: str: The name of the file to find.
        dir_path: str: The path to the directory to search.

    """
    if not os.path.isdir(dir_path):
        _output_error(f"Directory {dir_path} not found")
        return
    matches: list[str] = []
    for root, _, files in os.walk(dir_path):
        matches.extend(os.path.join(root, file) for file in files if file_name in file)
    if matches:
        print(f'[Found {len(matches)} matches for "{file_name}" in {dir_path}]')
        for match in matches:
            print(match)
        print(f'[End of matches for "{file_name}" in {dir_path}]')
    else:
        print(f'[No matches found for "{file_name}" in {dir_path}]')
