"""Core unit-test hooks."""

from __future__ import annotations

from typing import Any


def pytest_collection_modifyitems(config: Any, items: list[Any]) -> None:
    """Run ``test_logger_init`` last — it reloads ``backend.core.logger`` and would
    break ``isinstance(..., AppLoggerAdapter)`` in other modules loaded earlier.
    """

    def _is_logger_reload_module(item: Any) -> bool:
        return str(item.fspath).replace('\\', '/').endswith('test_logger_init.py')

    tail = [i for i in items if _is_logger_reload_module(i)]
    head = [i for i in items if not _is_logger_reload_module(i)]
    items[:] = head + tail
