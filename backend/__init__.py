"""Grinta package."""

import warnings

# Suppress only known, specific third-party DeprecationWarnings.
# Do NOT use a blanket `category=DeprecationWarning` filter — that silences
# warnings from Grinta's own code and newly added dependencies too.
#
# Pattern: warnings.filterwarnings('ignore', message=<regex>, category=DeprecationWarning, module=<regex>)
# Add a new entry for each third-party library that produces noise, scoped as
# narrowly as possible (prefer `module=` + `message=` over category-only).

# asttokens / astroid: fires from frozen importlib frames; cannot be caught by
# module-based filters alone because the source frame is internal to importlib.
warnings.filterwarnings(
    'ignore',
    message=r'.*asttokens.*',
    category=DeprecationWarning,
)
warnings.filterwarnings(
    'ignore',
    message=r'.*astroid.*',
    category=DeprecationWarning,
)

# google-genai (Gemini SDK) subclasses aiohttp.ClientSession — noisy on import.
warnings.filterwarnings(
    'ignore',
    message=r'Inheritance class AiohttpClientSession from ClientSession is discouraged',
    category=DeprecationWarning,
)

# anthropic SDK: uses deprecated pkg_resources internals in some versions.
warnings.filterwarnings(
    'ignore',
    message=r'.*pkg_resources.*',
    category=DeprecationWarning,
    module=r'anthropic.*',
)

# tree-sitter <0.25 exposes a deprecated Language constructor form.
warnings.filterwarnings(
    'ignore',
    message=r'.*Language\(\) with a shared library.*',
    category=DeprecationWarning,
    module=r'tree_sitter.*',
)

from importlib.metadata import PackageNotFoundError, version  # noqa: E402
from pathlib import Path  # noqa: E402

_DEFAULT_VERSION = '1.0.0'
__version__ = _DEFAULT_VERSION
__package_name__ = 'grinta'


def get_version() -> str:
    """Get the package version, preferring the local source tree when present."""
    from_pyproject = _version_from_pyproject()
    if from_pyproject:
        return from_pyproject
    from_metadata = _version_from_metadata()
    if from_metadata:
        return from_metadata
    return _DEFAULT_VERSION


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
        with pyproject_path.open('r', encoding='utf-8') as f:
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
        f'Grinta: could not determine package version ({_exc!r}); reporting '
        f'{_DEFAULT_VERSION!r}.',
        stacklevel=1,
    )
    __version__ = _DEFAULT_VERSION


__all__ = ['__version__', '__package_name__', 'get_version']
