"""Runtime-aware file resolution and read/write utilities for runtimes."""

import os
from pathlib import Path

from backend.events.observation import (
    ErrorObservation,
    FileReadObservation,
    FileWriteObservation,
    Observation,
)


def resolve_path(
    file_path: str,
    working_directory: str,
    workspace_root: str,
) -> Path:
    """Resolve a file path to a path on the host filesystem.

    For local execution, this ensures the path is within the workspace_root.

    Args:
        file_path: The path to resolve.
        working_directory: The working directory of the agent.
        workspace_root: The root directory of the workspace.

    Returns:
        Path: The resolved path on the host filesystem.

    Raises:
        PermissionError: If the resolved path is outside the allowed workspace directory.

    """
    # Convert to path and make absolute if needed
    p = Path(file_path)
    if not p.is_absolute():
        p = Path(working_directory) / p

    # Normalize the path
    abs_path = p.resolve()
    root_path = Path(workspace_root).resolve()

    # Validate path access
    try:
        if not abs_path.is_relative_to(root_path):
            msg = f"File access not permitted: {file_path}"
            raise PermissionError(msg)
    except (ValueError, AttributeError) as exc:
        # Fallback check for older Python versions or when paths are on different drives
        if not str(abs_path).startswith(str(root_path)):
            msg = f"File access not permitted: {file_path}"
            raise PermissionError(msg) from exc

    return abs_path


def read_lines(all_lines: list[str], start: int = 0, end: int = -1) -> list[str]:
    """Read a subset of lines from a list of lines.

    Args:
        all_lines: The complete list of lines to read from.
        start: Starting line index (inclusive).
        end: Ending line index (exclusive), -1 for all remaining lines.

    Returns:
        list[str]: The requested subset of lines.

    """
    start = max(start, 0)
    if end == -1:
        return all_lines[start:]

    end = max(start, end)
    return all_lines[start:end]


async def read_file(
    path: str,
    workdir: str,
    workspace_root: str,
    start: int = 0,
    end: int = -1,
) -> Observation:
    """Read file content with optional line range.

    Resolves path and reads file content, handling various error conditions.

    Args:
        path: File path to read
        workdir: Current working directory
        workspace_root: Workspace root path
        start: Starting line number (0-indexed)
        end: Ending line number (-1 for end of file)

    Returns:
        FileReadObservation with content or ErrorObservation on failure

    """
    try:
        whole_path = resolve_path(path, workdir, workspace_root)
    except PermissionError:
        return ErrorObservation(
            f"You're not allowed to access this path: {path}. You can only access paths inside the workspace.",
        )
    try:
        with open(whole_path, encoding="utf-8") as file:
            lines = read_lines(file.readlines(), start, end)
    except FileNotFoundError:
        return ErrorObservation(f"File not found: {path}")
    except UnicodeDecodeError:
        return ErrorObservation(f"File could not be decoded as utf-8: {path}")
    except IsADirectoryError:
        return ErrorObservation(f"Path is a directory: {path}. You can only read files")
    code_view = "".join(lines)
    return FileReadObservation(path=path, content=code_view)


def insert_lines(
    to_insert: list[str], original: list[str], start: int = 0, end: int = -1
) -> list[str]:
    """Insert the new content to the original content based on start and end."""
    new_lines = [""] if start == 0 else original[:start]
    new_lines += [i + "\n" for i in to_insert]
    new_lines += [""] if end == -1 else original[end:]
    return new_lines


async def write_file(
    path: str,
    workdir: str,
    workspace_root: str,
    content: str,
    start: int = 0,
    end: int = -1,
) -> Observation:
    """Write content to file with optional line range insertion.

    Resolves path and writes content, optionally inserting at specific line range.

    Args:
        path: File path to write
        workdir: Current working directory
        workspace_root: Workspace root path
        content: Content to write
        start: Starting line number for insertion (0-indexed)
        end: Ending line number for insertion (-1 for append)

    Returns:
        FileWriteObservation on success or ErrorObservation on failure

    """
    insert = content.split("\n")
    try:
        whole_path = resolve_path(path, workdir, workspace_root)
        if not os.path.exists(os.path.dirname(whole_path)):
            os.makedirs(os.path.dirname(whole_path))
        mode = "r+" if os.path.exists(whole_path) else "w"
        try:
            with open(whole_path, mode, encoding="utf-8") as file:
                if mode != "w":
                    all_lines = file.readlines()
                    new_file = insert_lines(insert, all_lines, start, end)
                else:
                    new_file = [i + "\n" for i in insert]
                file.seek(0)
                file.writelines(new_file)
                file.truncate()
        except FileNotFoundError:
            return ErrorObservation(f"File not found: {path}")
        except IsADirectoryError:
            return ErrorObservation(
                f"Path is a directory: {path}. You can only write to files"
            )
        except UnicodeDecodeError:
            return ErrorObservation(f"File could not be decoded as utf-8: {path}")
    except PermissionError as e:
        return ErrorObservation(f"Permission error on {path}: {e}")
    return FileWriteObservation(content="", path=path)
