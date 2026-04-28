"""Pure Python file operations fallback.

Cross-platform file operations that work without external dependencies.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from backend.core.logger import app_logger as logger
from backend.core.os_capabilities import OS_CAPS


class PythonFileOps:
    """Pure Python file operations.

    Provides cross-platform file operations without external dependencies.
    """

    @staticmethod
    def normalize_path(path: str | Path) -> Path:
        """Normalize path for current platform.

        Args:
            path: Path to normalize

        Returns:
            Normalized Path object
        """
        return Path(path).resolve()

    @staticmethod
    def is_hidden(path: str | Path) -> bool:
        """Check if file/directory is hidden (platform-aware).

        Args:
            path: Path to check

        Returns:
            True if hidden, False otherwise
        """
        path = Path(path)

        if OS_CAPS.is_windows:
            # Windows: check FILE_ATTRIBUTE_HIDDEN
            try:
                attrs = os.stat(path).st_file_attributes  # type: ignore
                return bool(attrs & stat.FILE_ATTRIBUTE_HIDDEN)  # type: ignore
            except (AttributeError, OSError):
                # Fallback: check if name starts with dot
                return path.name.startswith('.')
        else:
            # Unix: files starting with dot are hidden
            return path.name.startswith('.')

    @staticmethod
    def list_directory(
        directory: str | Path,
        include_hidden: bool = False,
        recursive: bool = False,
    ) -> list[Path]:
        """List files in directory (platform-aware)."""
        directory = Path(directory)
        if not directory.is_dir():
            logger.warning('Not a directory: %s', directory)
            return []

        try:
            if recursive:
                results = PythonFileOps._list_recursive(directory, include_hidden)
            else:
                results = PythonFileOps._list_non_recursive(directory, include_hidden)
        except (PermissionError, OSError) as e:
            logger.warning('Cannot list directory %s: %s', directory, e)
            results = []

        return sorted(results)

    @staticmethod
    def _list_recursive(directory: Path, include_hidden: bool) -> list[Path]:
        """Perform recursive directory listing with hidden file filtering."""
        results: list[Path] = []
        for root, dirs, files in os.walk(directory):
            root_path = Path(root)

            # Filter hidden directories in-place to prevent further recursion
            if not include_hidden:
                dirs[:] = [
                    d for d in dirs if not PythonFileOps.is_hidden(root_path / d)
                ]

            for file in files:
                file_path = root_path / file
                if include_hidden or not PythonFileOps.is_hidden(file_path):
                    results.append(file_path)
        return results

    @staticmethod
    def _list_non_recursive(directory: Path, include_hidden: bool) -> list[Path]:
        """Perform non-recursive directory listing with hidden file filtering."""
        results: list[Path] = []
        for item in directory.iterdir():
            if include_hidden or not PythonFileOps.is_hidden(item):
                results.append(item)
        return results

    @staticmethod
    def safe_read_text(
        file_path: str | Path,
        encoding: str = 'utf-8',
        errors: str = 'ignore',
    ) -> str | None:
        """Safely read text file with fallback encoding.

        Args:
            file_path: Path to file
            encoding: Primary encoding to try
            errors: How to handle encoding errors

        Returns:
            File content or None if unreadable
        """
        file_path = Path(file_path)

        try:
            return file_path.read_text(encoding=encoding, errors=errors)
        except (PermissionError, OSError, UnicodeDecodeError) as e:
            logger.debug('Cannot read file %s: %s', file_path, e)
            return None

    @staticmethod
    def safe_write_text(
        file_path: str | Path,
        content: str,
        encoding: str = 'utf-8',
        create_dirs: bool = True,
    ) -> bool:
        """Safely write text to file.

        Args:
            file_path: Path to file
            content: Content to write
            encoding: Encoding to use
            create_dirs: Whether to create parent directories

        Returns:
            True if successful, False otherwise
        """
        file_path = Path(file_path)

        try:
            if create_dirs:
                file_path.parent.mkdir(parents=True, exist_ok=True)

            file_path.write_text(content, encoding=encoding)
            return True
        except (PermissionError, OSError, UnicodeEncodeError) as e:
            logger.error('Cannot write file %s: %s', file_path, e)
            return False

    @staticmethod
    def get_file_size(file_path: str | Path) -> int | None:
        """Get file size in bytes.

        Args:
            file_path: Path to file

        Returns:
            File size in bytes or None if error
        """
        try:
            return Path(file_path).stat().st_size
        except (OSError, FileNotFoundError):
            return None

    @staticmethod
    def is_executable(file_path: str | Path) -> bool:
        """Check if file is executable (platform-aware).

        Args:
            file_path: Path to file

        Returns:
            True if executable, False otherwise
        """
        file_path = Path(file_path)

        if OS_CAPS.is_windows:
            # Windows: check extension
            return file_path.suffix.lower() in ('.exe', '.bat', '.cmd', '.ps1')
        return bool(os.access(file_path, os.X_OK))
