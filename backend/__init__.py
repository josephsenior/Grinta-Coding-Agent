"""Forge automation framework package."""

import os
from pathlib import Path

__package_name__ = "FORGE_ai"


def get_version():
    """Get the package version from pyproject.toml or installed package metadata.

    Returns:
        Version string or 'unknown' if version cannot be determined

    """
    try:
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidate_paths = [
            Path(root_dir) / "pyproject.toml",
            Path(root_dir) / "forge" / "pyproject.toml",
        ]
        for file_path in candidate_paths:
            if file_path.is_file():
                with open(file_path, encoding="utf-8") as f:
                    for line in f:
                        if line.strip().startswith("version ="):
                            return line.split("=", 1)[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    try:
        from importlib.metadata import version

        return version(__package_name__)
    except ImportError:
        pass
    try:
        from pkg_resources import DistributionNotFound, get_distribution

        return get_distribution(__package_name__).version
    except (ImportError, DistributionNotFound):
        pass
    return "unknown"


try:
    __version__ = get_version()
except Exception as _exc:
    import warnings as _w

    _w.warn(
        f"Forge: could not determine package version ({_exc!r}); "
        "reporting 'unknown'. Check that pyproject.toml is readable.",
        stacklevel=1,
    )
    __version__ = "unknown"


__all__ = ["__version__", "__package_name__", "get_version"]
