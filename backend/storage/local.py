"""Local filesystem-backed FileStore implementation."""

from __future__ import annotations

import os
import shutil
import tempfile

from backend.core.logger import FORGE_logger as logger
from backend.storage.files import FileStore


class LocalFileStore(FileStore):
    """Disk-backed FileStore using local filesystem paths."""

    root: str

    def __init__(self, root: str) -> None:
        """Normalize and create the storage root directory path."""
        if root.startswith("~"):
            root = os.path.expanduser(root)
        self.root = root
        os.makedirs(self.root, exist_ok=True)

    def get_full_path(self, path: str) -> str:
        """Convert relative path to full filesystem path with security validation.

        Args:
            path: Relative path

        Returns:
            Absolute path within storage root (validated and safe)

        Raises:
            ValueError: If path validation fails (traversal, boundary violation, etc.)

        """
        try:
            from backend.core.type_safety.path_validation import SafePath

            # Use SafePath for security validation
            safe_path = SafePath.validate(
                path,
                workspace_root=self.root,
                must_be_relative=True,  # Enforce storage root boundaries
            )
            return str(safe_path.path)
        except ImportError as imp_err:
            # SafePath module not available — fall back to manual validation
            logger.warning(
                "SafePath module not available, using manual path validation"
            )
            path = path.removeprefix("/")
            full = os.path.normpath(os.path.join(self.root, path))
            # Ensure the resolved path is still under root
            if not full.startswith(os.path.normpath(self.root)):
                raise ValueError(f"Path '{path}' escapes storage root") from imp_err
            return full
        except Exception as e:
            # Fail CLOSED — do NOT fall back to naive join on security rejection
            raise ValueError(f"Path validation rejected '{path}': {e}") from e

    def write(self, path: str, contents: str | bytes) -> None:
        """Write file to local filesystem.

        Args:
            path: File path relative to storage root
            contents: Content to write

        """
        full_path = self.get_full_path(path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        # Atomic write: write to a temp file in the same directory and replace.
        # This prevents partially-written files (e.g., JSON event files) if the
        # process crashes mid-write.
        dir_name = os.path.dirname(full_path)
        fd: int | None = None
        tmp_path: str | None = None
        try:
            fd, tmp_path = tempfile.mkstemp(
                prefix=f".{os.path.basename(full_path)}.tmp.",
                dir=dir_name,
            )
            mode = "w" if isinstance(contents, str) else "wb"
            encoding = "utf-8" if isinstance(contents, str) else None

            with os.fdopen(fd, mode, encoding=encoding) as f:
                fd = None
                f.write(contents)
                f.flush()
                os.fsync(f.fileno())

            os.replace(tmp_path, full_path)
            tmp_path = None
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except Exception:
                    logger.warning(
                        "Failed to close temp file descriptor", exc_info=True
                    )
            if tmp_path is not None:
                try:
                    os.remove(tmp_path)
                except Exception:
                    logger.warning(
                        "Failed to remove temp file %s", tmp_path, exc_info=True
                    )

    def read(self, path: str) -> str:
        """Read file from local filesystem.

        Args:
            path: File path relative to storage root

        Returns:
            File content as string

        """
        full_path = self.get_full_path(path)
        with open(full_path, encoding="utf-8") as f:
            return f.read()

    def list(self, path: str) -> list[str]:
        """List files/directories in local filesystem path.

        Args:
            path: Directory path relative to storage root

        Returns:
            List of file/directory names

        """
        full_path = self.get_full_path(path)
        files: list[str] = []
        for f in os.listdir(full_path):
            joined = os.path.join(path, f)
            norm = joined.replace("\\", "/")
            if os.path.isdir(self.get_full_path(joined)) and (not norm.endswith("/")):
                norm = f"{norm}/"
            files.append(norm)
        return files

    def delete(self, path: str) -> None:
        """Delete file or directory from local filesystem.

        Args:
            path: Path to delete

        """
        try:
            full_path = self.get_full_path(path)
            if not os.path.exists(full_path):
                logger.debug("Local path does not exist: %s", full_path)
                return
            if os.path.isfile(full_path):
                os.remove(full_path)
                logger.debug("Removed local file: %s", full_path)
            elif os.path.isdir(full_path):
                shutil.rmtree(full_path)
                logger.debug("Removed local directory: %s", full_path)
        except Exception as e:
            logger.error("Error clearing local file store: %s", str(e))
