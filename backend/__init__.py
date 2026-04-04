"""App automation framework package."""

import warnings

# Kill ALL third-party DeprecationWarnings before anything else runs.
# The asttokens/astroid warning fires from frozen importlib frames and
# can't be caught by module-based filters.
warnings.filterwarnings('ignore', category=DeprecationWarning)

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

__version__ = '0.55.0'
__package_name__ = 'app-ai'


def get_version() -> str:
    """Get the package version from metadata or pyproject.toml fallback."""
    from_metadata = _version_from_metadata()
    if from_metadata:
        return from_metadata
    from_pyproject = _version_from_pyproject()
    if from_pyproject:
        return from_pyproject
    return '0.55.0'


def _version_from_metadata() -> str | None:
    """Try to get version from installed package metadata."""
    try:
        return version(__package_name__)
    except PackageNotFoundError:
        return None


def _version_from_pyproject() -> str | None:
    """Try to get version from pyproject.toml (local dev)."""
    try:
        root_dir = Path(__file__).resolve().parent.parent
        pyproject_path = root_dir / 'pyproject.toml'
        if not pyproject_path.exists():
            return None
        with open(pyproject_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip().startswith('version ='):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return None


try:
    __version__ = get_version()
except Exception as _exc:
    warnings.warn(
        f"App: could not determine package version ({_exc!r}); reporting '0.55.0'.",
        stacklevel=1,
    )
    __version__ = '0.55.0'


__all__ = ['__version__', '__package_name__', 'get_version']
