"""Production-grade diff generation utilities.

Provides advanced unified diff generation with proper formatting, context lines,
and intelligent hunk detection. Designed for production use in agent runtime environments.
"""

from __future__ import annotations

import difflib


def get_diff(
    old: str,
    new: str,
    path: str | None = None,
    context_lines: int = 3,
    ignore_whitespace: bool = False,
) -> str:
    r"""Generate a unified diff between two text strings."""
    # Detect binary files
    binary_msg = _check_binary(old, new, path)
    if binary_msg:
        return binary_msg

    old_lines, new_lines = _prepare_diff_lines(old, new, ignore_whitespace)

    # Generate unified diff
    diff_generator = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=path or "old",
        tofile=path or "new",
        lineterm="",
        n=context_lines,
    )

    # Convert generator to list and filter out empty diffs
    diff_lines = list(diff_generator)
    if not diff_lines or len(diff_lines) <= 2:
        return ""

    return _finalize_diff_text(diff_lines)


def _prepare_diff_lines(
    old: str, new: str, ignore_whitespace: bool
) -> tuple[list[str], list[str]]:
    """Normalize and split input text into lines for diffing."""
    old_lines = old.splitlines(keepends=True) if old else []
    new_lines = new.splitlines(keepends=True) if new else []

    if ignore_whitespace:
        old_lines = [_normalize_whitespace(line) for line in old_lines]
        new_lines = [_normalize_whitespace(line) for line in new_lines]

    return old_lines, new_lines


def _finalize_diff_text(diff_lines: list[str]) -> str:
    """Join diff lines and ensure proper trailing newline."""
    diff_text = "\n".join(diff_lines)
    if not diff_text.endswith("\n"):
        diff_text += "\n"
    return diff_text


def _check_binary(old: str, new: str, path: str | None) -> str | None:
    """Detect binary files or content."""
    import mimetypes

    if path:
        mime_type, _ = mimetypes.guess_type(path)
        if mime_type and not mime_type.startswith(
            ("text/", "application/json", "application/xml")
        ):
            return f"Binary file {path} - diff not available\n"

    # Check for binary content
    if _is_binary(old) or _is_binary(new):
        return f"Binary content detected - diff not available for {path or 'file'}\n"

    return None


def _is_binary(content: str) -> bool:
    """Check if content appears to be binary.

    Args:
        content: Content string to check

    Returns:
        True if content appears to be binary, False otherwise
    """
    if not content:
        return False

    # Check for null bytes (strong indicator of binary)
    if "\x00" in content:
        return True

    # Check first 1000 bytes for high ratio of non-printable characters
    sample = content[:1000]
    if not sample:
        return False

    non_printable = sum(
        1 for c in sample if ord(c) < 32 and c not in "\n\r\t" and ord(c) != 0
    )
    ratio = non_printable / len(sample)

    # If more than 30% non-printable (excluding common whitespace), likely binary
    return ratio > 0.3


def _normalize_whitespace(line: str) -> str:
    """Normalize whitespace in a line for comparison.

    Preserves leading/trailing structure but normalizes internal whitespace.
    """
    # Preserve line ending
    has_newline = line.endswith(("\n", "\r\n"))
    line_content = line.rstrip("\n\r")

    # Normalize tabs to spaces and collapse multiple spaces
    normalized = " ".join(line_content.split())

    # Restore line ending
    return normalized + ("\n" if has_newline else "")


def get_diff_stats(diff_text: str) -> dict[str, int]:
    """Calculate statistics from a unified diff.

    Args:
        diff_text: Unified diff string

    Returns:
        Dictionary with statistics:
        - lines_added: Number of lines added
        - lines_removed: Number of lines removed
        - hunks: Number of change hunks
        - files_changed: Number of files in diff (usually 1)
    """
    if not diff_text:
        return {
            "lines_added": 0,
            "lines_removed": 0,
            "hunks": 0,
            "files_changed": 0,
        }

    lines = diff_text.splitlines()
    lines_added = 0
    lines_removed = 0
    hunks = 0
    changed_files = set()

    for line in lines:
        if line.startswith("@@"):
            hunks += 1
        elif line.startswith(("+++", "---")):
            changed_files.add(line)
        elif line.startswith("+"):
            lines_added += 1
        elif line.startswith("-"):
            lines_removed += 1

    return {
        "lines_added": lines_added,
        "lines_removed": lines_removed,
        "hunks": hunks,
        "files_changed": len(changed_files) // 2 if changed_files else 0,
    }
