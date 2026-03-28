"""Pure Python file search fallback.

Provides file search functionality without external dependencies (ripgrep/grep).
Slower but guaranteed to work on all platforms.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path

from backend.core.logger import forge_logger as logger
from backend.utils.regex_limits import try_compile_user_regex


class PythonSearcher:
    """Pure Python file search implementation.

    This is a fallback when ripgrep/grep are not available.
    It's slower but works everywhere without dependencies.
    """

    def __init__(self, case_sensitive: bool = True) -> None:
        """Initialize the searcher.

        Args:
            case_sensitive: Whether to perform case-sensitive search
        """
        self.case_sensitive = case_sensitive

    def search_files(
        self,
        pattern: str,
        directory: str | Path,
        file_pattern: str | None = None,
        max_results: int = 1000,
    ) -> list[tuple[Path, int, str]]:
        """Search for pattern in files.

        Args:
            pattern: Regex pattern to search for
            directory: Directory to search in
            file_pattern: Optional glob pattern for file filtering (e.g., "*.py")
            max_results: Maximum number of results to return

        Returns:
            List of (file_path, line_number, line_content) tuples
        """
        directory = Path(directory)
        if not directory.exists():
            logger.warning("Search directory does not exist: %s", directory)
            return []

        flags = 0 if self.case_sensitive else re.IGNORECASE
        regex, err = try_compile_user_regex(pattern, flags)
        if regex is None:
            logger.error("Rejected regex pattern '%s': %s", pattern, err)
            return []

        results: list[tuple[Path, int, str]] = []

        # Walk directory and search files
        for file_path in self._iter_files(directory, file_pattern):
            if len(results) >= max_results:
                logger.warning("Reached max results (%s), stopping search", max_results)
                break

            try:
                results.extend(
                    self._search_file(file_path, regex, max_results - len(results))
                )
            except Exception as e:
                logger.debug("Error searching file %s: %s", file_path, e)
                continue

        return results

    def _iter_files(
        self,
        directory: Path,
        file_pattern: str | None = None,
    ) -> Iterator[Path]:
        """Iterate over files in directory.

        Args:
            directory: Directory to search
            file_pattern: Optional glob pattern for filtering

        Yields:
            File paths
        """
        try:
            if file_pattern:
                # Use glob pattern
                yield from directory.rglob(file_pattern)
            else:
                # All files
                for root, _, files in os.walk(directory):
                    root_path = Path(root)
                    for file in files:
                        yield root_path / file
        except (PermissionError, OSError) as e:
            logger.debug("Cannot access directory %s: %s", directory, e)

    def _search_file(
        self,
        file_path: Path,
        regex: re.Pattern,
        max_results: int,
    ) -> list[tuple[Path, int, str]]:
        """Search a single file for pattern matches.

        Args:
            file_path: Path to file to search
            regex: Compiled regex pattern
            max_results: Maximum results to return from this file

        Returns:
            List of (file_path, line_number, line_content) tuples
        """
        results: list[tuple[Path, int, str]] = []

        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                for line_num, line in enumerate(f, start=1):
                    if len(results) >= max_results:
                        break

                    if regex.search(line):
                        results.append((file_path, line_num, line.rstrip()))
        except (PermissionError, OSError, UnicodeDecodeError):
            # Skip files we can't read
            pass

        return results

    def search_content(
        self,
        pattern: str,
        content: str,
    ) -> list[tuple[int, str]]:
        """Search for pattern in string content.

        Args:
            pattern: Regex pattern to search for
            content: String content to search

        Returns:
            List of (line_number, line_content) tuples
        """
        flags = 0 if self.case_sensitive else re.IGNORECASE
        regex, err = try_compile_user_regex(pattern, flags)
        if regex is None:
            logger.error("Rejected regex pattern '%s': %s", pattern, err)
            return []

        results: list[tuple[int, str]] = []
        for line_num, line in enumerate(content.splitlines(), start=1):
            if regex.search(line):
                results.append((line_num, line))

        return results
