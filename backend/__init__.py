"""Forge automation framework package."""

import warnings
from pathlib import Path
from importlib.metadata import version, PackageNotFoundError

__version__ = "0.55.0"
__package_name__ = "forge-ai"


def get_version() -> str:
    """Get the package version from metadata or pyproject.toml fallback.

    Returns:
        Version string or 'unknown' if version cannot be determined

    """
    # 1. Try metadata (installed package)
    try:
        return version(__package_name__)
    except PackageNotFoundError:
        pass

    # 2. Try pyproject.toml (local dev)
    try:
        root_dir = Path(__file__).resolve().parent.parent
        pyproject_path = root_dir / "pyproject.toml"
        if pyproject_path.exists():
            with open(pyproject_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("version ="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass

    return "0.55.0" # Default fallback


try:
    __version__ = get_version()
except Exception as _exc:
    warnings.warn(
        f"Forge: could not determine package version ({_exc!r}); "
        "reporting '0.55.0'.",
        stacklevel=1,
    )
    __version__ = "0.55.0"


__all__ = ["__version__", "__package_name__", "get_version"]
