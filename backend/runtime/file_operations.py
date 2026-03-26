"""File operation helpers for the runtime action execution server.

Extracted from action_execution_server.py to reduce its size and improve
maintainability. Contains: path resolution, file reading (text/binary/image/pdf/video),
file writing, file permissions, directory viewing, and the file editor execution wrapper.
"""

from __future__ import annotations

import base64
import mimetypes
import os
from typing import TYPE_CHECKING, Any

from backend.core.logger import forge_logger as logger
from backend.events.action import FileReadAction, FileWriteAction
from backend.core.enums import FileEditSource
from backend.events.observation import (
    ErrorObservation,
    FileEditObservation,
    FileReadObservation,
)
from backend.runtime.utils.files import insert_lines, read_lines
from backend.runtime.utils.test_output_summary import extract_test_summary

if TYPE_CHECKING:
    pass


def execute_file_editor(
    editor: Any,
    command: str,
    path: str,
    file_text: str | None = None,
    view_range: list[int] | None = None,
    old_str: str | None = None,
    new_str: str | None = None,
    insert_line: int | str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    enable_linting: bool = False,
    dry_run: bool = False,
) -> tuple[str, tuple[str | None, str | None]]:
    """Execute file editor command and handle exceptions."""

    insert_line, error_msg = _parse_insert_line(insert_line)
    if error_msg:
        return error_msg, (None, None)

    result = _invoke_editor(
        editor,
        command,
        path,
        file_text,
        view_range,
        old_str,
        new_str,
        insert_line,
        start_line,
        end_line,
        enable_linting,
        dry_run,
    )

    if result.error:
        return f"ERROR:\n{result.error}", (None, None)
    if not result.output:
        logger.warning("No output from file_editor for %s", path)
        return "", (None, None)

    return result.output, (result.old_content, result.new_content)


def _parse_insert_line(insert_line: int | str | None) -> tuple[int | None, str | None]:
    """Parse insert_line to integer and return (value, error_msg)."""
    if insert_line is not None and isinstance(insert_line, str):
        try:
            return int(insert_line), None
        except ValueError:
            return (
                None,
                f"ERROR:\nInvalid insert_line value: '{insert_line}'. Expected an integer.",
            )
    return insert_line, None


def _invoke_editor(
    editor: Any,
    command: str,
    path: str,
    file_text: str | None,
    view_range: list[int] | None,
    old_str: str | None,
    new_str: str | None,
    insert_line: int | None,
    start_line: int | None,
    end_line: int | None,
    enable_linting: bool,
    dry_run: bool,
) -> Any:
    """Safely invoke the editor with MISSING sentinels."""
    from backend.core.type_safety.sentinels import MISSING
    from backend.runtime.utils.file_editor import ToolError, ToolResult

    try:
        return editor(
            command=command,
            path=path,
            file_text=file_text if file_text is not None else MISSING,
            view_range=view_range,
            old_str=old_str if old_str is not None else MISSING,
            new_str=new_str if new_str is not None else MISSING,
            insert_line=insert_line,
            start_line=start_line,
            end_line=end_line,
            enable_linting=enable_linting,
            dry_run=dry_run,
        )
    except ToolError as e:
        return ToolResult(output="", error=str(e))
    except TypeError as e:
        return ToolResult(output="", error=str(e))


def truncate_large_text(value: str, max_chars: int, *, label: str) -> str:
    """Truncate large text payloads to prevent oversized event observations."""
    if max_chars <= 0 or len(value) <= max_chars:
        return value
    half = max_chars // 2
    logger.warning(
        "Truncating oversized %s payload from %s chars to %s chars",
        label,
        len(value),
        max_chars,
    )
    return value[:half] + "\n[... Truncated by Forge due to size ...]\n" + value[-half:]


# Default max chars for bash command output (configurable via env var).
_DEFAULT_MAX_CMD_OUTPUT_CHARS = 40_000

def _get_max_cmd_output_chars(max_chars: int | None) -> int:
    """Resolve max_chars from arg or env."""
    if max_chars is not None:
        return max_chars
    raw = os.environ.get("FORGE_MAX_CMD_OUTPUT_CHARS", "")
    try:
        return int(raw) if raw else _DEFAULT_MAX_CMD_OUTPUT_CHARS
    except (ValueError, TypeError):
        return _DEFAULT_MAX_CMD_OUTPUT_CHARS


def _extract_truncation_lines(
    lines: list[str], head_budget: int, tail_budget: int
) -> tuple[list[str], list[str]]:
    """Extract head and tail lines within fixed budgets."""
    head_lines: list[str] = []
    head_chars = 0
    for line in lines:
        if head_chars + len(line) > head_budget:
            break
        head_lines.append(line)
        head_chars += len(line)

    tail_lines: list[str] = []
    tail_chars = 0
    for line in reversed(lines):
        if tail_chars + len(line) > tail_budget:
            break
        tail_lines.insert(0, line)
        tail_chars += len(line)

    return head_lines, tail_lines


def truncate_cmd_output(output: str, max_chars: int | None = None) -> str:
    """Truncate bash command output with error-aware head+tail strategy.

    Unlike generic truncation, this function:
    - Preserves the first HEAD_LINES lines for command context
    - Always preserves the last TAIL_LINES lines (final status/results)
    - Extracts and surfaces any lines containing error/traceback keywords
      so the LLM sees failure information even mid-truncation
    - Prepends a [TEST_SUMMARY] block when test runner output is detected
      (P2-A: structured test result extraction)

    Args:
        output: Raw command output string.
        max_chars: Maximum number of characters to keep. Reads
            ``FORGE_MAX_CMD_OUTPUT_CHARS`` env var if not set, defaulting to
            40 000 characters (~80-120 lines for typical terminal output).

    Returns:
        Possibly-truncated output string with a clear [TRUNCATED] notice.
    """
    max_chars = _get_max_cmd_output_chars(max_chars)

    # P2-A: Prepend test summary when test output is detected (before truncation).
    test_summary = extract_test_summary(output)
    if test_summary:
        output = test_summary + "\n\n" + output

    if max_chars <= 0 or len(output) <= max_chars:
        return output

    lines = output.splitlines(keepends=True)
    total_lines = len(lines)
    head_budget = int(max_chars * 0.20)
    tail_budget = max_chars - head_budget

    head_lines, tail_lines = _extract_truncation_lines(lines, head_budget, tail_budget)

    skipped = total_lines - len(head_lines) - len(tail_lines)
    notice = (
        f"\n[FORGE: Output truncated — {skipped} lines hidden. "
        f"Showing first {len(head_lines)} lines and last {len(tail_lines)} lines]"
    )
    notice += "\n"

    logger.warning(
        "Truncated bash output from %d lines (%d chars) → head=%d tail=%d",
        total_lines,
        len(output),
        len(head_lines),
        len(tail_lines),
    )
    return "".join(head_lines) + notice + "".join(tail_lines)


def get_max_edit_observation_chars() -> int:
    """Read and validate max edit observation payload size from environment."""
    raw_value = os.environ.get("FORGE_MAX_EDIT_OBS_CHARS", "200000")
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid FORGE_MAX_EDIT_OBS_CHARS=%r; using default 200000",
            raw_value,
        )
        return 200000
    if parsed <= 0:
        logger.warning(
            "Non-positive FORGE_MAX_EDIT_OBS_CHARS=%s; using default 200000",
            parsed,
        )
        return 200000
    return parsed


def resolve_path(path: str, working_dir: str) -> str:
    """Resolve a relative or absolute path to an absolute path with security validation.

    Args:
        path: File path (relative or absolute)
        working_dir: Current working directory

    Returns:
        Absolute file path as string (validated and safe)

    """
    from backend.core.type_safety.path_validation import SafePath

    safe_path = SafePath.validate(
        path,
        workspace_root=working_dir,
        must_be_relative=True,
    )
    return str(safe_path.path)


def encode_binary_file(
    filepath: str,
    file_data: bytes,
    mime_type: str | None,
    default_mime: str,
) -> str:
    """Encode binary file data as base64 data URL."""
    encoded_data = base64.b64encode(file_data).decode("utf-8")
    effective_mime = mime_type or default_mime
    return f"data:{effective_mime};base64,{encoded_data}"


def read_image_file(filepath: str) -> FileReadObservation:
    """Read and encode an image file."""
    with open(filepath, "rb") as file:
        image_data = file.read()
        mime_type, _ = mimetypes.guess_type(filepath)
        encoded_image = encode_binary_file(filepath, image_data, mime_type, "image/png")
    return FileReadObservation(path=filepath, content=encoded_image)


def read_pdf_file(filepath: str) -> FileReadObservation:
    """Read and encode a PDF file."""
    with open(filepath, "rb") as file:
        pdf_data = file.read()
        encoded_pdf = encode_binary_file(
            filepath, pdf_data, "application/pdf", "application/pdf"
        )
    return FileReadObservation(path=filepath, content=encoded_pdf)


def read_video_file(filepath: str) -> FileReadObservation:
    """Read and encode a video file."""
    with open(filepath, "rb") as file:
        video_data = file.read()
        mime_type, _ = mimetypes.guess_type(filepath)
        encoded_video = encode_binary_file(filepath, video_data, mime_type, "video/mp4")
    return FileReadObservation(path=filepath, content=encoded_video)


def read_text_file(filepath: str, action: FileReadAction) -> FileReadObservation:
    """Read a text file with optional line range.

    Args:
        filepath: The path to the text file.
        action: The file read action with start/end line parameters.

    Returns:
        FileReadObservation: The observation with file content.

    Raises:
        IsADirectoryError: If filepath is a directory.

    """
    if os.path.isdir(filepath):
        raise IsADirectoryError(f"{filepath} is a directory, not a file")

    with open(filepath, encoding="utf-8") as f:
        all_lines = f.readlines()

    start = (action.start or 1) - 1
    end = action.end if action.end is not None else -1

    lines = read_lines(all_lines, start, end)

    return FileReadObservation(
        path=filepath,
        content="".join(lines),
    )


def handle_file_read_errors(filepath: str, working_dir: str) -> ErrorObservation:
    """Handle file reading errors with appropriate error messages."""
    if not os.path.exists(filepath):
        candidates = os.listdir(working_dir) if os.path.isdir(working_dir) else []
        hint = ""
        if candidates:
            import difflib

            matches = difflib.get_close_matches(
                os.path.basename(filepath), candidates, n=3
            )
            if matches:
                hint = f" Did you mean: {', '.join(matches)}?"
        return ErrorObservation(f"File not found: {filepath}.{hint}")
    return ErrorObservation(
        f"Cannot read file: {filepath} (permission denied or other error)"
    )


def ensure_directory_exists(filepath: str) -> None:
    """Create parent directories for a file path if they don't exist."""
    parent = os.path.dirname(filepath)
    if parent:
        os.makedirs(parent, exist_ok=True)


def write_file_content(
    filepath: str,
    action: FileWriteAction,
    file_exists: bool,
) -> ErrorObservation | None:
    """Write content to file, handling both new and existing files.

    Returns:
        ErrorObservation if write failed, None on success.
    """
    try:
        if not file_exists:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(action.content)
        else:
            with open(filepath, encoding="utf-8") as f:
                all_lines = f.readlines()

            # Match backend/runtime/utils/files.py behavior for splitting
            to_insert = action.content.split("\n")

            start = (action.start or 1) - 1
            end = action.end if action.end is not None else -1

            new_lines = insert_lines(to_insert, all_lines, start, end)

            with open(filepath, "w", encoding="utf-8") as f:
                f.writelines(new_lines)

        return None
    except Exception as e:
        return ErrorObservation(f"Failed to write file {filepath}: {e}")


def set_file_permissions(
    filepath: str,
    file_exists: bool,
    file_stat: os.stat_result | None,
) -> None:
    """Set file permissions and ownership with preservation for existing files."""
    if os.name == "nt":
        return  # Windows doesn't support chmod/chown

    if file_exists and file_stat is not None:
        try:
            os.chmod(filepath, file_stat.st_mode)
            if hasattr(os, "chown"):
                os.chown(filepath, file_stat.st_uid, file_stat.st_gid)
        except (OSError, PermissionError):
            logger.debug("Could not restore permissions for %s", filepath)
    else:
        try:
            os.chmod(filepath, 0o664)
        except (OSError, PermissionError):
            logger.debug("Could not set default permissions for %s", filepath)


def handle_directory_view(full_path: str, display_path: str) -> FileEditObservation:
    """Handle viewing a directory by listing files up to 2 levels deep."""
    # List files up to 2 levels deep
    file_list, hidden_count = _list_directory_recursive(full_path, max_depth=2)

    content = _format_directory_listing(display_path, file_list, hidden_count)

    return FileEditObservation(
        content=content,
        path=display_path,
        old_content=None,
        new_content=None,
        impl_source=FileEditSource.FILE_EDITOR,
        diff="",
    )


def _list_directory_recursive(
    dir_path: str,
    max_depth: int,
    current_depth: int = 0,
    base_path: str = "",
) -> tuple[list[str], int]:
    """Recursively list directory entries up to max_depth."""
    if current_depth >= max_depth:
        return [], 0

    entries = []
    hidden_count = 0

    try:
        for entry in os.listdir(dir_path):
            # Skip hidden files/directories (starting with .)
            if entry.startswith("."):
                hidden_count += 1
                continue

            entry_path = os.path.join(dir_path, entry)
            relative_path = os.path.join(base_path, entry) if base_path else entry

            try:
                if os.path.isdir(entry_path):
                    entries.append(relative_path + "/")
                    # Recursively list subdirectories
                    sub_entries, sub_hidden = _list_directory_recursive(
                        entry_path, max_depth, current_depth + 1, relative_path
                    )
                    entries.extend(sub_entries)
                    hidden_count += sub_hidden
                else:
                    entries.append(relative_path)
            except (OSError, ValueError):
                # Skip entries that can't be accessed
                continue
    except (OSError, PermissionError, NotADirectoryError):
        # Cannot read directory
        pass

    return entries, hidden_count


def _format_directory_listing(
    display_path: str, file_list: list[str], hidden_count: int
) -> str:
    """Format directory listing for display."""
    # Sort: directories first (with /), then files
    directories = sorted(
        [f for f in file_list if f.endswith("/")], key=lambda s: s.lower()
    )
    files = sorted(
        [f for f in file_list if not f.endswith("/")], key=lambda s: s.lower()
    )
    sorted_entries = directories + files

    display_path_normalized = display_path.replace("\\", "/")
    lines = [
        f"Here's the files and directories up to 2 levels deep in {display_path_normalized}, excluding hidden items:"
    ]

    # Include the directory itself first (with trailing slash)
    if not display_path_normalized.endswith("/"):
        lines.append(f"{display_path_normalized}/")

    # Then list entries inside the directory
    for entry in sorted_entries:
        entry_normalized = entry.replace("\\", "/")
        sep = "" if display_path_normalized.endswith("/") else "/"
        lines.append(f"{display_path_normalized}{sep}{entry_normalized}")

    if hidden_count > 0:
        lines.append("")
        lines.append(
            f"{hidden_count} hidden files/directories in this directory are excluded. You can use 'ls -la {display_path_normalized}' to see them."
        )

    return "\n".join(lines)
