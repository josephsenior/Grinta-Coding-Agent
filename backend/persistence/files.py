"""Abstract file storage interface implemented by App storage backends."""

from __future__ import annotations

from abc import abstractmethod


class FileStore:
    """Abstract interface for file storage backends.

    Provides basic CRUD operations for storing conversation data,
    agent state, and other persistent information. Implementations
    include local filesystem and in-memory storage.
    """

    root: str = ''

    @abstractmethod
    def write(self, path: str, contents: str | bytes) -> None:
        """Write content to file at given path.

        Args:
            path: File path relative to storage root
            contents: Content to write (string or bytes)

        """

    @abstractmethod
    def read(self, path: str) -> str:
        """Read file content as string.

        Args:
            path: File path relative to storage root

        Returns:
            File content as string

        Raises:
            FileNotFoundError: If file doesn't exist

        """

    @abstractmethod
    def list(self, path: str) -> list[str]:
        """List files and directories at given path.

        Args:
            path: Directory path relative to storage root

        Returns:
            List of file/directory names in path

        Raises:
            FileNotFoundError: If directory doesn't exist

        """

    @abstractmethod
    def delete(self, path: str) -> None:
        """Delete file or directory at given path.

        Args:
            path: Path to delete (file or directory)

        """
