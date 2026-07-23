from __future__ import annotations

import importlib
from typing import Any

from backend.execution.server.base import Runtime
from backend.utils.import_utils import get_impl


def _lazy_import(module_path: str, attr: str) -> Any:
    module = importlib.import_module(module_path)
    return getattr(module, attr)


# Map runtime keys to (module, attribute) for lazy loading
_DEFAULT_RUNTIME_IMPORTS: dict[str, tuple[str, str]] = {
    'local': (
        'backend.execution.drivers.local.local_runtime_inprocess',
        'LocalRuntimeInProcess',
    ),
}

_ALL_RUNTIME_KEYS = set(_DEFAULT_RUNTIME_IMPORTS.keys())


def get_runtime_cls(name: Any) -> type[Runtime]:
    """If name is one of the predefined runtime names (e.g. 'local'), return its class.

    Otherwise attempt to resolve name as subclass of Runtime and return it.
    Raise on invalid selections.
    """
    if not isinstance(name, str):
        mock_name = getattr(name, '_mock_name', None)
        if isinstance(mock_name, str) and mock_name in _DEFAULT_RUNTIME_IMPORTS:
            name = mock_name
        else:
            name = 'local'

    # Built-in lazy imports
    if name in _DEFAULT_RUNTIME_IMPORTS:
        module_path, attr = _DEFAULT_RUNTIME_IMPORTS[name]
        return _lazy_import(module_path, attr)
    try:
        return get_impl(Runtime, name)
    except Exception as e:
        known_keys = _ALL_RUNTIME_KEYS
        msg = f'Runtime {name} not supported, known are: {known_keys}'
        raise ValueError(msg) from e
