"""Enhanced path validation with security boundaries and sentinel support.

Provides production-grade path validation that:
- Prevents directory traversal attacks
- Validates against workspace boundaries
- Uses sentinel objects for explicit state handling
- Provides type-safe path wrappers
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path
from urllib.parse import unquote

from backend.core.constants import MAX_PATH_LENGTH
from backend.core.os_capabilities import OS_CAPS
from backend.core.type_safety.sentinels import MISSING, Sentinel, is_missing

# Security constants
DANGEROUS_CHARS = ['<', '>', '|', '&', ';', '`', '$', '(', ')', '\n', '\r']
PATH_TRAVERSAL_PATTERNS = ['../', '..\\', '..%2F', '..%5C']
# Regex to match ".." as a standalone path segment (not inside brackets like [...nextauth])
_DOTDOT_SEGMENT_RE = re.compile(r'(^|/)\.\.(/|$)')


class PathValidationError(Exception):
    """Raised when path validation fails."""

    def __init__(self, message: str, path: str | Sentinel = MISSING) -> None:
        """Initialize path validation error.

        Args:
            message: Error message
            path: The invalid path (if available)
        """
        super().__init__(message)
        self.message = message
        self.path = path if not is_missing(path) else '<unknown>'


class SafePath:
    """Type-safe wrapper for validated file paths.

    This class ensures that paths are validated before use and provides
    a clear API for path operations within security boundaries.

    Example:
        >>> path = SafePath.validate("app.py", workspace_root="/workspace")
        >>> str(path)
        '/workspace/app.py'
        >>> path.relative_to_workspace()
        'app.py'
    """

    def __init__(self, path: Path, workspace_root: Path | None = None) -> None:
        """Initialize safe path.

        Args:
            path: Validated Path object
            workspace_root: Optional workspace root for relative path resolution
        """
        self._path = path
        self._workspace_root = workspace_root

    @classmethod
    def validate(
        cls,
        path: str,
        workspace_root: str | Path | None = None,
        must_exist: bool = False,
        must_be_relative: bool = True,
    ) -> SafePath:
        """Validate and create a SafePath.

        Args:
            path: Path string to validate
            workspace_root: Workspace root directory (required if must_be_relative)
            must_exist: Whether path must exist
            must_be_relative: Whether path must be relative to workspace

        Returns:
            SafePath instance

        Raises:
            PathValidationError: If validation fails
        """
        validated_path = validate_and_sanitize_path(
            path, workspace_root, must_exist, must_be_relative
        )
        workspace_path = Path(workspace_root) if workspace_root else None
        return cls(validated_path, workspace_path)

    @property
    def path(self) -> Path:
        """Get the underlying Path object."""
        return self._path

    @property
    def workspace_root(self) -> Path | None:
        """Get the workspace root."""
        return self._workspace_root

    def relative_to_workspace(self) -> str:
        """Get path relative to workspace root.

        Returns:
            Relative path string

        Raises:
            ValueError: If workspace_root is not set
        """
        if self._workspace_root is None:
            raise ValueError('Workspace root not set')
        try:
            return str(self._path.relative_to(self._workspace_root))
        except ValueError:
            # Path is not relative to workspace
            return str(self._path)

    def exists(self) -> bool:
        """Check if path exists."""
        return self._path.exists()

    def is_file(self) -> bool:
        """Check if path is a file."""
        return self._path.is_file()

    def is_dir(self) -> bool:
        """Check if path is a directory."""
        return self._path.is_dir()

    def __str__(self) -> str:
        """Return string representation."""
        return str(self._path)

    def __repr__(self) -> str:
        """Return representation."""
        return f'SafePath({self._path!r}, workspace_root={self._workspace_root!r})'

    def __fspath__(self) -> str:
        """Support os.fspath() protocol."""
        return str(self._path)

    def __eq__(self, other: object) -> bool:
        """Compare paths."""
        if isinstance(other, SafePath):
            return self._path == other._path
        if isinstance(other, str | Path):
            return self._path == Path(other)
        return False

    def __hash__(self) -> int:
        """Make hashable."""
        return hash(self._path)


class PathValidator:
    """Production-grade path validator with security boundaries."""

    def __init__(
        self,
        workspace_root: str | Path,
        allow_absolute: bool = False,
        max_depth: int = 100,
    ) -> None:
        """Initialize path validator.

        Args:
            workspace_root: Root directory for path validation
            allow_absolute: Whether to allow absolute paths
            max_depth: Maximum directory depth allowed
        """
        self.workspace_root = Path(workspace_root).resolve()
        self.allow_absolute = allow_absolute
        self.max_depth = max_depth

        # Ensure workspace root exists
        if not self.workspace_root.exists():
            raise PathValidationError(
                f'Workspace root does not exist: {self.workspace_root}'
            )

    def validate(
        self,
        path: str,
        must_exist: bool = False,
        must_be_file: bool = False,
        must_be_dir: bool = False,
    ) -> SafePath:
        """Validate a path against security boundaries.

        Args:
            path: Path to validate
            must_exist: Whether path must exist
            must_be_file: Whether path must be a file
            must_be_dir: Whether path must be a directory

        Returns:
            SafePath instance

        Raises:
            PathValidationError: If validation fails
        """
        return SafePath.validate(
            path,
            workspace_root=str(self.workspace_root),
            must_exist=must_exist,
            must_be_relative=not self.allow_absolute,
        )


def _validate_path_string(path: str) -> str:
    """Validate path string: empty check, URL decode, null bytes, length, dangerous chars, traversal."""
    if not path:
        raise PathValidationError('Path must be a non-empty string', path)
    try:
        path = unquote(path)
    except Exception as e:
        raise PathValidationError(f'Invalid URL encoding: {e}', path) from e
    if '\x00' in path:
        raise PathValidationError('Path contains null bytes', path)
    if len(path) > MAX_PATH_LENGTH:
        raise PathValidationError(
            f'Path too long (max {MAX_PATH_LENGTH}): {len(path)}', path
        )
    for char in DANGEROUS_CHARS:
        if char in path:
            raise PathValidationError(
                f'Path contains dangerous character: {repr(char)}', path
            )
    normalized_input = path.replace('\\', '/')
    matched_pattern = next(
        (pattern for pattern in PATH_TRAVERSAL_PATTERNS if pattern in normalized_input),
        None,
    )
    has_dotdot_segment = _DOTDOT_SEGMENT_RE.search(normalized_input) is not None
    if matched_pattern is not None:
        raise PathValidationError(
            f'Path traversal detected: {matched_pattern}', path
        )
    # Check for ".." as a standalone path segment (avoids false positives on
    # bracket patterns like Next.js catch-all routes:  [...nextauth])
    if has_dotdot_segment:
        raise PathValidationError('Path traversal detected: ..', path)
    return path


def _is_windows_junction(p: Path) -> bool:
    """Detect a Windows directory junction (created via ``mklink /J``).

    ``Path.is_symlink()`` returns ``False`` for junctions on Windows even
    though they redirect like symlinks. We probe the file attributes via
    ``os.lstat`` and check the ``FILE_ATTRIBUTE_REPARSE_POINT`` bit.
    """
    import os

    if not OS_CAPS.is_windows:
        return False
    try:
        st = os.lstat(p)
    except (OSError, ValueError):
        return False
    # 0x400 = FILE_ATTRIBUTE_REPARSE_POINT
    file_attrs = getattr(st, 'st_file_attributes', 0)
    return bool(file_attrs & 0x400) and not p.is_symlink()


def _reject_unsafe_links(path_str: str, full_path: Path, workspace: Path) -> None:
    """Reject paths that would escape the workspace through links.

    A symlink that resolves *inside* the workspace is allowed (common in
    ``node_modules/.bin``); one that resolves *outside* is rejected with a
    clear error rather than a generic "outside boundary" message.
    """
    # Walk every parent of the supplied path that exists on disk and inspect
    # the link status BEFORE resolution. ``Path.resolve()`` already followed
    # links to compute ``full_path``; here we want the un-followed truth.
    candidate = full_path
    seen: set[Path] = set()
    while True:
        if candidate in seen:
            break
        seen.add(candidate)
        try:
            is_link = candidate.is_symlink() or _is_windows_junction(candidate)
        except OSError:
            is_link = False
        if is_link:
            try:
                target = candidate.resolve()
            except (OSError, RuntimeError) as e:  # RuntimeError: symlink loop
                raise PathValidationError(
                    f'Refusing to follow broken or cyclic link: {path_str}',
                    path_str,
                ) from e
            try:
                target.relative_to(workspace)
            except ValueError:
                raise PathValidationError(
                    'Refusing to follow link that escapes the workspace: '
                    f'{path_str} -> {target}',
                    path_str,
                ) from None
        if candidate == candidate.parent:
            break
        candidate = candidate.parent
        # Stop at the workspace root; nothing above it is in scope.
        try:
            candidate.relative_to(workspace)
        except ValueError:
            break


def _resolve_path(
    path: str, workspace_root: str | Path | None, must_be_relative: bool
) -> Path:
    """Resolve path to absolute Path, enforcing workspace boundary if must_be_relative."""
    try:
        if must_be_relative:
            if workspace_root is None:
                raise PathValidationError(
                    'workspace_root required for relative paths', path
                )
            workspace = Path(workspace_root).resolve()
            normalized = posixpath.normpath(path.lstrip('/'))
            # Strip the virtual /workspace prefix that the LLM uses in tool
            # calls.  Without this, "/workspace/file.py" becomes a literal
            # "workspace/" subdirectory inside the workspace root.
            if normalized.startswith('workspace/'):
                normalized = normalized[len('workspace/') :]
            elif normalized == 'workspace':
                normalized = '.'
            full_path = (workspace / normalized).resolve()
            try:
                rel_parts = full_path.relative_to(workspace).parts
            except ValueError:
                import os

                if OS_CAPS.is_windows:
                    full_str = str(full_path).lower()
                    work_str = str(workspace).lower()
                    if not work_str.endswith(os.sep):
                        work_str += os.sep
                    if not full_str.startswith(
                        work_str
                    ) and full_str != work_str.rstrip(os.sep):
                        raise PathValidationError(
                            f'Path outside workspace boundary: {path}', path
                        ) from None
                    rel_parts = full_path.parts[len(workspace.parts) :]
                else:
                    raise PathValidationError(
                        f'Path outside workspace boundary: {path}', path
                    ) from None
            depth = len(rel_parts)
            if depth > 100:
                raise PathValidationError(
                    f'Path depth too great (max 100): {depth}', path
                )
            _reject_unsafe_links(path, full_path, workspace)
            return full_path
        return Path(path).resolve()
    except (OSError, ValueError) as e:
        raise PathValidationError(f'Invalid path: {e}', path) from e


def validate_and_sanitize_path(
    path: str,
    workspace_root: str | Path | None = None,
    must_exist: bool = False,
    must_be_relative: bool = True,
) -> Path:
    """Validate and sanitize a file path with security checks.

    Prevents directory traversal, validates length, removes dangerous chars,
    enforces workspace boundaries, normalizes paths.
    """
    sanitized = _validate_path_string(path)
    validated_path = _resolve_path(sanitized, workspace_root, must_be_relative)
    if must_exist and not validated_path.exists():
        raise PathValidationError(f'Path does not exist: {path}', path)
    return validated_path
