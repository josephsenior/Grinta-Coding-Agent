"""In-memory FileStore useful for tests and ephemeral sessions."""

from __future__ import annotations

from backend.core.logger import app_logger as logger
from backend.persistence.files import FileStore


class InMemoryFileStore(FileStore):
    """Ephemeral FileStore that keeps files within process memory."""

    files: dict[str, str]

    def __init__(self, files: dict[str, str] | None = None) -> None:
        """Initialize optional pre-populated file dictionary."""
        self.files = {}
        if files is not None:
            self.files = files

    def write(self, path: str, contents: str | bytes) -> None:
        """Write to in-memory file store.

        Args:
            path: File path
            contents: Content to write

        """
        if isinstance(contents, bytes):
            contents = contents.decode("utf-8")
        self.files[path] = contents

    def read(self, path: str) -> str:
        """Read from in-memory file store.

        Args:
            path: File path

        Returns:
            File content

        Raises:
            FileNotFoundError: If file doesn't exist

        """
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def list(self, path: str) -> list[str]:
        """List files/directories in memory at given path.

        Args:
            path: Directory path

        Returns:
            List of file/directory names

        """
        files: list[str] = []
        for file in self.files:
            norm_file = file.replace("\\", "/")
            if not norm_file.startswith(path):
                continue
            suffix = norm_file.removeprefix(path)
            parts = suffix.split("/")
            if parts[0] == "":
                parts.pop(0)
            if len(parts) == 1:
                if not path:
                    files.append(norm_file.lstrip("/"))
                else:
                    files.append(norm_file)
            else:
                dir_path = f"{path.rstrip('/')}/{parts[0]}/" if path else f"{parts[0]}/"
                if dir_path not in files:
                    files.append(dir_path)
        return files

    def delete(self, path: str) -> None:
        """Delete from in-memory file store.

        Args:
            path: Path to delete (file or directory prefix)

        """
        try:
            keys_to_delete = [key for key in self.files if key.startswith(path)]
            for key in keys_to_delete:
                del self.files[key]
            logger.info("Cleared in-memory file store: %s", path)
        except Exception as e:
            logger.error("Error clearing in-memory file store: %s", str(e))
